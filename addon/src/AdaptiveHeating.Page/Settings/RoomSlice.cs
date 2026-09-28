using System.Text.Json.Serialization;

using AdaptiveHeating.Planner;

namespace AdaptiveHeating.Page.Settings;

/// <summary>What a room's sensors are held to, every value settable per room.</summary>
/// <param name="FreshWindow">How recently a sensor must have reported to count.</param>
/// <param name="StuckWindow">How long a reading may sit at one value before it reads as stuck.</param>
/// <param name="Spread">How far a fresh reading may sit from the others in the same room.</param>
/// <param name="WindowDelay">The delay each way before an open window stops the room and a closed one resumes it.</param>
/// <param name="BorrowsFrom">The room this one takes its reading from, or <c>null</c> where it has sensors of its own.</param>
public sealed record RoomSensorSettings(
	TimeSpan FreshWindow,
	TimeSpan StuckWindow,
	double Spread,
	TimeSpan WindowDelay,
	string? BorrowsFrom)
{
	public static RoomSensorSettings Standard(PlannerDefaults defaults)
	{
		ArgumentNullException.ThrowIfNull(defaults);

		return new(defaults.SensorFreshness, defaults.StuckReading, defaults.SensorSpread, TimeSpan.FromMinutes(2), null);
	}
}

/// <summary>The three numbers the system works out for a room, each with its own reset and its own lock.</summary>
public sealed record RoomLearntNumbers(LearntNumber WarmingRate, LearntNumber OutdoorTerm, LearntNumber Band)
{
	public static RoomLearntNumbers Starting(PlannerDefaults defaults)
	{
		ArgumentNullException.ThrowIfNull(defaults);

		return new(
			LearntNumber.Starting(0.5, SafeDirection.Lower),
			LearntNumber.Starting(defaults.HoldingTermStartingPerDegree, SafeDirection.Higher),
			LearntNumber.Starting(defaults.BandStartingValue, SafeDirection.Lower, ceiling: defaults.BandCeiling));
	}
}

/// <summary>Which of a room's three learnt numbers a reset or a lock is about.</summary>
public enum LearntKind
{
	WarmingRate,
	OutdoorTerm,
	Band
}

/// <summary>One room, as the page edits it. Saving sends this slice and never the rest of the document.</summary>
/// <param name="Id">What both halves name the room by.</param>
/// <param name="Name">What a person calls it.</param>
/// <param name="ModeTemperatures">One temperature per mode, each carrying the moment it was set.</param>
/// <param name="Sensors">The per-room sensor values.</param>
/// <param name="Learnt">The three learnt numbers.</param>
/// <param name="TemperatureSetByHand">The temperature somebody set at the card, or <c>null</c>.</param>
public sealed record RoomSlice(
	string Id,
	string Name,
	IReadOnlyDictionary<HeatingMode, Stamped<double>> ModeTemperatures,
	RoomSensorSettings Sensors,
	RoomLearntNumbers Learnt,
	double? TemperatureSetByHand)
{
	/// <summary>The entity id of this room's thermostat, which is what every action targets.</summary>
	/// <remarks>Filled from what the integration reports. Nothing is called for a room without one.</remarks>
	public string? Thermostat { get; init; }

	/// <summary>
	/// Whether the room has no temperature reading at all: no sensor of its own, and no neighbour to borrow from.
	/// Such a room takes on or off from a mode where another room takes a temperature.
	/// </summary>
	// Reported by the integration, because it follows from how the room was set up there. A room whose sensors have
	// merely gone quiet is not this case and keeps its temperatures.
	public bool NoReadingAtAll { get; init; }

	/// <summary>One on-or-off cell per mode, which is what a room with no reading carries in place of a temperature.</summary>
	public IReadOnlyDictionary<HeatingMode, Stamped<bool>> ModeSwitches { get; init; } =
		new Dictionary<HeatingMode, Stamped<bool>>();

	/// <summary>Every rise this room has made, which is what its warming rate is estimated from.</summary>
	public IReadOnlyList<WarmingRateMeasurement> RateMeasurements { get; init; } = [];

	public double TemperatureFor(HeatingMode mode) =>
		ModeTemperatures.TryGetValue(mode, out Stamped<double> held) ? held.Value : 0;

	// Worked out from what is above it, so writing it to the settings file would store one fact twice.
	[JsonIgnore]
	public bool StandsOffThePlan => TemperatureSetByHand.HasValue;

	[JsonIgnore]
	public bool Borrows => Sensors.BorrowsFrom is { Length: > 0 };
}
