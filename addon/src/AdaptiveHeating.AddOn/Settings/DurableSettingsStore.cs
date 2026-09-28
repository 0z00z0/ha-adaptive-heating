using AdaptiveHeating.AddOn.Persistence;
using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Settings;

/// <summary>The settings page's store with a file under it, so what a person typed is still there after a restart.</summary>
/// <remarks>
///     Every rule about the settings stays in the store it wraps. This one restores at start and writes after
///     each accepted save, and nothing else.
/// </remarks>
internal sealed class DurableSettingsStore : ISettingsStore
{
	private readonly InMemorySettingsStore _held;
	private readonly StateStore<StoredSettings> _file;
	private readonly TimeProvider _clock;

	private DurableSettingsStore(InMemorySettingsStore held, StateStore<StoredSettings> file, TimeProvider clock)
	{
		_held = held;
		_file = file;
		_clock = clock;

		_held.Changed += () => Changed?.Invoke();
	}

	/// <inheritdoc/>
	public event Action? Changed;

	/// <summary>The declaration the registry opens this store's file from.</summary>
	public static StateStoreDeclaration<StoredSettings> Declaration { get; } = new(
		Name: "the settings",
		NameSuffix: "-settings.json",
		Version: StoredSettings.CurrentVersion,
		// A person has just pressed save and a restart is about to need the number, so it is not worth coalescing.
		WritePolicy: StateWritePolicy.Immediate,
		VersionOf: stored => stored.Version,
		SavedAtOf: stored => stored.SavedAt);

	/// <summary>Where the file sits, which is what the start-up report names.</summary>
	public string FilePath => _file.FilePath;

	/// <summary>Opens the file and answers a store holding whatever it restored, or <paramref name="whenThereIsNoFile"/>.</summary>
	public static DurableSettingsStore Open(
		StateStoreRegistry registry,
		TimeProvider clock,
		HeatingDocument whenThereIsNoFile,
		ILogger logger)
	{
		ArgumentNullException.ThrowIfNull(registry);
		ArgumentNullException.ThrowIfNull(clock);
		ArgumentNullException.ThrowIfNull(whenThereIsNoFile);

		StateStore<StoredSettings> file = registry.Open(Declaration, StoredSettings.SerializerOptions, logger);
		StoredSettings? restored = file.Restore(clock.GetUtcNow());

		HeatingDocument document = restored?.Settings is { } settings
			// The integration has said nothing yet whatever the file held, and the add-on's own version is this build's.
			? settings with { Versions = new HalfVersions(HalfVersions.AddOnVersion, null, Vocabulary.Version) }
			: whenThereIsNoFile;

		return new DurableSettingsStore(new InMemorySettingsStore(document), file, clock);
	}

	/// <inheritdoc/>
	public HeatingDocument Read() => _held.Read();

	/// <inheritdoc/>
	public void Receive(HeatingDocument document)
	{
		_held.Receive(document);
		Save();
	}

	/// <inheritdoc/>
	// Not written: a reading is read again within a minute of a restart, so writing one would cost a file write on
	// every pass over the rooms and buy nothing.
	public void ReceiveWhatTheRoomsAreDoing(InForceRecord inForce, IReadOnlyDictionary<string, RoomNow> now) =>
		_held.ReceiveWhatTheRoomsAreDoing(inForce, now);

	/// <inheritdoc/>
	// Not written either: the dropdown is read again within a minute of a restart, and a stored option list would
	// go stale against the helper it came from.
	public void ReceiveThePresenceOptions(IReadOnlyList<string> options) =>
		_held.ReceiveThePresenceOptions(options);

	/// <inheritdoc/>
	// Not written either: the house is read again within a minute of a restart, and a stored list of calendars
	// would go stale against Home Assistant.
	public void ReceiveTheCalendarsOffered(IReadOnlyList<CalendarOnOffer> calendars) =>
		_held.ReceiveTheCalendarsOffered(calendars);

	/// <inheritdoc/>
	public SaveOutcome SaveCalendars(string? arrivals, string? record) =>
		Written(_held.SaveCalendars(arrivals, record));

	/// <inheritdoc/>
	public SaveOutcome SetModeByHand(HeatingMode mode, TimeSpan lasts, Stamp stamp) =>
		Written(_held.SetModeByHand(mode, lasts, stamp));

	/// <inheritdoc/>
	public SaveOutcome FollowPresenceAgain() =>
		Written(_held.FollowPresenceAgain());

	/// <summary>Rewrites every stamp made against an unset clock to the moment the clock was set.</summary>
	public void WhenTheClockIsSet(DateTimeOffset networkTime) =>
		Receive(_held.Read().WhenTheClockIsSet(networkTime));

	/// <inheritdoc/>
	public SaveOutcome SaveModeTemperatures(string roomId, IReadOnlyDictionary<HeatingMode, double> temperatures, Stamp stamp) =>
		Written(_held.SaveModeTemperatures(roomId, temperatures, stamp));

	/// <inheritdoc/>
	public SaveOutcome SaveSensorSettings(string roomId, RoomSensorSettings settings) =>
		Written(_held.SaveSensorSettings(roomId, settings));

	/// <inheritdoc/>
	public SaveOutcome SaveProfileEntry(ProfileEntry entry, Stamp stamp) =>
		Written(_held.SaveProfileEntry(entry, stamp));

	/// <inheritdoc/>
	public SaveOutcome ResetLearnt(string roomId, LearntKind kind) =>
		Written(_held.ResetLearnt(roomId, kind));

	/// <inheritdoc/>
	public SaveOutcome SetLearntByHand(string roomId, LearntKind kind, double? value) =>
		Written(_held.SetLearntByHand(roomId, kind, value));

	/// <inheritdoc/>
	public SaveOutcome SavePresenceMap(PresenceMap map) =>
		Written(_held.SavePresenceMap(map));

	private SaveOutcome Written(SaveOutcome outcome)
	{
		if (outcome.Written)
			Save();

		return outcome;
	}

	private void Save() =>
		_file.Write(new StoredSettings(StoredSettings.CurrentVersion, _clock.GetUtcNow(), _held.Read()));
}
