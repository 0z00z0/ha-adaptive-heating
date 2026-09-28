namespace AdaptiveHeating.Planner;

/// <summary>What chose the mode every room is running.</summary>
public enum ModeChosenBy
{
	Presence,

	/// <summary>Somebody chose it on the settings page, and it lets go by itself.</summary>
	Hand
}

/// <summary>
/// The mode somebody chose and the moment it lets go. Presence takes over again at that moment with nothing
/// further from anybody.
/// </summary>
/// <remarks>
///     The same shape as a timed hold on one room: an end moment, and a question asking whether it is still
///     unexpired. A mode that held until it was cleared would heat a cabin nobody is in until the next visit.
/// </remarks>
public sealed record ModeByHand
{
	/// <summary>What the field starts on where nothing is typed: an evening and a night.</summary>
	// Short on purpose. A stay of several days is typed in; a mode forgotten on the way out costs half a day.
	public static TimeSpan Standard { get; } = TimeSpan.FromHours(12);

	public static TimeSpan Shortest { get; } = TimeSpan.FromHours(1);

	/// <summary>A week, which is longer than any stay the cabin sees and short enough to be an end.</summary>
	public static TimeSpan Longest { get; } = TimeSpan.FromHours(168);

	/// <summary>The mode itself, named as the member's own name and carrying the moment it was chosen.</summary>
	// A name and not the enum: the settings file carries this, and a value no build knows must read as absent
	// rather than as the first member.
	public required Stamped<string> Mode { get; init; }

	public required DateTimeOffset EndsAt { get; init; }

	/// <summary>The mode this stands for, or <c>null</c> where the stored name belongs to no mode.</summary>
	public HeatingMode? Wanted =>
		Enum.TryParse(Mode.Value, out HeatingMode mode) && Enum.IsDefined(mode) ? mode : null;

	public bool UnexpiredAt(DateTimeOffset now) => EndsAt > now;

	/// <summary>The mode in force where this one is still unexpired, or <c>null</c> where presence answers.</summary>
	public HeatingMode? InForceAt(DateTimeOffset now) => UnexpiredAt(now) ? Wanted : null;

	/// <summary>A choice of <paramref name="mode"/> lasting <paramref name="lasts"/>, clamped to the bounds above.</summary>
	public static ModeByHand Of(HeatingMode mode, TimeSpan lasts, Stamp stamp)
	{
		TimeSpan held = lasts < Shortest ? Shortest : lasts > Longest ? Longest : lasts;

		return new ModeByHand
		{
			Mode = new Stamped<string>(mode.ToString(), stamp, ChangeOrigin.SettingsPage),
			EndsAt = stamp.SetAt + held
		};
	}

	/// <summary>Rewrites a choice made against an unset clock, end moment included, to the moment the clock was set.</summary>
	// The end moment was worked out from a clock reading the start of time, so it has already passed. Moving it
	// with the stamp is what keeps a mode chosen during an outage running for the hours it was given.
	public ModeByHand WhenTheClockIsSet(DateTimeOffset networkTime) =>
		Mode.Stamp.ClockWasUnset
			? this with { Mode = Mode.WhenTheClockIsSet(networkTime), EndsAt = networkTime + (EndsAt - Mode.Stamp.SetAt) }
			: this;
}
