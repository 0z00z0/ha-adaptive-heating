using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// A dropdown value no row maps holds the home mode, which is the expensive one, and a cabin that nobody is in
/// is heated on it. That has to reach a person, because nothing on any screen says it happened.
/// </summary>
public sealed class AnUnrecognisedPresenceValueTests
{
	private const string PresenceHelper = ACabin.PresenceHelper;

	/// <summary>The headline every card about this carries, which is how a test tells it from the outdoor one.</summary>
	private const string TheHeadline = "Presence not recognised";

	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public async Task A_mapped_value_reaches_the_state_its_row_names_and_needs_nobody()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		InMemorySettingsStore store = Store(Mapped());
		DrivesTheRooms driver = Driver(store, open, reporter);

		DrivingPass empty = await driver.RunAsync(
			States(Thermostat(target: 20.0), Dropdown("Borte")),
			Morning,
			CancellationToken.None);

		Assert.Equal(PresenceState.Away, empty.Presence);
		Assert.Equal(HeatingMode.Away, empty.Mode);

		// The option carrying a Norwegian letter, which is where an encoding fault would show.
		DrivingPass arriving = await driver.RunAsync(
			States(Thermostat(target: 4.0), Dropdown("På vei")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Equal(PresenceState.OnTheWay, arriving.Presence);
		Assert.Equal(HeatingMode.Home, arriving.Mode);

		Assert.Empty(AboutPresence(reporter));
		Assert.Empty(Recorded(reporter));
	}

	/// <summary>
	/// The whole point of the mapping: a value the words would call everyday runs away because its row says so,
	/// and the option is then renamed without the cabin moving.
	/// </summary>
	[Fact]
	public async Task A_renamed_option_holds_its_state_and_no_word_is_consulted()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		InMemorySettingsStore store = Store(Mapped());
		DrivesTheRooms driver = Driver(store, open, reporter);

		Assert.Equal(PresenceState.Everyday, PresenceVocabulary.Classify("Ikke hjemme"));

		store.SavePresenceMap(store.Read().Presence.Renamed("Borte", "Ikke hjemme"));

		DrivingPass pass = await driver.RunAsync(
			States(Thermostat(target: 20.0), Dropdown("Ikke hjemme")),
			Morning,
			CancellationToken.None);

		Assert.Equal(PresenceState.Away, pass.Presence);
		Assert.Equal(HeatingMode.Away, pass.Mode);
		Assert.Empty(AboutPresence(reporter));
	}

	[Fact]
	public async Task A_value_no_row_names_holds_the_expensive_mode_and_names_itself_to_a_person()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		DrivesTheRooms driver = Driver(Store(Mapped()), open, reporter);

		DrivingPass pass = await driver.RunAsync(
			States(Thermostat(target: 4.0), Dropdown("Hjemmekontor")),
			Morning,
			CancellationToken.None);

		// The fall-through the owner chose to keep, because a cabin with people in it must not go cold.
		Assert.Equal(PresenceState.Everyday, pass.Presence);
		Assert.Equal(HeatingMode.Home, pass.Mode);

		ACard raised = Assert.Single(AboutPresence(reporter));

		// The value itself, because a record saying only that something was refused does not say what to map.
		Assert.Contains("Hjemmekontor", raised.Message, StringComparison.Ordinal);
		Assert.Contains(PresenceHelper, raised.Message, StringComparison.Ordinal);

		HeatingReport line = Assert.Single(Recorded(reporter));

		Assert.Equal("Hjemmekontor", line.Reading);

		// The same value every minute is not worth a second card.
		await driver.RunAsync(
			States(Thermostat(target: 20.0), Dropdown("Hjemmekontor")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Single(AboutPresence(reporter));

		// A different one is: it is a value nobody has been told about yet.
		await driver.RunAsync(
			States(Thermostat(target: 20.0), Dropdown("Kanskje hjemme")),
			Morning.AddMinutes(2),
			CancellationToken.None);

		Assert.Equal(2, AboutPresence(reporter).Count);
		Assert.Contains("Kanskje hjemme", AboutPresence(reporter)[1].Message, StringComparison.Ordinal);
	}

	/// <summary>Setup: the dropdown's own options are read once, mapped, and never consulted for words again.</summary>
	[Fact]
	public async Task The_options_a_dropdown_offers_are_mapped_once_and_then_only_looked_up()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		InMemorySettingsStore store = Store(ACabin.WithOneRoom(away: 4, home: 20));
		DrivesTheRooms driver = Driver(store, open, reporter);

		Assert.True(store.Read().Presence.IsEmpty);

		DrivingPass pass = await driver.RunAsync(
			States(Thermostat(target: 20.0), DropdownOffering("Borte", "Hjemme", "Natt", "Gjester")),
			Morning,
			CancellationToken.None);

		Assert.Equal(4, store.Read().Presence.Count);
		Assert.Equal(PresenceState.Away, pass.Presence);
		Assert.Equal(HeatingMode.Away, pass.Mode);

		// Nothing was refused, so the setup happened before the value was read rather than after it.
		Assert.Empty(AboutPresence(reporter));

		// A person re-points one row; the next pass reads the row and not the word in it.
		store.SavePresenceMap(PresenceMap.Of([new PresenceOption("Borte", PresenceState.Guest)]));

		DrivingPass after = await driver.RunAsync(
			States(Thermostat(target: 20.0), DropdownOffering("Borte", "Hjemme", "Natt", "Gjester")),
			Morning.AddMinutes(1),
			CancellationToken.None);

		Assert.Equal(PresenceState.Guest, after.Presence);
		Assert.Single(store.Read().Presence.Options!);
	}

	/// <summary>A helper whose options say nothing is left unmapped, and its value reports itself.</summary>
	[Fact]
	public async Task Options_the_words_cannot_tell_apart_are_left_for_a_person()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		AReporter reporter = new();
		InMemorySettingsStore store = Store(ACabin.WithOneRoom(away: 4, home: 20));
		DrivesTheRooms driver = Driver(store, open, reporter);

		DrivingPass pass = await driver.RunAsync(
			States(Thermostat(target: 4.0), DropdownOffering("Eco", "Comfort", "Boost")),
			Morning,
			CancellationToken.None);

		Assert.True(store.Read().Presence.IsEmpty);
		Assert.Equal(HeatingMode.Home, pass.Mode);
		Assert.Single(AboutPresence(reporter));
	}

	private static List<ACard> AboutPresence(AReporter reporter) =>
		[.. reporter.Cards.Raised.Where(card => string.Equals(card.Title, TheHeadline, StringComparison.Ordinal))];

	private static List<HeatingReport> Recorded(AReporter reporter) =>
	[
		.. reporter.Reports.Recent().Entries
			.Select(entry => entry.Report)
			.Where(report => report.What == WhatHappened.PresenceNotRecognised),
	];

	/// <summary>The cabin with every option of its dropdown already mapped, as a setup would have left it.</summary>
	private static HeatingDocument Mapped() =>
		ACabin.WithOneRoom(away: 4, home: 20) with
		{
			Presence = PresenceMap.Of(
			[
				new PresenceOption("Hjemme", PresenceState.Everyday),
				new PresenceOption("Borte", PresenceState.Away),
				new PresenceOption("På vei", PresenceState.OnTheWay),
			])
		};

	private static InMemorySettingsStore Store(HeatingDocument document) => new(document);

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
