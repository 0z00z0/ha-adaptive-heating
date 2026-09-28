using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Persistence;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// The day profile and boost are reachable no other way, so a mode chosen on the settings page has to win over
/// the one presence selects. It also has to let go on its own: a cabin forgotten on the way out would otherwise
/// be heated until somebody next opened the page.
/// </summary>
public sealed class AModeChosenByHandTests
{
	private const string PresenceHelper = ACabin.PresenceHelper;

	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public async Task It_holds_while_presence_says_otherwise_and_lets_go_when_its_hours_are_up()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		InMemorySettingsStore store = new(ACabin.WithOneRoom() with { Presence = ACabin.Mapped });
		DrivesTheRooms driver = Driver(store, open);

		// Presence alone: the dropdown says the cabin is empty, which selects away and no day profile ever runs.
		DrivingPass presenceAlone = await driver.RunAsync(States(Thermostat(4.0), Dropdown("away")), Morning, CancellationToken.None);

		Assert.Equal(HeatingMode.Away, presenceAlone.Mode);
		Assert.Equal(ModeChosenBy.Presence, driver.InForce.ModeFrom);

		Assert.True(store.SetModeByHand(HeatingMode.DayProfile, TimeSpan.FromHours(4), Stamp.Certain(Morning)).Written);

		// The dropdown has not moved and still says the cabin is empty. The choice wins anyway.
		DrivingPass held = await driver.RunAsync(
			States(Thermostat(4.0), Dropdown("away")),
			Morning.AddHours(3).AddMinutes(59),
			CancellationToken.None);

		Assert.Equal(HeatingMode.DayProfile, held.Mode);
		Assert.Equal(PresenceState.Away, held.Presence);
		Assert.Equal(ModeChosenBy.Hand, driver.InForce.ModeFrom);

		// Nothing happens but time passing: no save, no dropdown change, nobody on the page.
		DrivingPass letGo = await driver.RunAsync(
			States(Thermostat(4.0), Dropdown("away")),
			Morning.AddHours(4),
			CancellationToken.None);

		Assert.Equal(HeatingMode.Away, letGo.Mode);
		Assert.Equal(ModeChosenBy.Presence, driver.InForce.ModeFrom);

		// The choice is left in the document rather than cleared, so the pass that notices writes nothing.
		Assert.NotNull(store.Read().ModeSetByHand);
	}

	/// <summary>The mode presence selects is followed again with nothing further from anybody.</summary>
	[Fact]
	public async Task After_it_lets_go_the_mode_follows_the_dropdown_again()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		InMemorySettingsStore store = new(ACabin.WithOneRoom() with { Presence = ACabin.Mapped });
		DrivesTheRooms driver = Driver(store, open);

		Assert.True(store.SetModeByHand(HeatingMode.Boost, TimeSpan.FromHours(1), Stamp.Certain(Morning)).Written);

		Assert.Equal(
			HeatingMode.Boost,
			(await driver.RunAsync(States(Thermostat(20.0), Dropdown("everyday")), Morning, CancellationToken.None)).Mode);

		// Expired, and the dropdown now says something else again. Presence answers, not the mode last chosen.
		DrivingPass night = await driver.RunAsync(
			States(Thermostat(20.0), Dropdown("night")),
			Morning.AddHours(2),
			CancellationToken.None);

		Assert.Equal(HeatingMode.Night, night.Mode);
		Assert.Equal(ModeChosenBy.Presence, driver.InForce.ModeFrom);
	}

	/// <summary>Releasing it early is the only way back from a mode chosen by mistake before its hours are up.</summary>
	[Fact]
	public async Task Following_presence_again_drops_the_choice_at_once()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		InMemorySettingsStore store = new(ACabin.WithOneRoom() with { Presence = ACabin.Mapped });
		DrivesTheRooms driver = Driver(store, open);

		Assert.True(store.SetModeByHand(HeatingMode.Boost, ModeByHand.Longest, Stamp.Certain(Morning)).Written);
		Assert.True(store.FollowPresenceAgain().Written);

		DrivingPass pass = await driver.RunAsync(States(Thermostat(4.0), Dropdown("away")), Morning, CancellationToken.None);

		Assert.Equal(HeatingMode.Away, pass.Mode);
		Assert.Null(store.Read().ModeSetByHand);
	}

	/// <summary>A restart must not hand a cabin back to presence: the choice and the moment it ends both cross it.</summary>
	[Fact]
	public void The_choice_and_the_moment_it_ends_are_there_after_a_restart()
	{
		string directory = ACabin.ScratchDirectory();
		ClockUnderTest clock = new(ACabin.Typed);

		using (StateStoreRegistry first = Registry(directory))
		{
			DurableSettingsStore store = DurableSettingsStore.Open(first, clock, ACabin.WithOneRoom(), NullLogger.Instance);

			Assert.True(store.SetModeByHand(HeatingMode.DayProfile, TimeSpan.FromHours(6), Stamp.Certain(ACabin.Typed)).Written);
		}

		using StateStoreRegistry second = Registry(directory);
		HeatingDocument back = DurableSettingsStore.Open(second, clock, ACabin.WithOneRoom(), NullLogger.Instance).Read();

		ModeByHand? chosen = back.ModeSetByHand;

		Assert.NotNull(chosen);
		Assert.Equal(HeatingMode.DayProfile, chosen.Wanted);
		Assert.Equal(ACabin.Typed.AddHours(6), chosen.EndsAt);
		Assert.True(chosen.UnexpiredAt(ACabin.Typed.AddHours(5)));
		Assert.False(chosen.UnexpiredAt(ACabin.Typed.AddHours(6)));
	}

	/// <summary>The hours are clamped where they are written, so nothing can store a choice that never lets go.</summary>
	[Fact]
	public void The_hours_it_is_given_are_held_to_their_bounds()
	{
		InMemorySettingsStore store = new(ACabin.WithOneRoom());

		Assert.True(store.SetModeByHand(HeatingMode.Boost, TimeSpan.FromDays(365), Stamp.Certain(ACabin.Typed)).Written);
		Assert.Equal(ACabin.Typed + ModeByHand.Longest, store.Read().ModeSetByHand!.EndsAt);

		Assert.True(store.SetModeByHand(HeatingMode.Boost, TimeSpan.Zero, Stamp.Certain(ACabin.Typed)).Written);
		Assert.Equal(ACabin.Typed + ModeByHand.Shortest, store.Read().ModeSetByHand!.EndsAt);
	}

	/// <summary>A choice made before the clock was set keeps the hours it was given rather than expiring at once.</summary>
	[Fact]
	public void A_choice_made_against_an_unset_clock_carries_its_end_moment_forward()
	{
		DateTimeOffset duringTheOutage = new(2016, 1, 1, 0, 0, 0, TimeSpan.Zero);

		HeatingDocument document = ACabin.WithOneRoom() with
		{
			ModeSetByHand = ModeByHand.Of(HeatingMode.Boost, TimeSpan.FromHours(3), Stamp.AgainstAnUnsetClock(duringTheOutage))
		};

		ModeByHand? chosen = document.WhenTheClockIsSet(ACabin.Typed).ModeSetByHand;

		Assert.NotNull(chosen);
		Assert.Equal(ACabin.Typed.AddHours(3), chosen.EndsAt);
		Assert.True(chosen.UnexpiredAt(ACabin.Typed.AddHours(2)));
	}

	private static StateStoreRegistry Registry(string directory) =>
		new(Path.Combine(directory, "heating.json"), NullLogger<StateStoreRegistry>.Instance);

	private static DrivesTheRooms Driver(ISettingsStore store, AnOpenConnection open) =>
		ADrivenCabin.Over(open, store, new AReporter().Reports, PresenceHelper).Driver;

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
}
