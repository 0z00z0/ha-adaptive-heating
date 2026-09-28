using System.Text.Json.Serialization;

namespace AdaptiveHeating.Planner;

/// <summary>Where a number was last changed. A tie between two stamps resolves in favour of the settings page.</summary>
public enum ChangeOrigin
{
	SettingsPage,
	Thermostat,
}

/// <summary>The moment a person or an automation set a number, and whether the clock had been set from the network.</summary>
// A struct reading a file gets its parameterless constructor unless the real one is named, which would restore
// every stamp as the start of time.
[method: JsonConstructor]
public readonly record struct Stamp(DateTimeOffset SetAt, bool ClockWasUnset)
{
	public static Stamp Certain(DateTimeOffset setAt) => new(setAt, false);

	public static Stamp AgainstAnUnsetClock(DateTimeOffset setAt) => new(setAt, true);

	/// <summary>The moment the clock is set from the network, every marked stamp becomes that moment.</summary>
	public Stamp WhenTheClockIsSet(DateTimeOffset networkTime) =>
		ClockWasUnset ? Certain(networkTime) : this;
}

[method: JsonConstructor]
public readonly record struct Stamped<T>(T Value, Stamp Stamp, ChangeOrigin Origin)
{
	/// <summary>True where the arriving change replaces this one.</summary>
	public bool IsReplacedBy(Stamped<T> arriving)
	{
		// A change made during an outage never displaces one made with a good clock, whatever the two read.
		if (Stamp.ClockWasUnset != arriving.Stamp.ClockWasUnset)
		{
			return Stamp.ClockWasUnset;
		}

		if (arriving.Stamp.SetAt != Stamp.SetAt)
		{
			return arriving.Stamp.SetAt > Stamp.SetAt;
		}

		return Origin == ChangeOrigin.Thermostat && arriving.Origin == ChangeOrigin.SettingsPage;
	}

	public Stamped<T> WhenTheClockIsSet(DateTimeOffset networkTime) =>
		this with { Stamp = Stamp.WhenTheClockIsSet(networkTime) };
}
