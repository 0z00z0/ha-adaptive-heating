using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// A room set up with nothing to measure it publishes no target temperature, because its heater's own dial holds
/// one. Reading that absence as "not one of our thermostats" takes the room out of the pass and the whole
/// on-or-off path with it, which leaves the room that most needs frost protection the one that cannot get it.
/// </summary>
public sealed class ARoomWithNoPublishedTargetTests
{
	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public async Task A_room_publishing_no_target_is_driven_while_somebody_elses_thermostat_is_skipped()
	{
		await using AnOpenConnection ours = await AnOpenConnection.StartAsync();

		DrivesTheRooms driving = Driver(ours, WithoutAReading());

		DrivingPass drove = await driving.RunAsync(
			States(WithNoTargetAttribute(), Dropdown("away")),
			Morning,
			CancellationToken.None);

		// The room reaches the pass and is driven, though its thermostat publishes no temperature to hold.
		Assert.Equal(1, drove.RoomsDriven);

		SentCall called = Assert.Single(ours.Core.Calls);

		Assert.Equal($"{HeatingActions.Domain}.{HeatingActions.SetRegulation}", called.Action);
		Assert.Contains("\"switched\":\"on\"", called.Json, StringComparison.Ordinal);

		// The other direction, or the assertion above proves only that everything is driven: a climate entity
		// naming the same room but carrying none of this integration's marker is nobody's business here.
		await using AnOpenConnection somebodyElses = await AnOpenConnection.StartAsync();

		DrivingPass skipped = await Driver(somebodyElses, WithoutAReading()).RunAsync(
			States(WithoutTheIntegrationMarker(), Dropdown("away")),
			Morning,
			CancellationToken.None);

		Assert.Equal(0, skipped.RoomsDriven);
		Assert.Empty(somebodyElses.Core.Calls);
	}

	[Fact]
	public async Task The_away_cell_of_a_room_with_no_reading_reaches_the_heater_under_the_away_mode()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		DrivesTheRooms driving = Driver(open, WithoutAReading());

		// The away cell starts on, because the dial on the heater is the only frost protection such a room has.
		await driving.RunAsync(States(WithNoTargetAttribute(), Dropdown("away")), Morning, CancellationToken.None);

		Assert.Contains("\"switched\":\"on\"", Assert.Single(open.Core.Calls).Json, StringComparison.Ordinal);

		// The cell is read and not a constant: the everyday cell starts off, so moving the dropdown switches it off.
		await driving.RunAsync(
			States(WithNoTargetAttribute(), Dropdown("everyday")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Equal(2, open.Core.Calls.Count);
		Assert.Contains("\"switched\":\"off\"", open.Core.Calls[1].Json, StringComparison.Ordinal);

		// No temperature is ever sent to such a room: it has none, and its own dial holds one.
		Assert.DoesNotContain(open.Core.Calls, call =>
			call.Action.EndsWith(HeatingActions.SetTemperature, StringComparison.Ordinal));
	}

	/// <summary>The one room, with the on-or-off cells a room that cannot be measured carries.</summary>
	private static HeatingDocument WithoutAReading()
	{
		HeatingDocument document = ACabin.WithOneRoom();

		return document with
		{
			// Mapped, because the dropdown values below are read through the mapping and not matched as words.
			Presence = ACabin.Mapped,
			Rooms =
			[
				document.Rooms[0] with
				{
					NoReadingAtAll = true,
					ModeSwitches = RoomModeSwitches.Starting(Stamp.Certain(default)),
				},
			],
		};
	}

	private static DrivesTheRooms Driver(AnOpenConnection open, HeatingDocument document) =>
		ADrivenCabin.Over(open, new InMemorySettingsStore(document), new AReporter().Reports, ACabin.PresenceHelper).Driver;

	private static List<EntityState> States(params string[] entities) =>
		JsonSerializer.Deserialize<List<EntityState>>($"[{string.Join(",", entities)}]")!;

	/// <summary>What the cabin's Soverom 2 actually publishes: no <c>temperature</c> attribute and no reading.</summary>
	private static string WithNoTargetAttribute() =>
		$$"""
		{
			"entity_id": "{{ACabin.Thermostat}}",
			"state": "heat",
			"attributes": {
				"friendly_name": "Kitchen",
				"room": "{{ACabin.RoomId}}",
				"integration_version": "0.1.0",
				"vocabulary_version": 1,
				"current_temperature": null,
				"hvac_action": "idle",
				"no_reading_at_all": true,
				"outdoor": -5
			}
		}
		""";

	/// <summary>A thermostat of some other integration's, naming a room of ours and carrying no marker of ours.</summary>
	private static string WithoutTheIntegrationMarker() =>
		$$"""
		{
			"entity_id": "{{ACabin.Thermostat}}",
			"state": "heat",
			"attributes": {
				"friendly_name": "Kitchen",
				"room": "{{ACabin.RoomId}}",
				"current_temperature": 19.0,
				"hvac_action": "idle"
			}
		}
		""";

	private static string Dropdown(string state) =>
		$$"""
		{ "entity_id": "{{ACabin.PresenceHelper}}", "state": "{{state}}", "attributes": { "friendly_name": "Presence" } }
		""";
}
