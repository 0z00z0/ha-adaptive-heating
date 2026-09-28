using System.Text.Json;

using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.Page.Settings;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// The record goes into a calendar Home Assistant keeps itself and no other, so which integration created a
/// calendar has to be known. Every calendar's capability list looks alike, and the entity registry is what
/// tells them apart.
/// </summary>
public sealed class WhichCalendarsAreOfferedTests
{
	private const string Local = "calendar.adaptiveheating_log";
	private const string Somebody = "calendar.alex_google";

	[Fact]
	public void Every_calendar_is_offered_and_only_a_local_one_is_marked_local()
	{
		IReadOnlyList<CalendarOnOffer> offered = CalendarsInTheHouse.Offered(
			States(
				ACalendar.Entity(Local, "Heating record"),
				ACalendar.Entity(Somebody, "Alex"),
				Thermostat()),
			new Dictionary<string, string>(StringComparer.Ordinal)
			{
				[Local] = CalendarActions.LocalPlatform,
				[Somebody] = "google"
			});

		Assert.Equal(2, offered.Count);

		// Both directions: the local one is marked and the other one is not.
		Assert.True(offered.Single(calendar => calendar.EntityId == Local).Local);
		Assert.False(offered.Single(calendar => calendar.EntityId == Somebody).Local);

		// The name is read beside the choice and the entity id is what it is chosen by.
		Assert.Equal("Alex", offered[0].Name);
		Assert.Equal("Heating record", offered[1].Name);
	}

	[Fact]
	public void A_calendar_the_registry_says_nothing_about_is_offered_and_is_not_local()
	{
		// A registry read that did not go through leaves this empty, and no calendar may then take the record.
		IReadOnlyList<CalendarOnOffer> offered = CalendarsInTheHouse.Offered(
			States(ACalendar.Entity(Local, "Heating record")),
			new Dictionary<string, string>(StringComparer.Ordinal));

		Assert.False(Assert.Single(offered).Local);
	}

	[Fact]
	public void The_registry_answer_names_the_integration_behind_each_calendar()
	{
		JsonElement answer = JsonSerializer.Deserialize<JsonElement>(
			$$"""
			{
				"entity_categories": { "config": 0 },
				"entities": [
					{ "ei": "{{Local}}", "pl": "local_calendar", "en": "Heating record" },
					{ "ei": "{{Somebody}}", "pl": "google", "en": "Alex" },
					{ "ei": "light.hall", "pl": "hue", "en": "Hall" },
					{ "en": "a row with no entity id" }
				]
			}
			""");

		IReadOnlyDictionary<string, string> platforms = EntityRegistryReading.CalendarPlatformsIn(answer);

		// Only the calendars, and each against the integration that made it.
		Assert.Equal(2, platforms.Count);
		Assert.Equal(CalendarActions.LocalPlatform, platforms[Local]);
		Assert.Equal("google", platforms[Somebody]);
	}

	[Fact]
	public async Task The_registry_is_read_once_per_connection_and_only_where_the_house_holds_a_calendar()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync((_, call) =>
			string.Equals(call.Action, CoreConnection.EntityRegistryCommand, StringComparison.Ordinal)
				? RegistryAnswering(call.Id)
				: CoreUnderTest.Worked(call.Id));

		TheCalendarsOnOffer offered = new(open.Connection, NullLogger<TheCalendarsOnOffer>.Instance);

		// A cabin with no calendar never sends the read at all.
		Assert.Empty(await offered.OfferedAsync(States(Thermostat()), CancellationToken.None));
		Assert.Empty(open.Core.Calls);

		IReadOnlyList<CalendarOnOffer> withOne = await offered
			.OfferedAsync(States(ACalendar.Entity(Local, "Heating record")), CancellationToken.None);

		Assert.True(Assert.Single(withOne).Local);
		Assert.Single(open.Core.Calls, Registry);

		// Read once per connection, not once per pass over the rooms.
		await offered.OfferedAsync(States(ACalendar.Entity(Local, "Heating record")), CancellationToken.None);

		Assert.Single(open.Core.Calls, Registry);
	}

	private static bool Registry(SentCall call) =>
		string.Equals(call.Action, CoreConnection.EntityRegistryCommand, StringComparison.Ordinal);

	private static string RegistryAnswering(int id) =>
		$$"""
		{
			"id": {{id.ToString(System.Globalization.CultureInfo.InvariantCulture)}},
			"type": "result",
			"success": true,
			"result": {
				"entity_categories": {},
				"entities": [{ "ei": "{{Local}}", "pl": "local_calendar", "en": "Heating record" }]
			}
		}
		""";

	private static List<EntityState> States(params string[] entities) =>
		JsonSerializer.Deserialize<List<EntityState>>($"[{string.Join(",", entities)}]")!;

	private static string Thermostat() =>
		$$"""
		{ "entity_id": "{{ACabin.Thermostat}}", "state": "heat", "attributes": { "friendly_name": "Kitchen" } }
		""";
}
