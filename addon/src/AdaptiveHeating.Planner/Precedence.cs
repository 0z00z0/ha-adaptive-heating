namespace AdaptiveHeating.Planner;

/// <summary>What chose the temperature a room is holding.</summary>
public enum TargetSource
{
	ModeTemperature,
	ScheduleBoundary,
	HandChange,
	TimedHold,
	WarmUp,
}

/// <summary>
/// The temperatures offered for one room. A timed hold that has expired and a warm-up that is not
/// running are left out by the caller rather than carried here.
/// </summary>
public sealed record RoomTargetCandidates
{
	public required Stamped<double> ModeTemperature { get; init; }

	/// <summary>The boundary in force. It is absent while a mode other than the ordinary one is in force.</summary>
	public Stamped<double>? ScheduleBoundary { get; init; }

	public Stamped<double>? HandChange { get; init; }

	public Stamped<double>? TimedHold { get; init; }

	public Stamped<double>? WarmUp { get; init; }
}

public sealed record ResolvedTarget(double Temperature, TargetSource Source, Stamp Stamp);

/// <summary>
/// One temperature per room. A running warm-up wins outright and an unexpired hold comes next; below
/// those three the most recently set of the mode temperature, the boundary and a hand change wins.
/// </summary>
public static class Precedence
{
	public static ResolvedTarget Resolve(RoomTargetCandidates candidates)
	{
		ArgumentNullException.ThrowIfNull(candidates);

		if (candidates.WarmUp is Stamped<double> warmUp)
		{
			return new ResolvedTarget(warmUp.Value, TargetSource.WarmUp, warmUp.Stamp);
		}

		if (candidates.TimedHold is Stamped<double> hold)
		{
			return new ResolvedTarget(hold.Value, TargetSource.TimedHold, hold.Stamp);
		}

		Stamped<double> standing = candidates.ModeTemperature;
		TargetSource source = TargetSource.ModeTemperature;

		if (candidates.ScheduleBoundary is Stamped<double> boundary && standing.IsReplacedBy(boundary))
		{
			standing = boundary;
			source = TargetSource.ScheduleBoundary;
		}

		if (candidates.HandChange is Stamped<double> byHand && standing.IsReplacedBy(byHand))
		{
			standing = byHand;
			source = TargetSource.HandChange;
		}

		return new ResolvedTarget(standing.Value, source, standing.Stamp);
	}
}
