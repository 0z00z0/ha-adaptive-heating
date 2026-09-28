using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// A mode has to reach a room as an instruction, or the settings page writes into itself and the heating never
/// follows anything a person set.
/// </summary>
public sealed class DrivingTheRoomsTests
{
	private const string PresenceHelper = ACabin.PresenceHelper;

	private static readonly DateTimeOffset Morning = new(2026, 9, 24, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public async Task A_mode_reaches_the_room_as_a_temperature()
	{
		// Nothing names a presence helper, so the cabin reads as empty and every room holds its frost temperature.
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		DrivesTheRooms driver = Driver(open, ACabin.WithOneRoom(away: 4, home: 20));

		DrivingPass pass = await driver.RunAsync(States(Thermostat(target: 20.0)), Morning, CancellationToken.None);

		Assert.Equal(HeatingMode.Away, pass.Mode);

		SentCall called = Assert.Single(open.Core.Calls);

		Assert.Equal($"{HeatingActions.ClimateDomain}.{HeatingActions.SetTemperature}", called.Action);
		Assert.Contains("\"temperature\":4", called.Json, StringComparison.Ordinal);
		Assert.Contains($"\"entity_id\":[\"{ACabin.Thermostat}\"]", called.Json, StringComparison.Ordinal);
	}

	[Fact]
	public async Task A_room_with_no_reading_is_switched_on_or_off_in_a_modes_place()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		DrivesTheRooms driver = Driver(open, WithoutAReading(), PresenceHelper);

		await driver.RunAsync(
			States(Thermostat(target: 4.0, current: null, noReading: true), Dropdown("away")),
			Morning,
			CancellationToken.None);

		// The away cell starts on, because the dial on the heater is the only frost protection such a room has.
		SentCall called = Assert.Single(open.Core.Calls);

		Assert.Equal($"{HeatingActions.Domain}.{HeatingActions.SetRegulation}", called.Action);
		Assert.Contains("\"switched\":\"on\"", called.Json, StringComparison.Ordinal);

		await driver.RunAsync(
			States(Thermostat(target: 4.0, current: null, noReading: true), Dropdown("everyday")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Equal(2, open.Core.Calls.Count);
		Assert.Contains("\"switched\":\"off\"", open.Core.Calls[1].Json, StringComparison.Ordinal);

		// No temperature is ever sent to such a room: it has none, and its own dial holds one.
		Assert.DoesNotContain(open.Core.Calls, call =>
			call.Action.EndsWith(HeatingActions.SetTemperature, StringComparison.Ordinal));
	}

	[Fact]
	public async Task A_boundary_changes_what_the_room_holds_and_one_naming_the_same_temperature_replaces_nothing()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		DrivesTheRooms driver = Driver(open, UnderTheDayProfile());

		DrivingPass pass = await driver.RunAsync(States(Thermostat(target: 21.0)), Morning, CancellationToken.None);

		SentCall called = Assert.Single(open.Core.Calls);

		Assert.Equal($"{HeatingActions.ClimateDomain}.{HeatingActions.SetTemperature}", called.Action);
		Assert.Contains("\"temperature\":18", called.Json, StringComparison.Ordinal);

		// The pass says when the next boundary falls, which is what a timer is armed for. The 06:00 entry is in
		// force at 07:00, so the evening one is next.
		Assert.Equal(new DateTimeOffset(2026, 9, 24, 22, 0, 0, TimeSpan.Zero), pass.NextBoundary);

		// The room now holds what the boundary named, so the next pass asks for nothing.
		await driver.RunAsync(States(Thermostat(target: 18.0)), Morning.AddMinutes(1), CancellationToken.None);
		Assert.Single(open.Core.Calls);

		// A temperature set at the card after the boundary arrived stands until the next boundary.
		await driver.RunAsync(
			States(Thermostat(target: 23.0, setAt: "2026-09-24T06:30:00+00:00")),
			Morning.AddMinutes(2),
			CancellationToken.None);

		Assert.Single(open.Core.Calls);
	}

	[Fact]
	public async Task A_warm_up_starts_early_enough_and_only_where_the_deadline_meaning_is_switched_on()
	{
		Assert.False(HeatingDocument.NothingHeardYet().DeadlineMeaningAvailable);

		// The 06:00 entry wants 18 in a room at 16. On four fifths of the half a degree an hour the room
		// starts on, two degrees is five hours, so the heating has to begin at 01:00.
		DateTimeOffset plannedStart = new(2026, 9, 24, 1, 0, 0, TimeSpan.Zero);
		HeatingDocument document = UnderTheDayProfile(BoundaryMeaning.WarmBy);

		await using AnOpenConnection whileOff = await AnOpenConnection.StartAsync();

		await Driver(whileOff, document).RunAsync(States(Thermostat(16.0, 16.0)), plannedStart, CancellationToken.None);

		Assert.DoesNotContain(whileOff.Core.Calls, call =>
			call.Action.EndsWith(HeatingActions.WarmRoomBy, StringComparison.Ordinal));

		HeatingDocument switchedOn = document with { DeadlineMeaningAvailable = true };

		await using AnOpenConnection tooEarly = await AnOpenConnection.StartAsync();

		await Driver(tooEarly, switchedOn)
			.RunAsync(States(Thermostat(16.0, 16.0)), plannedStart.AddMinutes(-30), CancellationToken.None);

		Assert.DoesNotContain(tooEarly.Core.Calls, call =>
			call.Action.EndsWith(HeatingActions.WarmRoomBy, StringComparison.Ordinal));

		await using AnOpenConnection asked = await AnOpenConnection.StartAsync();

		await Driver(asked, switchedOn).RunAsync(States(Thermostat(16.0, 16.0)), plannedStart, CancellationToken.None);

		Assert.Contains(asked.Core.Calls, call =>
			call.Action.EndsWith(HeatingActions.WarmRoomBy, StringComparison.Ordinal)
			&& call.Json.Contains("\"temperature\":18", StringComparison.Ordinal)
			&& call.Json.Contains("2026-09-24T06:00:00", StringComparison.Ordinal));
	}

	/// <summary>One room with a day-profile temperature typed before the boundary, and two boundaries.</summary>
	private static HeatingDocument UnderTheDayProfile(BoundaryMeaning meaning = BoundaryMeaning.Starts)
	{
		HeatingDocument document = ACabin.WithOneRoom();
		DateTimeOffset typed = new(2026, 9, 20, 8, 0, 0, TimeSpan.Zero);

		Dictionary<HeatingMode, Stamped<double>> temperatures = new(document.Rooms[0].ModeTemperatures)
		{
			[HeatingMode.DayProfile] = ACabin.Held(16, typed),
		};

		return document with
		{
			Rooms = [document.Rooms[0] with { ModeTemperatures = temperatures }],
			// Long enough to cover every moment these tests drive at, so what they measure is the profile and not
			// a mode letting go part way through.
			ModeSetByHand = ModeByHand.Of(HeatingMode.DayProfile, ModeByHand.Longest, Stamp.Certain(typed)),
			Profile =
			[
				new ProfileEntry("morning", BoundaryAnchor.ClockTime, TimeSpan.FromHours(6), meaning, Slot(18, typed)),
				new ProfileEntry("evening", BoundaryAnchor.ClockTime, TimeSpan.FromHours(22), meaning, Slot(15, typed)),
			],
		};
	}

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

	private static Dictionary<string, Stamped<double>> Slot(double temperature, DateTimeOffset typed) =>
		new(StringComparer.Ordinal) { [ACabin.RoomId] = ACabin.Held(temperature, typed) };

	private static DrivesTheRooms Driver(AnOpenConnection open, HeatingDocument document, string? presenceHelper = null) =>
		Driver(open, new InMemorySettingsStore(document), new AReporter(), presenceHelper, OutdoorChoice.Nothing);

	private static DrivesTheRooms Driver(
		AnOpenConnection open,
		ISettingsStore store,
		AReporter reporter,
		string? presenceHelper,
		OutdoorChoice outdoor) =>
		ADrivenCabin.Over(open, store, reporter.Reports, presenceHelper, outdoor).Driver;

	private static List<EntityState> States(params string[] entities) =>
		JsonSerializer.Deserialize<List<EntityState>>($"[{string.Join(",", entities)}]")!;

	private static string Thermostat(
		double target,
		double? current = 19.0,
		bool noReading = false,
		string setAt = "2026-09-23T08:00:00+00:00") =>
		$$"""
		{
			"entity_id": "{{ACabin.Thermostat}}",
			"state": "heat",
			"attributes": {
				"friendly_name": "Kitchen",
				"room": "{{ACabin.RoomId}}",
				"integration_version": "0.1.0",
				"vocabulary_version": 1,
				"temperature": {{Invariant(target)}},
				"current_temperature": {{(current is { } reading ? Invariant(reading) : "null")}},
				"hvac_action": "idle",
				"no_reading_at_all": {{(noReading ? "true" : "false")}},
				"outdoor": -5,
				"target_set_at": "{{setAt}}"
			}
		}
		""";

	private static string Dropdown(string state) =>
		$$"""
		{ "entity_id": "{{PresenceHelper}}", "state": "{{state}}", "attributes": { "friendly_name": "Presence" } }
		""";

	// A temperature written the Norwegian way is not a number to a JSON reader.
	private static string Invariant(double value) => value.ToString(CultureInfo.InvariantCulture);
}
