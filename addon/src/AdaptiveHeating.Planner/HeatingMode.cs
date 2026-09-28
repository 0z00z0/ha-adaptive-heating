namespace AdaptiveHeating.Planner;

/// <summary>
/// The five modes, each holding one temperature per room. A mode is a name; what it is worth in a room is the
/// number typed against it here.
/// </summary>
/// <remarks>The planner resolves a mode to a temperature before it calls the integration, so the integration
/// never learns what a mode is.</remarks>
public enum HeatingMode
{
	/// <summary>The frost protection. Nothing anywhere falls below it.</summary>
	Away,

	Night,

	Home,

	/// <summary>Set by a person and by nothing else. No presence state ever selects it.</summary>
	Boost,

	/// <summary>A mode like the others. Its slots apply only while it is in force.</summary>
	DayProfile
}

/// <summary>The five modes in the order the table draws them, and the resource key each label comes from.</summary>
public static class HeatingModes
{
	public static IReadOnlyList<HeatingMode> All { get; } =
		[HeatingMode.Away, HeatingMode.Night, HeatingMode.Home, HeatingMode.Boost, HeatingMode.DayProfile];

	/// <summary>The resource key holding this mode's label. Two words at most, because it heads a column.</summary>
	public static string KeyOf(HeatingMode mode) => mode switch
	{
		HeatingMode.Away => "ModeAway",
		HeatingMode.Night => "ModeNight",
		HeatingMode.Home => "ModeHome",
		HeatingMode.Boost => "ModeBoost",
		_ => "ModeDayProfile"
	};
}
