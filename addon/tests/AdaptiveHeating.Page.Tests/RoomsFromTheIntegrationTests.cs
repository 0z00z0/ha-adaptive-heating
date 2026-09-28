using System.Text.Json;

using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// Which thermostats in a house belong to this integration. Claiming somebody else's would point every
/// action at a thermostat this system does not control.
/// </summary>
public sealed class RoomsFromTheIntegrationTests
{
	private const string Ours = """
		[
			{
				"entity_id": "climate.kitchen",
				"state": "heat",
				"attributes": {
					"friendly_name": "Kitchen",
					"room": "kitchen",
					"integration_version": "0.1.0",
					"vocabulary_version": 1
				}
			}
		]
		""";

	private const string SomebodyElses = """
		[
			{
				"entity_id": "climate.hallway",
				"state": "heat",
				"attributes": { "friendly_name": "Hallway", "hvac_modes": ["heat", "off"] }
			},
			{
				"entity_id": "climate.cellar",
				"state": "heat",
				"attributes": { "friendly_name": "Cellar", "room": "cellar", "hvac_modes": ["heat", "off"] }
			},
			{
				"entity_id": "sensor.kitchen_temperature",
				"state": "20.4",
				"attributes": { "friendly_name": "Kitchen temperature", "room": "kitchen", "integration_version": "0.1.0" }
			}
		]
		""";

	[Fact]
	public void A_thermostat_of_this_integration_is_kept_and_carries_its_room_and_its_version()
	{
		MergedRooms merged = RoomsFromTheIntegration.Merge(
			HeatingDocument.NothingHeardYet(), States(Ours), PlannerDefaults.Standard);

		Assert.True(merged.Changed);
		Assert.Equal("kitchen", Assert.Single(merged.Document.Rooms).Id);
		Assert.Equal("climate.kitchen", merged.Document.Rooms[0].Thermostat);
		Assert.Equal("Kitchen", merged.Document.Rooms[0].Name);
		Assert.Equal("0.1.0", merged.Document.Versions.Integration);
	}

	[Fact]
	public void A_thermostat_that_is_not_this_integrations_is_left_alone()
	{
		// The other direction, and it has to be proved. One of these is a thermostat naming a room of its own,
		// which everything but the integration's own version would claim.
		MergedRooms merged = RoomsFromTheIntegration.Merge(
			HeatingDocument.NothingHeardYet(), States(SomebodyElses), PlannerDefaults.Standard);

		Assert.False(merged.Changed);
		Assert.Empty(merged.Document.Rooms);
		Assert.Null(merged.Document.Versions.Integration);
	}

	[Fact]
	public void A_room_already_set_up_keeps_its_temperatures_and_gains_its_thermostat()
	{
		HeatingDocument held = ACabin.WithOneRoom(home: 21.5);
		held = held with { Rooms = [held.Rooms[0] with { Thermostat = null }] };

		MergedRooms merged = RoomsFromTheIntegration.Merge(held, States(Ours), PlannerDefaults.Standard);

		Assert.Equal("climate.kitchen", Assert.Single(merged.Document.Rooms).Thermostat);
		Assert.Equal(21.5, merged.Document.Rooms[0].TemperatureFor(HeatingMode.Home));
	}

	[Fact]
	public void A_pass_that_learns_nothing_new_asks_for_no_write()
	{
		MergedRooms first = RoomsFromTheIntegration.Merge(
			HeatingDocument.NothingHeardYet(), States(Ours), PlannerDefaults.Standard);

		MergedRooms again = RoomsFromTheIntegration.Merge(first.Document, States(Ours), PlannerDefaults.Standard);

		Assert.False(again.Changed);
	}

	[Fact]
	public void A_core_that_answers_nothing_leaves_every_room_as_it_was()
	{
		MergedRooms merged = RoomsFromTheIntegration.Merge(ACabin.WithOneRoom(), [], PlannerDefaults.Standard);

		Assert.False(merged.Changed);
		Assert.Equal(ACabin.RoomId, Assert.Single(merged.Document.Rooms).Id);
	}

	private static List<EntityState> States(string json) =>
		JsonSerializer.Deserialize<List<EntityState>>(json)!;
}
