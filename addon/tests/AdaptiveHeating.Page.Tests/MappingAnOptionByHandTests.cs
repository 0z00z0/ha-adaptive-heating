using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Persistence;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// The vocabulary knows four groups and the heating has more states than that, so some options can only be
/// mapped by a person. What a person maps has to survive a restart, and the value that was named to them has to
/// stop being the one thing the add-on stays silent about.
/// </summary>
public sealed class MappingAnOptionByHandTests
{
	private const string PresenceHelper = ACabin.PresenceHelper;

	/// <summary>The headline every card about this carries, which is how a test tells it from the outdoor one.</summary>
	private const string TheHeadline = "Presence not recognised";

	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	/// <summary>
	/// The two rows the cabin's own dropdown lands on the wrong state. Neither can be fixed by recognising more
	/// words: one word means away and the option does not, and the other carries no word the vocabulary holds.
	/// </summary>
	[Fact]
	public void The_two_rows_the_words_get_wrong_hold_what_a_person_mapped_after_a_restart()
	{
		string directory = ACabin.ScratchDirectory();
		ClockUnderTest clock = new(ACabin.Typed);

		// What the words say, which is what a setup leaves behind and what a person has to correct.
		Assert.Equal(PresenceState.Everyday, PresenceVocabulary.Classify("Planlagt"));
		Assert.Equal(PresenceState.Away, PresenceVocabulary.Classify("Midlertidig borte"));

		using (StateStoreRegistry first = Registry(directory))
		{
			DurableSettingsStore store = DurableSettingsStore.Open(first, clock, ACabin.WithOneRoom(), NullLogger.Instance);

			SaveOutcome outcome = store.SavePresenceMap(PresenceMap.Of(
			[
				new PresenceOption("Hjemme", PresenceState.Everyday),
				new PresenceOption("Planlagt", PresenceState.PlannedToArrive),
				new PresenceOption("Midlertidig borte", PresenceState.TemporarilyAway),
			]));

			Assert.True(outcome.Written);
		}

		using StateStoreRegistry second = Registry(directory);
		HeatingDocument back = DurableSettingsStore.Open(second, clock, ACabin.WithOneRoom(), NullLogger.Instance).Read();

		Assert.Equal(PresenceState.PlannedToArrive, back.Presence.StateFor("Planlagt"));
		Assert.Equal(PresenceState.TemporarilyAway, back.Presence.StateFor("Midlertidig borte"));

		// And the two now select the opposite mode to the one the words would have picked, which is the point of
		// correcting them: a cabin nobody has reached is not heated, and one somebody stepped out of is not cooled.
		Assert.Equal(HeatingMode.Away, Presence.ModeFor(back.Presence.StateFor("Planlagt")!.Value));
		Assert.Equal(HeatingMode.Home, Presence.ModeFor(back.Presence.StateFor("Midlertidig borte")!.Value));

		// The options the dropdown offers are a reading, so they do not cross a restart and are read again.
		Assert.Empty(back.PresenceOptionsOffered);
	}

	/// <summary>
	/// An option the settings store has never seen is only editable because the list the dropdown offers reaches
	/// the page. A helper whose words mean nothing here leaves no stored row at all.
	/// </summary>
	[Fact]
	public async Task The_options_a_dropdown_offers_reach_the_page_even_where_nothing_could_be_mapped()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		InMemorySettingsStore store = new(ACabin.WithOneRoom());
		DrivesTheRooms driver = Driver(store, open, new AReporter());

		await driver.RunAsync(
			States(Thermostat(4.0), DropdownOffering("Eco", "Comfort", "Boost")),
			Morning,
			CancellationToken.None);

		// Refused, as the guard is meant to: three options the words cannot tell apart are not guessed at.
		Assert.True(store.Read().Presence.IsEmpty);

		// And yet every one of them is on the page, which is the only way a person can map them.
		Assert.Equal(new[] { "Eco", "Comfort", "Boost" }, store.Read().PresenceOptionsOffered);
	}

	/// <summary>
	/// The card names the value, so mapping that value must clear the latch behind it. Leaving the latch on a
	/// value that now has a row would keep the add-on silent if the row were later taken off again.
	/// </summary>
	[Fact]
	public async Task Mapping_the_value_a_card_named_clears_the_latch_behind_it()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		InMemorySettingsStore store = new(ACabin.WithOneRoom() with { Presence = ACabin.Mapped });
		DrivesTheRooms driver = Driver(store, open, reporter);

		DrivingPass refused = await driver.RunAsync(
			States(Thermostat(4.0), Dropdown("Hjemmekontor")),
			Morning,
			CancellationToken.None);

		// The expensive lean, and a card naming the value so a person knows what to map.
		Assert.Equal(HeatingMode.Home, refused.Mode);
		Assert.Contains("Hjemmekontor", Assert.Single(AboutPresence(reporter)).Message, StringComparison.Ordinal);

		store.SavePresenceMap(PresenceMap.Of(
			[.. ACabin.Mapped.Options!, new PresenceOption("Hjemmekontor", PresenceState.TemporarilyAway)]));

		DrivingPass mapped = await driver.RunAsync(
			States(Thermostat(20.0), Dropdown("Hjemmekontor")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Equal(PresenceState.TemporarilyAway, mapped.Presence);
		Assert.Single(AboutPresence(reporter));

		// The row taken off again: the value is refused afresh and names itself a second time rather than
		// being the one value the add-on has nothing left to say about.
		store.SavePresenceMap(ACabin.Mapped);

		await driver.RunAsync(
			States(Thermostat(20.0), Dropdown("Hjemmekontor")),
			Morning.AddMinutes(2),
			CancellationToken.None);

		Assert.Equal(2, AboutPresence(reporter).Count);
	}

	private static List<ACard> AboutPresence(AReporter reporter) =>
		[.. reporter.Cards.Raised.Where(card => string.Equals(card.Title, TheHeadline, StringComparison.Ordinal))];

	private static StateStoreRegistry Registry(string directory) =>
		new(Path.Combine(directory, "heating.json"), NullLogger<StateStoreRegistry>.Instance);

	private static DrivesTheRooms Driver(ISettingsStore store, AnOpenConnection open, AReporter reporter) =>
		ADrivenCabin.Over(open, store, reporter.Reports, PresenceHelper).Driver;

	private static List<EntityState> States(params string[] entities) =>
		JsonSerializer.Deserialize<List<EntityState>>($"[{string.Join(",", entities)}]")!;

	private static string Thermostat(double target) =>
		$$"""
		{
			"entity_id": "{{ACabin.Thermostat}}",
			"state": "heat",
			"attributes": {
				"friendly_name": "Kitchen",
				"room": "{{ACabin.RoomId}}",
				"integration_version": "0.1.0",
				"vocabulary_version": 1,
				"temperature": {{target.ToString(CultureInfo.InvariantCulture)}},
				"current_temperature": 19,
				"hvac_action": "idle",
				"no_reading_at_all": false,
				"outdoor": -5,
				"target_set_at": "2026-09-23T08:00:00+00:00"
			}
		}
		""";

	private static string Dropdown(string state) =>
		$$"""
		{ "entity_id": "{{PresenceHelper}}", "state": "{{state}}", "attributes": { "friendly_name": "Presence" } }
		""";

	/// <summary>The dropdown as Home Assistant reports one: its value, and the options it offers beside it.</summary>
	private static string DropdownOffering(string state, params string[] options) =>
		$$"""
		{
			"entity_id": "{{PresenceHelper}}",
			"state": "{{state}}",
			"attributes": {
				"friendly_name": "Presence",
				"options": [{{string.Join(", ", options.Prepend(state).Distinct(StringComparer.Ordinal).Select(one => $"\"{one}\""))}}]
			}
		}
		""";
}
