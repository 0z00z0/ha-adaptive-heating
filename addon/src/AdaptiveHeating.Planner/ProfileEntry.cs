namespace AdaptiveHeating.Planner;

/// <summary>What a time in the day's profile means.</summary>
public enum BoundaryMeaning
{
	/// <summary>The time heating starts. The default on every new entry, because a stranger reads a time that way.</summary>
	Starts,

	/// <summary>The time the room must be at the temperature. Rests on the measured warming rate.</summary>
	WarmBy
}

/// <summary>Where a boundary's time comes from.</summary>
public enum BoundaryAnchor
{
	ClockTime,
	Sunrise,
	Sunset
}

/// <summary>One period in the day's profile. Its slots apply only while the day profile mode is in force.</summary>
/// <param name="Id">Stable across a save, so the page can edit one entry without renumbering the rest.</param>
/// <param name="Anchor">A clock time, or an offset from sunrise or sunset.</param>
/// <param name="At">The clock time, or the offset from the sun event.</param>
/// <param name="Meaning">Whether the time is when heating starts or when the room must be warm.</param>
/// <param name="Temperatures">One temperature per room, each carrying the moment it was set.</param>
public sealed record ProfileEntry(
	string Id,
	BoundaryAnchor Anchor,
	TimeSpan At,
	BoundaryMeaning Meaning,
	IReadOnlyDictionary<string, Stamped<double>> Temperatures)
{
	public double TemperatureFor(string roomId) =>
		Temperatures.TryGetValue(roomId, out Stamped<double> held) ? held.Value : 0;
}
