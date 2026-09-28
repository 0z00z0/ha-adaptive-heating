using System.Text.Json.Serialization;

using AdaptiveHeating.Planner;

namespace AdaptiveHeating.Page.Settings;

/// <summary>Everything the settings page reads, as one snapshot.</summary>
/// <param name="Rooms">Every room set up in the integration.</param>
/// <param name="Profile">The day's periods, in the order the page draws them.</param>
/// <param name="WritesPresence">Whether this half writes the shared dropdown or follows it.</param>
/// <param name="SecondWriterSeen">Whether a presence change this half did not make arrived while it was the writer.</param>
/// <param name="DeadlineMeaningAvailable">
///     Whether an entry may be given the deadline meaning. Off to begin with, so the page offers no setting
///     whose effect rests on an estimate worth nothing yet.
/// </param>
/// <param name="Versions">What each half runs.</param>
public sealed record HeatingDocument(
	IReadOnlyList<RoomSlice> Rooms,
	IReadOnlyList<ProfileEntry> Profile,
	bool WritesPresence,
	bool SecondWriterSeen,
	bool DeadlineMeaningAvailable,
	HalfVersions Versions)
{
	/// <summary>The mode somebody chose and the moment it lets go, or <c>null</c> where presence answers alone.</summary>
	/// <remarks>No presence state selects boost or the day profile, so those two are reached only this way. An
	/// expired choice is left where it is: <see cref="ModeByHand.UnexpiredAt"/> is what decides.</remarks>
	public ModeByHand? ModeSetByHand { get; init; }

	/// <summary>The calendar the planned arrivals are read from, by entity id, or <c>null</c> where none is chosen.</summary>
	/// <remarks>Any calendar will do: reading one is the same whoever keeps it.</remarks>
	public string? ArrivalCalendar { get; init; }

	/// <summary>The calendar each finished warm-up is written to, by entity id, or <c>null</c> where none is chosen.</summary>
	/// <remarks>A local one and no other, so the record stays on the box it is about.</remarks>
	public string? RecordCalendar { get; init; }

	/// <summary>Every calendar Home Assistant reports now, which is what the two settings are chosen from.</summary>
	// A reading and not a setting: the house is read again within a minute of a restart, and a stored list would
	// go stale against Home Assistant.
	[JsonIgnore]
	public IReadOnlyList<CalendarOnOffer> CalendarsOffered { get; init; } = [];

	/// <summary>What each option of the presence dropdown means. Empty until the dropdown has been read once.</summary>
	/// <remarks>A settings file written before this existed restores as empty, which reads every value as
	/// unrecognised and reports each one rather than guessing.</remarks>
	public PresenceMap Presence { get; init; } = PresenceMap.Empty;

	/// <summary>The options the dropdown itself currently offers, so one no row names can still be mapped by hand.</summary>
	// A reading and not a setting: the dropdown is read again within a minute of a restart, and an option list
	// written to the settings file would go stale against the helper.
	[JsonIgnore]
	public IReadOnlyList<string> PresenceOptionsOffered { get; init; } = [];

	/// <summary>What each room is currently being told to hold, and the mode in force over the whole cabin.</summary>
	// Worked out afresh on every pass and mirroring temperatures the rooms already carry, so it is never written
	// to the settings file.
	[JsonIgnore]
	public InForceRecord InForce { get; init; } = InForceRecord.Empty;

	/// <summary>What each room's thermostat reads and holds now, by the id both halves name the room by.</summary>
	// A reading, not a setting: a restart reads it again within a minute.
	[JsonIgnore]
	public IReadOnlyDictionary<string, RoomNow> Now { get; init; } =
		new Dictionary<string, RoomNow>(StringComparer.Ordinal);

	/// <summary>What one room reads and holds now, or <c>null</c> where nothing has been heard about it.</summary>
	public RoomNow? NowFor(string roomId) => Now.GetValueOrDefault(roomId);

	/// <summary>The temperature one room is being told to hold, or <c>null</c> where none is in force.</summary>
	public Stamped<double>? ToldFor(string roomId) =>
		InForce.Temperatures.TryGetValue(roomId, out Stamped<double> told) ? told : null;

	// Worked out from the rooms above, so writing it to the settings file would store every room twice.
	[JsonIgnore]
	public IReadOnlyList<RoomSlice> SetByHand =>
		[.. Rooms.Where(room => room.StandsOffThePlan)];

	/// <summary>The away temperature is the frost protection, and this is the coldest one any room holds.</summary>
	[JsonIgnore]
	public double? LowestFrostTemperature =>
		Rooms.Count == 0 ? null : Rooms.Min(room => room.TemperatureFor(HeatingMode.Away));

	/// <summary>
	/// Rewrites every stamp written against an unset clock to the moment the clock was set, so a change made
	/// during an outage stands newer than anything before it and older than anything after.
	/// </summary>
	public HeatingDocument WhenTheClockIsSet(DateTimeOffset networkTime) =>
		this with
		{
			// The end moment was worked out from a clock reading the start of time, so it has already passed.
			ModeSetByHand = ModeSetByHand?.WhenTheClockIsSet(networkTime),
			Rooms = [.. Rooms.Select(room => room with { ModeTemperatures = Rewrite(room.ModeTemperatures, networkTime) })],
			Profile = [.. Profile.Select(entry => entry with { Temperatures = Rewrite(entry.Temperatures, networkTime) })]
		};

	/// <summary>What the add-on starts on before it has heard from the integration.</summary>
	/// <remarks>A room is set up in the integration, so an add-on that has not yet connected knows of none,
	/// and the page says so rather than showing an empty table as though it were a finished one.</remarks>
	public static HeatingDocument NothingHeardYet() =>
		new([], [], WritesPresence: false, SecondWriterSeen: false, DeadlineMeaningAvailable: false,
			new HalfVersions(HalfVersions.AddOnVersion, null, Planner.Vocabulary.Version));

	private static Dictionary<TKey, Stamped<double>> Rewrite<TKey>(
		IReadOnlyDictionary<TKey, Stamped<double>> held,
		DateTimeOffset networkTime)
		where TKey : notnull
	{
		Dictionary<TKey, Stamped<double>> rewritten = [];

		foreach (KeyValuePair<TKey, Stamped<double>> one in held)
			rewritten[one.Key] = one.Value.WhenTheClockIsSet(networkTime);

		return rewritten;
	}
}

/// <summary>What a save was allowed to do.</summary>
/// <param name="Written">Whether the slice reached the store.</param>
/// <param name="Message">Why not, where it did not. Empty otherwise.</param>
public readonly record struct SaveOutcome(bool Written, string Message)
{
	public static SaveOutcome Ok { get; } = new(true, "");

	public static SaveOutcome Refused(string message) => new(false, message);
}

/// <summary>Where the page reads and writes. One room's slice at a time, never the whole document.</summary>
/// <remarks>Nothing on the page knows which store it is talking to: one holds the settings for as long as the
/// process runs, and the add-on wraps that one in a file and in the calls to the thermostats.</remarks>
public interface ISettingsStore
{
	HeatingDocument Read();

	/// <summary>Raised when something other than this page changed a number, so the table states what is held.</summary>
	event Action? Changed;

	/// <summary>Takes a document from somewhere other than the page: a restart, the integration, or the clock being set.</summary>
	void Receive(HeatingDocument document);

	/// <summary>
	/// Takes what the rooms are doing: what each thermostat reads and holds, and what each is being told. Not a
	/// setting, so nothing is written to a file and nothing is sent to a room.
	/// </summary>
	void ReceiveWhatTheRoomsAreDoing(InForceRecord inForce, IReadOnlyDictionary<string, RoomNow> now);

	/// <summary>
	/// Takes the options the presence dropdown offers now, so the page can draw a row for one no stored row
	/// names. Not a setting, so nothing is written to a file.
	/// </summary>
	void ReceiveThePresenceOptions(IReadOnlyList<string> options);

	/// <summary>
	/// Takes the calendars Home Assistant reports now, so the page can offer them. Not a setting, so nothing is
	/// written to a file.
	/// </summary>
	void ReceiveTheCalendarsOffered(IReadOnlyList<CalendarOnOffer> calendars);

	/// <summary>Writes which calendar the arrivals are read from and which one the record is written to.</summary>
	/// <remarks>Both at once, because they sit on one screen behind one save. An empty value clears a setting.</remarks>
	SaveOutcome SaveCalendars(string? arrivals, string? record);

	/// <summary>Writes the mode somebody chose and how long it holds before presence takes over again.</summary>
	SaveOutcome SetModeByHand(HeatingMode mode, TimeSpan lasts, Stamp stamp);

	/// <summary>Drops the chosen mode, so presence answers from now on.</summary>
	SaveOutcome FollowPresenceAgain();

	SaveOutcome SaveModeTemperatures(string roomId, IReadOnlyDictionary<HeatingMode, double> temperatures, Stamp stamp);

	SaveOutcome SaveSensorSettings(string roomId, RoomSensorSettings settings);

	SaveOutcome SaveProfileEntry(ProfileEntry entry, Stamp stamp);

	/// <summary>Returns a learnt number to its safe starting value and drops the measurements behind it.</summary>
	SaveOutcome ResetLearnt(string roomId, LearntKind kind);

	/// <summary>A set value locks the number; a <c>null</c> value releases the lock and hands back the system's own.</summary>
	SaveOutcome SetLearntByHand(string roomId, LearntKind kind, double? value);

	/// <summary>Writes what each option of the presence dropdown means, which is the whole mapping at once.</summary>
	/// <remarks>The rows are one table on one screen and a state moved between two of them has to land as one
	/// change, so a row at a time would leave two options claiming the same state in between.</remarks>
	SaveOutcome SavePresenceMap(PresenceMap map);
}
