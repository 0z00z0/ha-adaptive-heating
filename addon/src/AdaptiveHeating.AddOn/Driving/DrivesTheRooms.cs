using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Driving;

/// <summary>What one pass decided, for the record and for a test to read.</summary>
/// <param name="NextBoundary">The instant the next schedule boundary falls on, or <c>null</c> where none applies.</param>
/// <param name="Outdoor">The outdoor temperature the pass ran on, and where it came from.</param>
/// <param name="NextArrival">The arrival this pass planned against, or <c>null</c> where none is ahead.</param>
/// <param name="Recorded">How many finished warm-ups reached the record calendar on this pass.</param>
internal sealed record DrivingPass(
	HeatingMode Mode,
	PresenceState Presence,
	int RoomsDriven,
	int Sent,
	DateTimeOffset? NextBoundary,
	OutdoorReading Outdoor,
	DateTimeOffset? NextArrival,
	int Recorded);

/// <summary>
/// One pass over the rooms: the mode in force resolved to an instruction per room, the day's boundary, any
/// warm-up that is due, and what each room's own behaviour teaches.
/// </summary>
/// <remarks>
///     Nothing here decides a rule. The mode table, the precedence order, the boundary placement, the warm-up
///     arithmetic and the two learning watchers all live in the planner; this reads the thermostats, hands the
///     planner numbers, and calls the actions its answers name.
/// </remarks>
internal sealed class DrivesTheRooms
{
	/// <summary>How far two temperatures may sit apart and still count as the same one. Half the thermostat's step.</summary>
	private const double SameTemperature = 0.25;

	/// <summary>How many rises one room keeps. A winter of them fits, and nothing reads the ones beyond it.</summary>
	private const int RisesKept = 400;

	private readonly ISettingsStore _store;
	private readonly Thermostats _thermostats;
	private readonly PlannerDefaults _defaults;
	private readonly TheHouseholdClock _household;
	private readonly string? _presenceHelper;
	private readonly OutdoorChoice _outdoor;
	private readonly ReportsWhatHappened _reports;
	private readonly TheArrivals _arrivals;
	private readonly RecordsTheWarmUps _record;
	private readonly ILogger _logger;
	private readonly Dictionary<string, RoomDriving> _driving = new(StringComparer.Ordinal);

	private PresenceState _presence = PresenceState.NoEvidence;
	private HeatingMode? _modeLastPass;
	private HeatingMode? _modeReported;
	private DateTimeOffset? _modeInForceSince;
	private string? _presenceNotRecognised;
	private bool _reportedTheSensorsOut;
	private bool _reportedTheZone;
	private InForceRecord _inForce = InForceRecord.Empty;

	public DrivesTheRooms(
		ISettingsStore store,
		Thermostats thermostats,
		PlannerDefaults defaults,
		TheHouseholdClock household,
		string? presenceHelper,
		OutdoorChoice outdoor,
		ReportsWhatHappened reports,
		TheArrivals arrivals,
		RecordsTheWarmUps record,
		ILogger<DrivesTheRooms> logger)
	{
		_store = store ?? throw new ArgumentNullException(nameof(store));
		_thermostats = thermostats ?? throw new ArgumentNullException(nameof(thermostats));
		_defaults = defaults ?? throw new ArgumentNullException(nameof(defaults));
		_household = household ?? throw new ArgumentNullException(nameof(household));
		_presenceHelper = presenceHelper;
		_outdoor = outdoor ?? throw new ArgumentNullException(nameof(outdoor));
		_reports = reports ?? throw new ArgumentNullException(nameof(reports));
		_arrivals = arrivals ?? throw new ArgumentNullException(nameof(arrivals));
		_record = record ?? throw new ArgumentNullException(nameof(record));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <summary>What each room is being told to hold, which is what the settings page states beside a room's settings.</summary>
	public InForceRecord InForce => _inForce;

	public async Task<DrivingPass> RunAsync(IReadOnlyList<EntityState> states, DateTimeOffset now, CancellationToken token)
	{
		ArgumentNullException.ThrowIfNull(states);

		EntityState? dropdown = PresenceDropdown(states);

		// Before the document is read: mapping the dropdown's options writes one, and this pass then reads the
		// mapping it just made rather than reporting every option as unrecognised once.
		if (SetsUpThePresenceMap.FromTheOptionsItOffers(_store, dropdown, _logger))
			_presenceNotRecognised = null;

		// The settings page draws one row per option, and a value the words could not tell apart has no stored row
		// to draw. Without this the page has nothing to edit and the mapping can only be guessed at.
		_store.ReceiveThePresenceOptions(SetsUpThePresenceMap.OptionsOf(dropdown));

		HeatingDocument document = _store.Read();
		(HeatingMode mode, ModeChosenBy modeFrom, string? presenceUnknown) = ModeInForce(document, dropdown, now);

		if (presenceUnknown is { Length: > 0 } refused)
		{
			await _reports
				.ReportAsync(
					HeatingReport.About(WhatHappened.PresenceNotRecognised, now)
						with { Named = _presenceHelper, Reading = refused },
					token)
				.ConfigureAwait(false);
		}

		if (_modeReported != mode)
		{
			_modeReported = mode;

			await _reports
				.ReportAsync(HeatingReport.About(WhatHappened.ModeInForce, now) with { Named = mode.ToString() }, token)
				.ConfigureAwait(false);
		}

		await ReportTheHouseholdClockAsync(now, token).ConfigureAwait(false);

		SunTimes sun = SunTimesFrom(states);
		OutdoorReading outdoor = TheOutdoorTemperature.Read(states, _outdoor, now, _defaults);

		await ReportTheOutdoorSensorsAsync(outdoor, now, token).ConfigureAwait(false);

		// A slot stays silent under any other mode, which is what makes the day profile a mode like the others.
		EntryInForce? boundary = mode == HeatingMode.DayProfile
			? DayProfile.InForceAt(document.Profile, _household.Zone, sun, now)
			: null;

		Dictionary<string, ThermostatNow> reporting = new(StringComparer.Ordinal);

		foreach (EntityState state in states)
		{
			if (ThermostatNow.From(state, now) is { } thermostat)
				reporting[thermostat.RoomId] = thermostat;
		}

		// Read before the rooms are driven, so a room reached on this pass is planned against the same arrival as
		// every other. A reading is taken again on its own cadence and stands between.
		DateTimeOffset? arrival = await _arrivals.NextAsync(document, states, now, token).ConfigureAwait(false);

		List<RoomSlice> rooms = [];
		Dictionary<string, Stamped<double>> told = new(StringComparer.Ordinal);
		bool learnt = false;
		int driven = 0;
		int sent = 0;

		foreach (RoomSlice room in document.Rooms)
		{
			if (room.Thermostat is not { Length: > 0 } || !reporting.TryGetValue(room.Id, out ThermostatNow? thermostat))
			{
				rooms.Add(room);
				continue;
			}

			driven++;
			RoomOutcome outcome = await DriveAsync(room, thermostat, mode, boundary, document, sun, now, outdoor, arrival, told, token)
				.ConfigureAwait(false);
			rooms.Add(outcome.Room);
			learnt |= outcome.Learnt;
			sent += outcome.Sent;
		}

		if (learnt)
			_store.Receive(document with { Rooms = rooms });

		KeepWhatIsInForce(mode, modeFrom, told, now);

		_store.ReceiveWhatTheRoomsAreDoing(_inForce, ReadingsFrom(reporting, now));

		// A boundary only bites under the day profile, so under any other mode there is nothing to arm a timer
		// for. The pass a minute is what notices the mode changing back.
		DateTimeOffset? nextBoundary = mode == HeatingMode.DayProfile
			? DayProfile.NextBoundaryAfter(document.Profile, _household.Zone, sun, now)
			: null;

		// After the rooms, so a warm-up whose deadline fell during this pass is written down with what its room
		// reads now rather than with what it read a minute ago.
		int recorded = await _record
			.WriteDownWhatFinishedAsync(document, states, reporting, now, token)
			.ConfigureAwait(false);

		return new DrivingPass(mode, _presence, driven, sent, nextBoundary, outdoor, arrival, recorded);
	}

	private static Dictionary<string, RoomNow> ReadingsFrom(
		Dictionary<string, ThermostatNow> reporting,
		DateTimeOffset readAt)
	{
		Dictionary<string, RoomNow> readings = new(StringComparer.Ordinal);

		foreach (ThermostatNow thermostat in reporting.Values)
		{
			// A room publishing no target has no temperature line to show, and a zero here would read as one.
			if (thermostat.Target is not { } target)
				continue;

			readings[thermostat.RoomId] = new RoomNow(
				thermostat.RoomId,
				thermostat.RoomTemperature,
				target,
				thermostat.HeaterCommandedOn,
				readAt);
		}

		return readings;
	}

	/// <summary>Merges this pass's instructions into the record of what is in force, and says what it refused.</summary>
	private void KeepWhatIsInForce(
		HeatingMode mode,
		ModeChosenBy from,
		Dictionary<string, Stamped<double>> told,
		DateTimeOffset now)
	{
		_inForce = _inForce with
		{
			Mode = new Stamped<string>(mode.ToString(), Stamp.Certain(_modeInForceSince ?? now), ChangeOrigin.SettingsPage),
			ModeFrom = from
		};

		if (told.Count == 0)
			return;

		MergeOutcome merged = _inForce.Merge(told.Select(one => new ArrivingTemperature(one.Key, one.Value)));
		_inForce = merged.Record;

		foreach (RefusedChange refused in merged.Refused)
		{
			_logger.LogInformation(
				"{Room} keeps {Held} °C in force: {Arriving} °C was set earlier than that.",
				refused.RoomId, refused.TemperatureHeld, refused.ArrivingTemperature);
		}
	}

	/// <summary>A fresh connection to Home Assistant, after which whatever still holds is said again.</summary>
	/// <remarks>
	///     Home Assistant holds no cards after a core restart, and this side cannot see what it is still showing.
	///     Every card carries a stable id, so re-raising one replaces its own card rather than stacking a second.
	/// </remarks>
	public void TheConnectionCameBack()
	{
		_reportedTheSensorsOut = false;
		_arrivals.TheConnectionCameBack();
	}

	// Said once while it stays true, and again the next time it becomes true: a cabin whose outdoor sensors are
	// all dead would otherwise raise the same card every minute.
	/// <summary>Raises the card for a household zone that did not resolve, which nothing here can put right.</summary>
	private async Task ReportTheHouseholdClockAsync(DateTimeOffset now, CancellationToken token)
	{
		if (_household.Resolved || _reportedTheZone)
			return;

		// Latched on the card arriving, never on the attempt. A card refused for want of a connection would
		// otherwise leave a household whose every wall time is wrong with no card at all.
		_reportedTheZone = await _reports
			.ReportAsync(
				HeatingReport.About(WhatHappened.HouseholdZoneNotResolved, now) with { Named = _household.Named },
				token)
			.ConfigureAwait(false);
	}

	private async Task ReportTheOutdoorSensorsAsync(OutdoorReading outdoor, DateTimeOffset now, CancellationToken token)
	{
		bool allOut = outdoor.From is OutdoorFrom.Forecast or OutdoorFrom.Nothing;

		if (!allOut)
		{
			_reportedTheSensorsOut = false;

			return;
		}

		if (_reportedTheSensorsOut)
			return;

		// Latched on the card arriving, never on the attempt. A card refused for want of a connection would
		// otherwise leave a cabin whose sensors were already out with no card at all.
		_reportedTheSensorsOut = await _reports
			.ReportAsync(
				HeatingReport.About(WhatHappened.OutdoorSensorsAllFailed, now) with
				{
					Named = outdoor.From == OutdoorFrom.Forecast ? _outdoor.Forecast : null,
					Against = outdoor.Temperature
				},
				token)
			.ConfigureAwait(false);
	}

	private sealed record RoomOutcome(RoomSlice Room, bool Learnt, int Sent);

	private async Task<RoomOutcome> DriveAsync(
		RoomSlice room,
		ThermostatNow thermostat,
		HeatingMode mode,
		EntryInForce? boundary,
		HeatingDocument document,
		SunTimes sun,
		DateTimeOffset now,
		OutdoorReading outdoor,
		DateTimeOffset? arrival,
		Dictionary<string, Stamped<double>> told,
		CancellationToken token)
	{
		RoomDriving driving = DrivingOf(room.Id);
		Stamped<RoomInstruction>? asked = ModeTable.For(mode, !room.NoReadingAtAll, room.ModeTemperatures, room.ModeSwitches);

		if (room.NoReadingAtAll)
			return new RoomOutcome(room, false, await SwitchAsync(room, driving, asked, now, token).ConfigureAwait(false));

		int sent = 0;

		if (asked is { } instruction)
			sent += await HoldAsync(room, thermostat, driving, instruction, boundary, now, told, token).ConfigureAwait(false);

		double? outside = outdoor.From == OutdoorFrom.NothingChosen ? thermostat.Outdoor : outdoor.Temperature;
		RoomSlice after = await LearnAsync(room, thermostat, driving, now, outside, token).ConfigureAwait(false);

		if (mode == HeatingMode.DayProfile && document.DeadlineMeaningAvailable)
			sent += await WarmUpAsync(after, thermostat, driving, document, sun, now, outside, token).ConfigureAwait(false);

		// Whatever mode is in force: an arrival is people coming to a cabin that has been standing cold, and the
		// mode that will be in force when they are there is the one the room is warmed to.
		if (arrival is { } deadline)
			sent += await WarmUpForTheArrivalAsync(after, thermostat, driving, deadline, now, outside, token).ConfigureAwait(false);

		return new RoomOutcome(after, !ReferenceEquals(after, room), sent);
	}

	/// <summary>A room with no reading is switched on or off, and nothing else is done to it.</summary>
	private async Task<int> SwitchAsync(
		RoomSlice room,
		RoomDriving driving,
		Stamped<RoomInstruction>? asked,
		DateTimeOffset now,
		CancellationToken token)
	{
		if (asked is not { } instruction || driving.LastSwitched == instruction.Value.SwitchedOn)
			return 0;

		ActionOutcome outcome = await _thermostats
			.SwitchAsync(room.Thermostat!, instruction.Value.SwitchedOn, token)
			.ConfigureAwait(false);

		if (outcome != ActionOutcome.Called)
			return 0;

		driving.LastSwitched = instruction.Value.SwitchedOn;

		await _reports
			.ReportAsync(
				HeatingReport.About(WhatHappened.RoomSwitched, now, room.Id) with { SwitchedOn = instruction.Value.SwitchedOn },
				token)
			.ConfigureAwait(false);

		return 1;
	}

	/// <summary>One temperature per room, out of the mode, the boundary, a hand change and whatever the room is running.</summary>
	private async Task<int> HoldAsync(
		RoomSlice room,
		ThermostatNow thermostat,
		RoomDriving driving,
		Stamped<RoomInstruction> asked,
		EntryInForce? boundary,
		DateTimeOffset now,
		Dictionary<string, Stamped<double>> told,
		CancellationToken token)
	{
		// A room publishing no target holds nothing to weigh a candidate against, and takes on or off instead.
		if (thermostat.Target is not { } holding)
			return 0;

		NoteAHandChange(thermostat, holding, driving, now);

		RoomTargetCandidates candidates = new()
		{
			ModeTemperature = new Stamped<double>(asked.Value.Temperature, NewerOf(asked.Stamp), asked.Origin),
			ScheduleBoundary = BoundaryFor(room.Id, boundary),
			HandChange = driving.HandChange,

			// A warm-up and an unexpired hold are the integration's to run, so they are offered here only to keep
			// this pass from writing over one.
			TimedHold = thermostat.HoldUnexpiredAt(now)
				? new Stamped<double>(holding, Stamp.Certain(now), ChangeOrigin.Thermostat)
				: null,
			WarmUp = thermostat.WarmUpRunning
				? new Stamped<double>(holding, Stamp.Certain(now), ChangeOrigin.Thermostat)
				: null,
		};

		ResolvedTarget resolved = Precedence.Resolve(candidates);

		// A warm-up and an unexpired hold are the integration's, so what it is holding is what is in force.
		if (resolved.Source is TargetSource.WarmUp or TargetSource.TimedHold)
		{
			Offer(told, room.Id, resolved);

			return 0;
		}

		// A boundary naming the temperature the room is already holding replaces nothing.
		if (Math.Abs(resolved.Temperature - holding) <= SameTemperature)
		{
			driving.LastCommanded = resolved.Temperature;
			Offer(told, room.Id, resolved);

			return 0;
		}

		ActionOutcome outcome = await _thermostats
			.SetTemperatureAsync(room.Thermostat!, resolved.Temperature, token)
			.ConfigureAwait(false);

		if (outcome != ActionOutcome.Called)
			return 0;

		driving.LastCommanded = resolved.Temperature;
		driving.HandChange = null;

		Offer(told, room.Id, resolved);

		await _reports
			.ReportAsync(
				HeatingReport.About(WhatHappened.RoomHolds, now, room.Id) with
				{
					Temperature = resolved.Temperature,
					Named = resolved.Source.ToString()
				},
				token)
			.ConfigureAwait(false);

		return 1;
	}

	// Offered only where the number itself moved: the record's stamp contest would refuse the same temperature
	// arriving again as a change, and every steady minute would then read as a refusal.
	private void Offer(Dictionary<string, Stamped<double>> told, string roomId, ResolvedTarget resolved)
	{
		if (_inForce.Temperatures.TryGetValue(roomId, out Stamped<double> held) && held.Value == resolved.Temperature)
			return;

		told[roomId] = new Stamped<double>(resolved.Temperature, resolved.Stamp, ChangeOrigin.SettingsPage);
	}

	/// <summary>Starts the warm-up for a deadline entry, at the moment the planner says the heating has to begin.</summary>
	private async Task<int> WarmUpAsync(
		RoomSlice room,
		ThermostatNow thermostat,
		RoomDriving driving,
		HeatingDocument document,
		SunTimes sun,
		DateTimeOffset now,
		double? outside,
		CancellationToken token)
	{
		if (thermostat.RoomTemperature is not { } roomTemperature || thermostat.WarmUpRunning)
			return 0;

		int sent = 0;

		foreach (ProfileEntry entry in document.Profile)
		{
			if (entry.Meaning != BoundaryMeaning.WarmBy
				|| !entry.Temperatures.TryGetValue(room.Id, out Stamped<double> wanted)
				|| DayProfile.NextArrivalOf(entry, _household.Zone, sun, now) is not { } deadline)
				continue;

			if (driving.WarmUpsAsked.TryGetValue(entry.Id, out DateTimeOffset already) && already == deadline)
				continue;

			double rate = Estimate(room, outside, now).DegreesPerHour;

			if (WarmUp.DueNow(roomTemperature, wanted.Value, deadline, now, rate, _defaults) is not { } plan)
				continue;

			ActionOutcome outcome = await _thermostats
				.WarmRoomByAsync(room.Thermostat!, wanted.Value, deadline, token)
				.ConfigureAwait(false);

			if (outcome != ActionOutcome.Called)
				continue;

			driving.WarmUpsAsked[entry.Id] = deadline;
			_record.Asked(room.Id, wanted.Value, deadline, now);
			sent++;

			HeatingReport report = WarmUp.Report(room.Id, plan) is { } cannotReach
				? HeatingReport.About(WhatHappened.CannotWarmInTime, now, room.Id) with
				{
					Temperature = cannotReach.TemperatureWanted,
					Against = cannotReach.TemperatureItReaches,
					Deadline = deadline
				}
				: HeatingReport.About(WhatHappened.WarmUpStarted, now, room.Id) with
				{
					Temperature = wanted.Value,
					Deadline = deadline
				};

			await _reports.ReportAsync(report, token).ConfigureAwait(false);
		}

		return sent;
	}

	/// <summary>Starts the warm-up for a planned arrival, at the moment the planner says the heating has to begin.</summary>
	private async Task<int> WarmUpForTheArrivalAsync(
		RoomSlice room,
		ThermostatNow thermostat,
		RoomDriving driving,
		DateTimeOffset deadline,
		DateTimeOffset now,
		double? outside,
		CancellationToken token)
	{
		if (thermostat.RoomTemperature is not { } roomTemperature || thermostat.WarmUpRunning)
			return 0;

		// Asked once per arrival. A different arrival carries a different deadline, so the comparison tells the
		// two apart without anything having to name one.
		if (driving.ArrivalAsked == deadline)
			return 0;

		double wanted = room.TemperatureFor(HeatingMode.Home);
		double rate = Estimate(room, outside, now).DegreesPerHour;

		if (WarmUp.DueNow(roomTemperature, wanted, deadline, now, rate, _defaults) is not { } plan)
			return 0;

		ActionOutcome outcome = await _thermostats
			.WarmRoomByAsync(room.Thermostat!, wanted, deadline, token)
			.ConfigureAwait(false);

		if (outcome != ActionOutcome.Called)
			return 0;

		driving.ArrivalAsked = deadline;
		_record.Asked(room.Id, wanted, deadline, now);

		HeatingReport report = WarmUp.Report(room.Id, plan) is { } cannotReach
			? HeatingReport.About(WhatHappened.CannotWarmInTime, now, room.Id) with
			{
				Temperature = cannotReach.TemperatureWanted,
				Against = cannotReach.TemperatureItReaches,
				Deadline = deadline
			}
			: HeatingReport.About(WhatHappened.WarmUpStarted, now, room.Id) with
			{
				Temperature = wanted,
				Deadline = deadline
			};

		await _reports.ReportAsync(report, token).ConfigureAwait(false);

		return 1;
	}

	/// <summary>Watches the room, and writes back what it has learnt from it.</summary>
	private async Task<RoomSlice> LearnAsync(
		RoomSlice room,
		ThermostatNow thermostat,
		RoomDriving driving,
		DateTimeOffset now,
		double? outside,
		CancellationToken token)
	{
		// Nothing is learnt from a room publishing no target: both watchers measure against the temperature it
		// was asked to hold, and it was asked for none.
		if (thermostat.Target is not { } holding)
			return room;

		RoomObservation observation = new(
			now,
			thermostat.RoomTemperature,
			holding,
			thermostat.HeaterCommandedOn,
			thermostat.WarmUpRunning,
			outside,
			thermostat.PowerWatts,
			thermostat.HasAPowerMeter);

		RoomSlice after = room;
		RiseOutcome rise = driving.Rises.Observe(observation);

		if (rise.Measurement is { } measurement)
		{
			List<WarmingRateMeasurement> kept = [.. after.RateMeasurements, measurement];

			if (kept.Count > RisesKept)
				kept.RemoveRange(0, kept.Count - RisesKept);

			after = after with { RateMeasurements = kept };

			WarmingRateEstimate estimate = Estimate(after, outside, now);
			LearntNumber rate = after.Learnt.WarmingRate.Observe(estimate.DegreesPerHour, now, _defaults);

			after = after with { Learnt = after.Learnt with { WarmingRate = rate } };

			await _thermostats
				.SetWarmingRateAsync(room.Thermostat!, rate.Value, measurement.OutdoorTemperature, token)
				.ConfigureAwait(false);

			await _reports
				.ReportAsync(
					HeatingReport.About(WhatHappened.WarmingRateLearnt, now, room.Id) with
					{
						DegreesPerHour = rate.Value,
						Against = measurement.OutdoorTemperature
					},
					token)
				.ConfigureAwait(false);
		}
		else if (rise.Verdict is RiseVerdict.NoPowerDrawn or RiseVerdict.HeaterNeverRan)
		{
			await _reports
				.ReportAsync(HeatingReport.About(WhatHappened.RoseWithoutHeating, now, room.Id), token)
				.ConfigureAwait(false);
		}

		if (driving.Settling.Observe(observation, after.Learnt.OutdoorTerm.Value) is { } fit)
		{
			LearntNumber term = after.Learnt.OutdoorTerm.Observe(fit.PerDegree, now, _defaults);

			if (Math.Abs(term.Value - after.Learnt.OutdoorTerm.Value) > 1e-9)
			{
				await _thermostats
					.SetRegulationAsync(room.Thermostat!, outdoorShiftPerDegree: term.Value, token: token)
					.ConfigureAwait(false);

				await _reports
					.ReportAsync(
						HeatingReport.About(WhatHappened.OutdoorTermLearnt, now, room.Id) with
						{
							Temperature = fit.MeanShortfall,
							Against = fit.OutdoorTemperature
						},
						token)
					.ConfigureAwait(false);
			}

			after = after with { Learnt = after.Learnt with { OutdoorTerm = term } };
		}

		return after;
	}

	private WarmingRateEstimate Estimate(RoomSlice room, double? outside, DateTimeOffset now) =>
		WarmingRate.Estimate(
			room.RateMeasurements,
			room.Learnt.WarmingRate.StartingValue,
			outside ?? 0.0,
			now,
			_defaults);

	/// <summary>A target this pass did not ask for was set at the room's card, and it stands until something replaces it.</summary>
	private static void NoteAHandChange(ThermostatNow thermostat, double holding, RoomDriving driving, DateTimeOffset now)
	{
		// While a warm-up or a hold runs, the published target is theirs and says nothing about a person.
		if (thermostat.WarmUpRunning || thermostat.HoldUnexpiredAt(now))
			return;

		bool ours = driving.LastCommanded is { } commanded && Math.Abs(holding - commanded) <= SameTemperature;
		bool alreadyKnown = driving.HandChange is { } standing && Math.Abs(holding - standing.Value) <= SameTemperature;

		if (ours || alreadyKnown)
			return;

		driving.HandChange = new Stamped<double>(
			holding,
			Stamp.Certain(thermostat.TargetSetAt ?? now),
			ChangeOrigin.Thermostat);
	}

	private static Stamped<double>? BoundaryFor(string roomId, EntryInForce? boundary) =>
		boundary is not null && boundary.Entry.Temperatures.TryGetValue(roomId, out Stamped<double> slot)
			? new Stamped<double>(slot.Value, Stamp.Certain(boundary.Since), ChangeOrigin.SettingsPage)
			: null;

	// The mode coming into force is itself a change, so its temperature is stamped at the later of the two: when
	// somebody typed the number, and when the mode it belongs to took over. Without that, a hand change made after
	// the number was typed would survive the house switching to away.
	private Stamp NewerOf(Stamp typed) =>
		_modeInForceSince is { } since && since > typed.SetAt ? Stamp.Certain(since) : typed;

	/// <summary>The presence dropdown as Home Assistant last reported it, or <c>null</c> where none is named.</summary>
	private EntityState? PresenceDropdown(IReadOnlyList<EntityState> states) =>
		_presenceHelper is { Length: > 0 } helper
			? states.FirstOrDefault(state => string.Equals(state.EntityId, helper, StringComparison.Ordinal))
			: null;

	/// <summary>The mode in force, what chose it, and the dropdown value this pass could not read.</summary>
	private (HeatingMode Mode, ModeChosenBy From, string? PresenceNotRecognised) ModeInForce(
		HeatingDocument document,
		EntityState? dropdown,
		DateTimeOffset now)
	{
		string? notRecognised = null;

		// A value that has since been given a row is no longer the one refused. Leaving the latch on it would keep
		// the add-on silent if that row were later removed and the same value read again.
		if (_presenceNotRecognised is { } latched && document.Presence.StateFor(latched) is not null)
			_presenceNotRecognised = null;

		if (dropdown is not null)
		{
			// A dropdown reading unavailable holds the last value actually seen: falling through to everyday
			// un-pauses a whole house with nothing to put it back.
			if (Presence.Read(document.Presence, dropdown.State) is { } reading)
			{
				// Latched on the value, not on a flag: a second, different value a person chooses is worth a card
				// of its own, while the same one every minute is not.
				if (!reading.Recognised
					&& dropdown.State is { Length: > 0 } refused
					&& !string.Equals(refused, _presenceNotRecognised, StringComparison.Ordinal))
				{
					_presenceNotRecognised = refused;
					notRecognised = refused;
				}

				_presence = reading.State;
			}
		}

		HeatingMode mode = Presence.ModeFor(_presence);
		ModeChosenBy from = ModeChosenBy.Presence;

		// A mode somebody chose wins while it is unexpired, whether presence agrees or not, and lets go by itself
		// afterwards with nothing further from anybody. Boost and the day profile are reached this way and no other.
		if (document.ModeSetByHand?.InForceAt(now) is { } wanted)
		{
			mode = wanted;
			from = ModeChosenBy.Hand;
		}

		// Tracked on the mode actually in force rather than on presence alone: a hand change on a room must not
		// outlive the mode it was made under, and a chosen mode letting go is that same change.
		if (_modeLastPass is { } previous && previous != mode)
			_modeInForceSince = now;

		_modeLastPass = mode;

		return (mode, from, notRecognised);
	}

	/// <summary>Today's sun times from Home Assistant's own sun entity, which is what a sun-anchored boundary needs.</summary>
	private SunTimes SunTimesFrom(IReadOnlyList<EntityState> states)
	{
		EntityState? sun = states.FirstOrDefault(state =>
			string.Equals(state.EntityId, WhatTheHeatingReads.Sun, StringComparison.Ordinal));

		if (sun?.Attributes is not { } attributes)
			return SunTimes.Unknown;

		return new SunTimes(LocalTimeOf(Attributes.Moment(attributes, "next_rising")), LocalTimeOf(Attributes.Moment(attributes, "next_setting")));
	}

	private TimeOnly? LocalTimeOf(DateTimeOffset? moment) =>
		moment is { } at ? TimeOnly.FromDateTime(_household.Wall(at).DateTime) : null;

	private RoomDriving DrivingOf(string roomId)
	{
		if (!_driving.TryGetValue(roomId, out RoomDriving? driving))
		{
			driving = new RoomDriving(_defaults);
			_driving[roomId] = driving;
		}

		return driving;
	}

	/// <summary>What this process remembers about one room between passes. A restart costs one re-assertion.</summary>
	private sealed class RoomDriving
	{
		public RoomDriving(PlannerDefaults defaults)
		{
			Rises = new WarmingRateWatcher(defaults);
			Settling = new HoldingTermWatcher(defaults);
		}

		public WarmingRateWatcher Rises { get; }

		public HoldingTermWatcher Settling { get; }

		public double? LastCommanded { get; set; }

		public bool? LastSwitched { get; set; }

		public Stamped<double>? HandChange { get; set; }

		public Dictionary<string, DateTimeOffset> WarmUpsAsked { get; } = new(StringComparer.Ordinal);

		/// <summary>The arrival this room's warm-up was last asked for, so the same one is not asked for twice.</summary>
		public DateTimeOffset? ArrivalAsked { get; set; }
	}
}
