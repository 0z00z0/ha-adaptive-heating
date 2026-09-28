using System.Diagnostics;

using AdaptiveHeating.AddOn.Integration;

using Microsoft.Extensions.Logging;

using NetDaemon.Client.HomeAssistant.Model;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// The add-on holds one connection to Home Assistant for as long as it runs, and everything it asks of Home
/// Assistant goes over it. The handshake, the numbering and the reopening are the client's; what is proved here
/// is the add-on's own half: which answer reaches which caller, what a caller gets while the connection is not
/// usable, and that a room's change arrives without anything asking for it.
/// </summary>
public sealed class TheOpenConnectionTests
{
	[Fact]
	public async Task A_change_reaches_the_add_on_without_anything_asking_for_it()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync(
			answer: null,
			CoreUnderTest.Thermostat(current: 19.5),
			CoreUnderTest.SomebodyElses());

		// The house is read once as the connection opens, and never again.
		SentCall read = Assert.Single(open.Core.Reads);

		Assert.Equal("get_states", read.Action);
		Assert.Empty(open.Core.Calls);

		// Somebody else's lamp crossed the connection and is not kept: the heating reads its own thermostats, the
		// sun and the presence helper, and a house raises hundreds of changes a minute.
		EntityState only = Assert.Single(open.Connection.House);

		Assert.Equal(ACabin.Thermostat, only.EntityId);
		Assert.Equal(19.5, only.Attributes![HeatingActions.CurrentTemperatureAttribute].GetDouble());

		int told = 0;
		open.Connection.SomethingChanged += () => told++;

		open.Core.Reports(CoreUnderTest.Thermostat(current: 21.5));

		Assert.True(
			await AnOpenConnection.UntilAsync(() => told == 1),
			"A room's change never reached the add-on.");

		// The new reading is in the table, and no message went out to fetch it.
		Assert.Equal(21.5, Assert.Single(open.Connection.House).Attributes![HeatingActions.CurrentTemperatureAttribute].GetDouble());
		Assert.Single(open.Core.Reads);

		// Every event in the house arrives whatever the subscription asked for, so what the heating does not read
		// must not wake a pass over the rooms.
		open.Core.Reports(CoreUnderTest.SomebodyElses());
		open.Core.ReportsSomethingElse();

		Assert.False(
			await AnOpenConnection.UntilAsync(() => told > 1),
			"Somebody else's entity asked for a pass over the rooms.");

		// The client drops the event type it was asked for, measured at 26.36.0, so asking for one buys a second
		// subscription carrying the same traffic. Nothing is named, and the filtering is this side's.
		Assert.Null(Assert.Single(open.Core.SubscribedTo));
	}

	[Fact]
	public async Task The_connection_is_not_usable_while_the_core_is_still_starting()
	{
		// A call made while Home Assistant is coming up is spent and lost, which is the whole reason the client
		// asks whether the core is running and hands nothing over until it says yes.
		await using AnOpenConnection starting = await AnOpenConnection.StartingAsync(
			answer: null,
			CoreUnderTest.Thermostat());

		TaskCompletionSource letTheHouseArrive = new(TaskCreationOptions.RunContinuationsAsynchronously);

		starting.Core.HoldTheRead = letTheHouseArrive;

		starting.Runner.TheCoreIsStarting();

		Assert.False(starting.Connection.IsOpen);
		Assert.Empty(starting.Connection.House);

		Assert.Equal(
			ActionOutcome.Failed,
			await starting.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None));

		Assert.Empty(starting.Core.Calls);

		// The core is up and the house is being read. Still not usable: a pass driven off an empty house would
		// work out what every room should do from nothing at all.
		starting.Runner.HandOver(starting.Core);

		Assert.True(
			await AnOpenConnection.UntilAsync(() => starting.Core.Reads.Count == 1),
			"The house was never read.");

		Assert.False(starting.Connection.IsOpen);

		Assert.Equal(
			ActionOutcome.Failed,
			await starting.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None));

		// The house has landed, so the same call now goes through. Without this half the refusals above would
		// also pass on a connection that never works at all.
		letTheHouseArrive.SetResult();

		Assert.True(
			await AnOpenConnection.UntilAsync(() => starting.Connection.IsOpen),
			"The connection never became usable after the house was read.");

		Assert.Equal(
			ActionOutcome.Called,
			await starting.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None));
	}

	[Fact]
	public async Task A_call_made_while_the_connection_is_down_is_lost_at_once_rather_than_waiting_on_it()
	{
		AnOpenConnection never = AnOpenConnection.NotStarted();
		Stopwatch took = Stopwatch.StartNew();

		ActionOutcome outcome = await never.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None);

		took.Stop();

		Assert.Equal(ActionOutcome.Failed, outcome);

		// Nothing is queued and nothing waits for the answer that is never coming.
		Assert.True(took.Elapsed < CoreConnection.WaitForAnAnswer, $"The call waited {took.Elapsed}.");
		Assert.Contains(
			never.Log.Lines,
			line => line.Level == LogLevel.Warning && line.Said.Contains(ReplyFromTheCore.NoConnection, StringComparison.Ordinal));
	}

	[Fact]
	public async Task Two_calls_in_flight_each_get_the_answer_to_their_own_call()
	{
		// The first call is held back and answered second, so a connection matching answers to calls by the
		// order they arrive in would hand each one the other's answer.
		await using AnOpenConnection open = await AnOpenConnection.StartAsync((self, call) =>
		{
			if (self.Calls.Count == 1)
				return null;

			self.Say(CoreUnderTest.Worked(call.Id));
			self.Say(CoreUnderTest.Refused(
				self.Calls[0].Id,
				"not_found",
				"Service adaptive_heating.hold_temperature not found."));

			return null;
		});

		Task<ActionOutcome> held = open.Thermostats
			.HoldTemperatureAsync(ACabin.Thermostat, 21, TimeSpan.FromHours(2), CancellationToken.None);

		Assert.True(await AnOpenConnection.UntilAsync(() => open.Core.Calls.Count == 1), "The first call never went out.");

		ActionOutcome second = await open.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None);

		Assert.Equal(ActionOutcome.Called, second);
		Assert.Equal(ActionOutcome.UnknownAction, await held);

		// Home Assistant refuses a number that is not greater than the last one on the connection.
		Assert.True(open.Core.Calls[1].Id > open.Core.Calls[0].Id);
	}

	[Fact]
	public async Task A_refusal_carries_back_the_sentence_the_room_gave_for_it()
	{
		const string Said = "Soverom 2 cannot be held above 30 degrees.";

		await using AnOpenConnection open = await AnOpenConnection.StartAsync(
			(_, call) => CoreUnderTest.Refused(call.Id, "service_validation_error", Said));

		ActionOutcome outcome = await open.Thermostats.SetTemperatureAsync(ACabin.Thermostat, 35, CancellationToken.None);

		// A refusal is the room answering, not the add-on failing, and the reason reaches the log with it.
		Assert.Equal(ActionOutcome.Refused, outcome);
		Assert.Contains(open.Log.Lines, line => line.Said.Contains(Said, StringComparison.Ordinal));
	}

	[Fact]
	public async Task A_call_already_sent_when_home_assistant_goes_away_is_answered_rather_than_left_hanging()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync((_, _) => null);

		Task<ActionOutcome> waiting = open.Thermostats.ReturnToTargetAsync(ACabin.Thermostat, CancellationToken.None);

		Assert.True(await AnOpenConnection.UntilAsync(() => open.Core.Calls.Count == 1), "The call never went out.");

		Stopwatch took = Stopwatch.StartNew();

		open.Core.GoAway();

		Assert.Equal(ActionOutcome.Failed, await waiting);

		took.Stop();

		// Every restart would otherwise leave the room waiting twenty seconds for an answer that is not coming.
		Assert.True(took.Elapsed < CoreConnection.WaitForAnAnswer, $"The call waited {took.Elapsed}.");
	}

	[Fact]
	public async Task A_reading_that_arrives_while_the_house_is_being_read_is_the_one_that_stands()
	{
		// A subscription reports only what changes after it starts, so a fresh connection reads the whole house.
		// That answer carries the house as Home Assistant served it, and a change that overtook it must not be
		// put back to the older value.
		CoreUnderTest core = new(answer: null, CoreUnderTest.Thermostat(current: 19.5));
		EntitiesNow house = new();

		house.Reading();
		house.Record(ACabin.Thermostat, CoreUnderTest.Thermostat(current: 22.0));

		Assert.Equal(1, house.Read(core.House, [ACabin.PresenceHelper]));

		EntityState only = Assert.Single(house.Snapshot());

		Assert.Equal(22.0, only.Attributes![HeatingActions.CurrentTemperatureAttribute].GetDouble());
	}

	[Fact]
	public void An_entity_that_has_gone_is_dropped_rather_than_left_reading_its_last_value()
	{
		EntitiesNow house = new();

		house.Read([CoreUnderTest.Thermostat()], [ACabin.PresenceHelper]);

		Assert.Single(house.Snapshot());

		// A room removed in the integration reports no new state. Keeping it would drive a room that is gone.
		house.Record(ACabin.Thermostat, state: null);

		Assert.Empty(house.Snapshot());
	}
}
