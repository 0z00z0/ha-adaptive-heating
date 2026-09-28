namespace AdaptiveHeating.Planner;

/// <summary>The day's sun times, supplied by the caller so the placement stays pure.</summary>
/// <param name="Sunrise">Local time of sunrise, or <c>null</c> when unknown (polar night, sun entity missing).</param>
/// <param name="Sunset">Local time of sunset, or <c>null</c> when unknown.</param>
public sealed record SunTimes(TimeOnly? Sunrise, TimeOnly? Sunset)
{
	/// <summary>Sun times that resolve nothing. A sun-anchored boundary is left out when this is all that is known.</summary>
	public static readonly SunTimes Unknown = new(null, null);
}

/// <summary>One boundary placed on the clock, with the entry it belongs to.</summary>
public readonly record struct PlacedBoundary(TimeOnly Start, ProfileEntry Entry);

/// <summary>The entry the clock has in force, and the moment its boundary arrived.</summary>
/// <remarks>The arrival is what the entry's temperature is stamped with, so a boundary replaces a hand change made
/// before it and stands aside for one made after it.</remarks>
public sealed record EntryInForce(ProfileEntry Entry, DateTimeOffset Since);

/// <summary>
/// The day's profile against the clock: which entry is in force, and when the next boundary falls.
/// </summary>
/// <remarks>
///     The placement, the wrap to yesterday's last entry, the next-boundary walk and the spring-forward rule are
///     taken from the lighting engine's <c>CircadianCalculator</c> and its <c>PeriodStart</c>, read on 2026-09-24.
///     The two copies drift, and a fault found in either is carried across by hand.
/// </remarks>
public static class DayProfile
{
	/// <summary>This entry's time of day, or <c>null</c> where a sun-anchored one cannot be placed.</summary>
	public static TimeOnly? Resolve(ProfileEntry entry, SunTimes sun)
	{
		ArgumentNullException.ThrowIfNull(entry);
		ArgumentNullException.ThrowIfNull(sun);

		if (entry.Anchor == BoundaryAnchor.ClockTime)
			return TimeOnly.FromTimeSpan(Within24Hours(entry.At));

		TimeOnly? anchor = entry.Anchor == BoundaryAnchor.Sunrise ? sun.Sunrise : sun.Sunset;

		// A sun-anchored boundary the sun entity cannot place is dropped, never guessed at.
		return anchor?.Add(entry.At);
	}

	/// <summary>The entry in force at <paramref name="now"/>, wrapping to yesterday's last, or <c>null</c> where none can be placed.</summary>
	public static EntryInForce? InForceAt(
		IReadOnlyList<ProfileEntry> entries,
		TimeZoneInfo zone,
		SunTimes sun,
		DateTimeOffset now)
	{
		ArgumentNullException.ThrowIfNull(zone);

		List<PlacedBoundary> boundaries = Placed(entries, sun);
		if (boundaries.Count == 0)
			return null;

		TimeOnly timeOfDay = TimeOfDay(now, zone);
		DateOnly today = DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(now, zone).DateTime);
		int index = -1;

		for (int at = 0; at < boundaries.Count; at++)
		{
			if (boundaries[at].Start <= timeOfDay)
				index = at;
		}

		// Before the first boundary of the day, yesterday's last entry is the one still running.
		PlacedBoundary running = index < 0 ? boundaries[^1] : boundaries[index];
		DateOnly began = index < 0 ? today.AddDays(-1) : today;

		return new EntryInForce(running.Entry, InstantOf(began, running.Start, zone));
	}

	/// <summary>The instant the next boundary after <paramref name="now"/> falls on, wrapping to the next local day.</summary>
	public static DateTimeOffset? NextBoundaryAfter(
		IReadOnlyList<ProfileEntry> entries,
		TimeZoneInfo zone,
		SunTimes sun,
		DateTimeOffset now)
	{
		ArgumentNullException.ThrowIfNull(zone);

		List<PlacedBoundary> boundaries = Placed(entries, sun);
		if (boundaries.Count == 0)
			return null;

		TimeOnly timeOfDay = TimeOfDay(now, zone);
		DateOnly today = DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(now, zone).DateTime);

		foreach (PlacedBoundary boundary in boundaries)
		{
			if (boundary.Start > timeOfDay)
				return InstantOf(today, boundary.Start, zone);
		}

		return InstantOf(today.AddDays(1), boundaries[0].Start, zone);
	}

	/// <summary>The next instant this entry's own boundary falls on, which is the deadline a warm-up works back from.</summary>
	public static DateTimeOffset? NextArrivalOf(ProfileEntry entry, TimeZoneInfo zone, SunTimes sun, DateTimeOffset now)
	{
		ArgumentNullException.ThrowIfNull(zone);

		if (Resolve(entry, sun) is not { } start)
			return null;

		DateOnly today = DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(now, zone).DateTime);
		DateTimeOffset todays = InstantOf(today, start, zone);

		return todays > now ? todays : InstantOf(today.AddDays(1), start, zone);
	}

	/// <summary>A household wall clock on a household day, as the instant it happens at.</summary>
	// A wall clock the spring-forward gap swallows never happens, so the boundary arrives at the first minute that
	// does; an ambiguous autumn one takes the standard-time answer.
	public static DateTimeOffset InstantOf(DateOnly day, TimeOnly boundary, TimeZoneInfo zone)
	{
		ArgumentNullException.ThrowIfNull(zone);

		DateTime local = day.ToDateTime(boundary, DateTimeKind.Unspecified);

		while (zone.IsInvalidTime(local))
			local = local.AddMinutes(1);

		return new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(local, zone));
	}

	private static List<PlacedBoundary> Placed(IReadOnlyList<ProfileEntry> entries, SunTimes sun)
	{
		ArgumentNullException.ThrowIfNull(entries);

		List<PlacedBoundary> boundaries = new(entries.Count);

		foreach (ProfileEntry entry in entries)
		{
			if (Resolve(entry, sun) is { } start)
				boundaries.Add(new PlacedBoundary(start, entry));
		}

		boundaries.Sort((left, right) => left.Start.CompareTo(right.Start));

		return boundaries;
	}

	private static TimeOnly TimeOfDay(DateTimeOffset now, TimeZoneInfo zone) =>
		TimeOnly.FromDateTime(TimeZoneInfo.ConvertTime(now, zone).DateTime);

	private static TimeSpan Within24Hours(TimeSpan at) =>
		TimeSpan.FromTicks(((at.Ticks % TimeSpan.TicksPerDay) + TimeSpan.TicksPerDay) % TimeSpan.TicksPerDay);
}
