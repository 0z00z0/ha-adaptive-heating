using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.Page.Presentation;

/// <summary>Which part of the settings the page is showing.</summary>
public enum SettingsSection
{
	Modes,
	Profile,
	Rooms,
	Presence,
	Calendars
}

/// <summary>
/// What the settings page reads and what a click on it does. The page holds no rule of its own: every change
/// goes to the store, and what comes back is what the table draws.
/// </summary>
public sealed class SettingsPageModel : IDisposable
{
	private readonly ISettingsStore _store;
	private readonly IStampSource _stamps;

	private HeatingDocument _document;

	public SettingsPageModel(ISettingsStore store, IStampSource stamps)
	{
		ArgumentNullException.ThrowIfNull(store);
		ArgumentNullException.ThrowIfNull(stamps);

		_store = store;
		_stamps = stamps;
		_document = store.Read();
		_store.Changed += OnStoreChanged;
	}

	/// <summary>Raised when the table on screen no longer states what is held.</summary>
	public event Action? Changed;

	public HeatingDocument Document => _document;

	public SettingsSection Section { get; private set; } = SettingsSection.Modes;

	/// <summary>The room whose fold is open, or <c>null</c>. One at a time, so the page never scrolls past two.</summary>
	public string? OpenRoomId { get; private set; }

	/// <summary>The period whose fold is open, or <c>null</c>.</summary>
	public string? OpenEntryId { get; private set; }

	/// <summary>What the last save did. Empty until something has been saved.</summary>
	public SaveOutcome LastOutcome { get; private set; } = SaveOutcome.Ok;

	/// <summary>The room the last save was about, so a refusal is shown beside the room it refused.</summary>
	public string? LastSavedRoomId { get; private set; }

	/// <summary>True where the last save was refused, which is the only state that needs a red mark.</summary>
	public bool LastSaveWasRefused => !LastOutcome.Written;

	public bool IsActive(SettingsSection section) => Section == section;

	/// <summary>Opens a section, from the query on load or from the sub-navigation afterwards.</summary>
	public void Show(SettingsSection section)
	{
		if (Section == section)
			return;

		Section = section;
		Raise();
	}

	/// <summary>Reads the section a link asked for. An unknown value opens the mode table.</summary>
	public void Start(string? sectionQuery)
	{
		Section = sectionQuery?.ToLowerInvariant() switch
		{
			"profile" => SettingsSection.Profile,
			"rooms" => SettingsSection.Rooms,
			"presence" => SettingsSection.Presence,
			"calendars" => SettingsSection.Calendars,
			_ => SettingsSection.Modes
		};
	}

	public void ToggleRoom(string roomId, bool open)
	{
		OpenRoomId = open ? roomId : null;
		Raise();
	}

	public void ToggleEntry(string entryId, bool open)
	{
		OpenEntryId = open ? entryId : null;
		Raise();
	}

	/// <summary>Writes one room's mode temperatures. The rest of the document is not sent and cannot be overwritten.</summary>
	public void SaveModeTemperatures(string roomId, IReadOnlyDictionary<HeatingMode, double> temperatures) =>
		Record(roomId, _store.SaveModeTemperatures(roomId, temperatures, Now()));

	public void SaveSensorSettings(string roomId, RoomSensorSettings settings) =>
		Record(roomId, _store.SaveSensorSettings(roomId, settings));

	public void SaveProfileEntry(ProfileEntry entry) =>
		Record(null, _store.SaveProfileEntry(entry, Now()));

	public void ResetLearnt(string roomId, LearntKind kind) =>
		Record(roomId, _store.ResetLearnt(roomId, kind));

	public void SetLearntByHand(string roomId, LearntKind kind, double? value) =>
		Record(roomId, _store.SetLearntByHand(roomId, kind, value));

	/// <summary>Writes what each option of the presence dropdown means, as one table.</summary>
	public void SavePresenceMap(PresenceMap map) =>
		Record(null, _store.SavePresenceMap(map));

	/// <summary>Writes which calendar the arrivals are read from and which one the record is written to.</summary>
	public void SaveCalendars(string? arrivals, string? record) =>
		Record(null, _store.SaveCalendars(arrivals, record));

	/// <summary>Chooses the mode by hand for a number of hours, after which presence answers again unaided.</summary>
	public void SetModeByHand(HeatingMode mode, double hours) =>
		Record(null, _store.SetModeByHand(mode, TimeSpan.FromHours(hours), Now()));

	/// <summary>Drops a chosen mode, so presence answers from now on.</summary>
	public void FollowPresenceAgain() =>
		Record(null, _store.FollowPresenceAgain());

	/// <inheritdoc/>
	public void Dispose() => _store.Changed -= OnStoreChanged;

	// Whether the stamp is marked as made against an unset clock is the source's to decide, not the page's.
	private Stamp Now() => _stamps.Take();

	private void Record(string? roomId, SaveOutcome outcome)
	{
		LastOutcome = outcome;
		LastSavedRoomId = roomId;
		_document = _store.Read();
		Raise();
	}

	private void OnStoreChanged()
	{
		_document = _store.Read();
		Raise();
	}

	private void Raise() => Changed?.Invoke();
}
