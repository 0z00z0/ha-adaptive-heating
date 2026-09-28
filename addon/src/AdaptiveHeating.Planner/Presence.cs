namespace AdaptiveHeating.Planner;

/// <summary>The states of the dropdown the heating shares with the lighting engine.</summary>
/// <remarks>
///     Ordinals are pinned and no member may be renamed or removed. A stored mapping names a state by identifier
///     and the settings file carries the member's own name, so either change silently re-points every row holding
///     it.
/// </remarks>
public enum PresenceState
{
	/// <summary>No helper is named, or the evidence says nothing. The cabin reads as empty.</summary>
	NoEvidence = 0,
	Away = 1,
	Everyday = 2,
	Night = 3,
	Guest = 4,
	PlannedToArrive = 5,
	OnTheWay = 6,
	TemporarilyAway = 7,
}

/// <summary>What the dropdown read, and whether a stored row named its value.</summary>
public readonly record struct PresenceReading(PresenceState State, bool Recognised);

/// <summary>The states an option may stand for, and the resource key each label comes from.</summary>
public static class PresenceStates
{
	/// <summary>Every state a dropdown option can be given, in the order the settings page offers them.</summary>
	/// <remarks><see cref="PresenceState.NoEvidence"/> is left out: it says no helper answered, so no option means it.</remarks>
	public static IReadOnlyList<PresenceState> Mappable { get; } =
	[
		PresenceState.Everyday,
		PresenceState.Night,
		PresenceState.Guest,
		PresenceState.Away,
		PresenceState.TemporarilyAway,
		PresenceState.PlannedToArrive,
		PresenceState.OnTheWay,
	];

	/// <summary>The resource key holding this state's label. Three words at most, because it sits in a dropdown.</summary>
	public static string KeyOf(PresenceState state) => state switch
	{
		PresenceState.Away => "PresenceAway",
		PresenceState.Everyday => "PresenceEveryday",
		PresenceState.Night => "PresenceNight",
		PresenceState.Guest => "PresenceGuest",
		PresenceState.PlannedToArrive => "PresencePlanned",
		PresenceState.OnTheWay => "PresenceOnTheWay",
		PresenceState.TemporarilyAway => "PresenceTemporarilyAway",
		_ => "PresenceNoEvidence"
	};
}

public static class Presence
{
	/// <summary>True where the heating treats the cabin as empty. Unclear evidence leans this way.</summary>
	public static bool ReadsAsAnEmptyCabin(PresenceState state) => state switch
	{
		PresenceState.Away => true,
		PresenceState.PlannedToArrive => true,
		PresenceState.NoEvidence => true,
		_ => false,
	};

	/// <summary>The mode a presence state selects. No state selects boost, and none selects the day profile.</summary>
	/// <remarks>Temporarily away and on the way both hold comfort: re-warming a cold cabin costs more than
	/// holding a warm one, and an arrival that is near and certain does not wait for movement.</remarks>
	public static HeatingMode ModeFor(PresenceState state) => state switch
	{
		PresenceState.Night => HeatingMode.Night,
		PresenceState.Everyday => HeatingMode.Home,
		PresenceState.Guest => HeatingMode.Home,
		PresenceState.TemporarilyAway => HeatingMode.Home,
		PresenceState.OnTheWay => HeatingMode.Home,
		_ => HeatingMode.Away,
	};

	/// <summary>
	/// Reads one dropdown value against the stored mapping. An empty, unknown or unavailable value answers
	/// <c>null</c>, which holds the last value actually seen: falling through to everyday un-pauses a whole house
	/// with nothing to put it back.
	/// </summary>
	/// <remarks>
	///     A lookup and nothing else. No word is matched here, so what a value means is what the row for it says,
	///     and renaming the option in Home Assistant costs that row's text and not the mode.
	/// </remarks>
	public static PresenceReading? Read(PresenceMap map, string? value)
	{
		ArgumentNullException.ThrowIfNull(map);

		if (value is not { Length: > 0 } text || Unusable(text))
			return null;

		// A value no row names is treated as everyday, and the rooms keep following the clock. That is the
		// expensive lean, taken so a cabin with people in it cannot go cold, and it is reported rather than silent.
		return map.StateFor(text) is { } state
			? new PresenceReading(state, true)
			: new PresenceReading(PresenceState.Everyday, false);
	}

	private static bool Unusable(string text) =>
		string.Equals(text, "unknown", StringComparison.OrdinalIgnoreCase)
		|| string.Equals(text, "unavailable", StringComparison.OrdinalIgnoreCase);
}
