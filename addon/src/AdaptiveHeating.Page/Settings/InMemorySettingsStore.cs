using AdaptiveHeating.Planner;

namespace AdaptiveHeating.Page.Settings;

/// <summary>
/// Holds the settings for as long as the process runs, and is what every rule about them is written in. The
/// add-on wraps it in a file and in the calls to the thermostats; the render host uses it on its own.
/// </summary>
/// <remarks>The stamp rule lives here rather than in the page: an arriving number whose stamp is older than
/// the one held is refused and the refusal says so, exactly as a thermostat refuses one.</remarks>
public sealed class InMemorySettingsStore : ISettingsStore
{
	private readonly Lock _gate = new();

	private HeatingDocument _document;

	public InMemorySettingsStore(HeatingDocument document) =>
		_document = document ?? throw new ArgumentNullException(nameof(document));

	/// <inheritdoc/>
	public event Action? Changed;

	/// <inheritdoc/>
	public HeatingDocument Read()
	{
		lock (_gate)
			return _document;
	}

	/// <inheritdoc/>
	public void Receive(HeatingDocument document)
	{
		ArgumentNullException.ThrowIfNull(document);

		lock (_gate)
			_document = document;

		Changed?.Invoke();
	}

	/// <inheritdoc/>
	public void ReceiveWhatTheRoomsAreDoing(InForceRecord inForce, IReadOnlyDictionary<string, RoomNow> now)
	{
		ArgumentNullException.ThrowIfNull(inForce);
		ArgumentNullException.ThrowIfNull(now);

		lock (_gate)
			_document = _document with { InForce = inForce, Now = now };

		Changed?.Invoke();
	}

	/// <inheritdoc/>
	public void ReceiveThePresenceOptions(IReadOnlyList<string> options)
	{
		ArgumentNullException.ThrowIfNull(options);

		lock (_gate)
		{
			// Compared before it is stored: this arrives on every pass over the rooms, and raising the change would
			// otherwise redraw every open page once a minute.
			if (_document.PresenceOptionsOffered.SequenceEqual(options, StringComparer.Ordinal))
				return;

			_document = _document with { PresenceOptionsOffered = [.. options] };
		}

		Changed?.Invoke();
	}

	/// <inheritdoc/>
	public void ReceiveTheCalendarsOffered(IReadOnlyList<CalendarOnOffer> calendars)
	{
		ArgumentNullException.ThrowIfNull(calendars);

		lock (_gate)
		{
			// Compared before it is stored, exactly as the dropdown's options are: this arrives on every pass and
			// raising the change would redraw every open page once a minute.
			if (_document.CalendarsOffered.SequenceEqual(calendars))
				return;

			_document = _document with { CalendarsOffered = [.. calendars] };
		}

		Changed?.Invoke();
	}

	/// <inheritdoc/>
	public SaveOutcome SaveCalendars(string? arrivals, string? record)
	{
		lock (_gate)
		{
			_document = _document with
			{
				ArrivalCalendar = Named(arrivals),
				RecordCalendar = Named(record)
			};
		}

		Changed?.Invoke();

		return SaveOutcome.Ok;
	}

	/// <inheritdoc/>
	public SaveOutcome SetModeByHand(HeatingMode mode, TimeSpan lasts, Stamp stamp) =>
		Chosen(ModeByHand.Of(mode, lasts, stamp));

	/// <inheritdoc/>
	public SaveOutcome FollowPresenceAgain() => Chosen(null);

	/// <inheritdoc/>
	public SaveOutcome SaveModeTemperatures(string roomId, IReadOnlyDictionary<HeatingMode, double> temperatures, Stamp stamp)
	{
		ArgumentNullException.ThrowIfNull(temperatures);

		return Change(roomId, room =>
		{
			Dictionary<HeatingMode, Stamped<double>> held = new(room.ModeTemperatures);

			foreach ((HeatingMode mode, double wanted) in temperatures)
			{
				Stamped<double> arriving = new(wanted, stamp, ChangeOrigin.SettingsPage);
				bool isHeld = held.TryGetValue(mode, out Stamped<double> already);

				// An unchanged number is not a change, so it neither carries a new stamp nor can be refused.
				if (isHeld && already.Value == wanted)
					continue;

				if (isHeld && !already.IsReplacedBy(arriving))
					return (room, SaveOutcome.Refused(RefusedForAnOlderStamp));

				held[mode] = arriving;
			}

			return (room with { ModeTemperatures = held }, SaveOutcome.Ok);
		});
	}

	/// <inheritdoc/>
	public SaveOutcome SaveSensorSettings(string roomId, RoomSensorSettings settings)
	{
		ArgumentNullException.ThrowIfNull(settings);

		// A room whose own reading is borrowed cannot lend, so a lender that starts borrowing is refused here
		// rather than leaving every borrowing room to discover it.
		if (settings.BorrowsFrom is { Length: > 0 } lender)
		{
			HeatingDocument document = Read();

			if (string.Equals(lender, roomId, StringComparison.Ordinal))
				return SaveOutcome.Refused("A room cannot borrow from itself.");

			if (document.Rooms.FirstOrDefault(room => room.Id == lender) is { } lending && lending.Borrows)
				return SaveOutcome.Refused("That room borrows its own reading.");
		}

		return Change(roomId, room => (room with { Sensors = settings }, SaveOutcome.Ok));
	}

	/// <inheritdoc/>
	public SaveOutcome SaveProfileEntry(ProfileEntry entry, Stamp stamp)
	{
		ArgumentNullException.ThrowIfNull(entry);

		lock (_gate)
		{
			int at = IndexOfEntry(entry.Id);

			if (at < 0)
				return SaveOutcome.Refused("That period is no longer in the profile.");

			Dictionary<string, Stamped<double>> held = new(_document.Profile[at].Temperatures);

			foreach ((string roomId, Stamped<double> arriving) in entry.Temperatures)
				held[roomId] = new Stamped<double>(arriving.Value, stamp, ChangeOrigin.SettingsPage);

			List<ProfileEntry> profile = [.. _document.Profile];
			profile[at] = entry with { Temperatures = held };

			_document = _document with { Profile = profile };
		}

		Changed?.Invoke();

		return SaveOutcome.Ok;
	}

	/// <inheritdoc/>
	public SaveOutcome ResetLearnt(string roomId, LearntKind kind) =>
		Change(roomId, room => (room with { Learnt = Replace(room.Learnt, kind, Reset) }, SaveOutcome.Ok));

	/// <inheritdoc/>
	public SaveOutcome SetLearntByHand(string roomId, LearntKind kind, double? value) =>
		Change(roomId, room =>
			(room with { Learnt = Replace(room.Learnt, kind, held => held with { ValueSetByAPerson = value }) }, SaveOutcome.Ok));

	/// <inheritdoc/>
	public SaveOutcome SavePresenceMap(PresenceMap map)
	{
		ArgumentNullException.ThrowIfNull(map);

		// Two options meaning one state is legitimate; two rows for one option text is not, because only the first
		// is ever read and the second would sit on the page doing nothing.
		if (FirstRepeatedOption(map) is { Length: > 0 } repeated)
			return SaveOutcome.Refused($"Two rows name the option '{repeated}'.");

		lock (_gate)
			_document = _document with { Presence = PresenceMap.Of(map.Options ?? []) };

		Changed?.Invoke();

		return SaveOutcome.Ok;
	}

	private const string RefusedForAnOlderStamp = "Changed elsewhere since this page loaded.";

	// No stamp rule over this one, unlike every number a thermostat also writes: one control on one screen, and
	// nothing but a person ever writes it, so the last save is the answer.
	private SaveOutcome Chosen(ModeByHand? chosen)
	{
		lock (_gate)
			_document = _document with { ModeSetByHand = chosen };

		Changed?.Invoke();

		return SaveOutcome.Ok;
	}

	// A blank choice and no choice are the same thing, so the field never holds whitespace a comparison would miss.
	private static string? Named(string? entityId) =>
		entityId?.Trim() is { Length: > 0 } named ? named : null;

	private static string? FirstRepeatedOption(PresenceMap map)
	{
		HashSet<string> seen = new(StringComparer.OrdinalIgnoreCase);

		foreach (PresenceOption option in map.Options ?? [])
		{
			if (option.Value?.Trim() is { Length: > 0 } text && !seen.Add(text))
				return text;
		}

		return null;
	}

	// The measurements go with the reset, so clearing a lock afterwards hands back the starting value rather
	// than a number fitted to a room that has since been rebuilt.
	private static LearntNumber Reset(LearntNumber held) =>
		held with { SystemValue = held.StartingValue, MeasurementCount = 0, AgreementsSoFar = 0, LastChangedAt = null };

	private static RoomLearntNumbers Replace(RoomLearntNumbers held, LearntKind kind, Func<LearntNumber, LearntNumber> change) =>
		kind switch
		{
			LearntKind.WarmingRate => held with { WarmingRate = change(held.WarmingRate) },
			LearntKind.OutdoorTerm => held with { OutdoorTerm = change(held.OutdoorTerm) },
			_ => held with { Band = change(held.Band) }
		};

	private int IndexOfEntry(string id)
	{
		for (int index = 0; index < _document.Profile.Count; index++)
		{
			if (string.Equals(_document.Profile[index].Id, id, StringComparison.Ordinal))
				return index;
		}

		return -1;
	}

	private SaveOutcome Change(string roomId, Func<RoomSlice, (RoomSlice Room, SaveOutcome Outcome)> change)
	{
		SaveOutcome outcome;

		lock (_gate)
		{
			int at = -1;

			for (int index = 0; index < _document.Rooms.Count; index++)
			{
				if (string.Equals(_document.Rooms[index].Id, roomId, StringComparison.Ordinal))
				{
					at = index;
					break;
				}
			}

			if (at < 0)
				return SaveOutcome.Refused("That room is no longer set up.");

			(RoomSlice changed, outcome) = change(_document.Rooms[at]);

			if (!outcome.Written)
				return outcome;

			List<RoomSlice> rooms = [.. _document.Rooms];
			rooms[at] = changed;

			_document = _document with { Rooms = rooms };
		}

		Changed?.Invoke();

		return outcome;
	}
}
