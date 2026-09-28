using System.Threading.Channels;

using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>Turns a number saved on the settings page into the action that writes it down in the room's thermostat.</summary>
/// <remarks>
///     A save must not wait on Home Assistant, so what to send is queued and a pump sends it. The queue keeps
///     the order the saves were made in, which is what stops two changes to one number arriving the wrong way round.
/// </remarks>
internal sealed class TellsTheThermostats : ISettingsStore
{
	private readonly ISettingsStore _inner;
	private readonly Thermostats _thermostats;
	private readonly ILogger<TellsTheThermostats> _logger;
	private readonly Channel<Func<CancellationToken, Task<ActionOutcome>>> _queue = Channel.CreateUnbounded<Func<CancellationToken, Task<ActionOutcome>>>();

	public TellsTheThermostats(ISettingsStore inner, Thermostats thermostats, ILogger<TellsTheThermostats> logger)
	{
		_inner = inner ?? throw new ArgumentNullException(nameof(inner));
		_thermostats = thermostats ?? throw new ArgumentNullException(nameof(thermostats));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));

		_inner.Changed += () => Changed?.Invoke();
	}

	/// <inheritdoc/>
	public event Action? Changed;

	/// <inheritdoc/>
	public HeatingDocument Read() => _inner.Read();

	/// <inheritdoc/>
	public void Receive(HeatingDocument document) => _inner.Receive(document);

	/// <inheritdoc/>
	// Nothing is sent: the reading came from the rooms, so sending it back would tell them what they just said.
	public void ReceiveWhatTheRoomsAreDoing(InForceRecord inForce, IReadOnlyDictionary<string, RoomNow> now) =>
		_inner.ReceiveWhatTheRoomsAreDoing(inForce, now);

	/// <inheritdoc/>
	public SaveOutcome SaveModeTemperatures(string roomId, IReadOnlyDictionary<HeatingMode, double> temperatures, Stamp stamp) =>
		_inner.SaveModeTemperatures(roomId, temperatures, stamp);

	/// <inheritdoc/>
	public SaveOutcome SaveSensorSettings(string roomId, RoomSensorSettings settings) =>
		_inner.SaveSensorSettings(roomId, settings);

	/// <inheritdoc/>
	public SaveOutcome SaveProfileEntry(ProfileEntry entry, Stamp stamp) =>
		_inner.SaveProfileEntry(entry, stamp);

	/// <inheritdoc/>
	public SaveOutcome ResetLearnt(string roomId, LearntKind kind) =>
		Tell(roomId, kind, _inner.ResetLearnt(roomId, kind));

	/// <inheritdoc/>
	public SaveOutcome SetLearntByHand(string roomId, LearntKind kind, double? value) =>
		Tell(roomId, kind, _inner.SetLearntByHand(roomId, kind, value));

	/// <inheritdoc/>
	// Nothing is sent: what an option of the dropdown means reaches no thermostat.
	public SaveOutcome SavePresenceMap(PresenceMap map) => _inner.SavePresenceMap(map);

	/// <inheritdoc/>
	public void ReceiveThePresenceOptions(IReadOnlyList<string> options) => _inner.ReceiveThePresenceOptions(options);

	/// <inheritdoc/>
	public void ReceiveTheCalendarsOffered(IReadOnlyList<CalendarOnOffer> calendars) =>
		_inner.ReceiveTheCalendarsOffered(calendars);

	/// <inheritdoc/>
	// Nothing is sent: which calendar is read and which is written reaches no thermostat.
	public SaveOutcome SaveCalendars(string? arrivals, string? record) => _inner.SaveCalendars(arrivals, record);

	/// <inheritdoc/>
	// Nothing is sent: the mode resolves to a temperature on the next pass, and that is what reaches a room.
	public SaveOutcome SetModeByHand(HeatingMode mode, TimeSpan lasts, Stamp stamp) =>
		_inner.SetModeByHand(mode, lasts, stamp);

	/// <inheritdoc/>
	public SaveOutcome FollowPresenceAgain() => _inner.FollowPresenceAgain();

	/// <summary>Sends what is queued, in order, until the token is cancelled.</summary>
	public async Task PumpAsync(CancellationToken token)
	{
		await foreach (Func<CancellationToken, Task<ActionOutcome>> call in _queue.Reader.ReadAllAsync(token).ConfigureAwait(false))
			await call(token).ConfigureAwait(false);
	}

	/// <summary>Sends whatever is queued now and stops. What the sends did, in the order they were made.</summary>
	public async Task<IReadOnlyList<ActionOutcome>> SendWhatIsWaitingAsync(CancellationToken token)
	{
		List<ActionOutcome> sent = [];

		while (_queue.Reader.TryRead(out Func<CancellationToken, Task<ActionOutcome>>? call))
			sent.Add(await call(token).ConfigureAwait(false));

		return sent;
	}

	private SaveOutcome Tell(string roomId, LearntKind kind, SaveOutcome outcome)
	{
		if (!outcome.Written)
			return outcome;

		if (_inner.Read().Rooms.FirstOrDefault(room => room.Id == roomId) is not { Thermostat: { Length: > 0 } thermostat } room)
		{
			// A room the integration has not reported has no thermostat to write to. The number is held and
			// goes out when the room is found.
			_logger.LogDebug("No thermostat is known for {Room}, so {Number} was saved and not sent.", roomId, kind);

			return outcome;
		}

		_queue.Writer.TryWrite(kind switch
		{
			LearntKind.WarmingRate => token =>
				_thermostats.SetWarmingRateAsync(thermostat, room.Learnt.WarmingRate.Value, measuredAtOutdoor: null, token),
			LearntKind.OutdoorTerm => token =>
				_thermostats.SetRegulationAsync(thermostat, outdoorShiftPerDegree: room.Learnt.OutdoorTerm.Value, token: token),
			_ => token =>
				_thermostats.SetRegulationAsync(thermostat, band: room.Learnt.Band.Value, token: token)
		});

		return outcome;
	}
}
