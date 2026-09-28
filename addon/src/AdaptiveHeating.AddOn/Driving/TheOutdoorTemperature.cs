using System.Globalization;

using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Driving;

/// <summary>Where the outdoor temperature the rooms are running on came from.</summary>
internal enum OutdoorFrom
{
	/// <summary>Nothing was chosen, so each thermostat's own attribute is all there is.</summary>
	NothingChosen,

	/// <summary>One or more of the chosen sensors passed the check.</summary>
	Sensors,

	/// <summary>Every chosen sensor failed the check, so the forecast is what the rooms run on.</summary>
	Forecast,

	/// <summary>Sensors were chosen, and neither they nor the forecast answered.</summary>
	Nothing
}

/// <summary>The outdoor temperature this pass, and what the check made of each chosen sensor.</summary>
internal sealed record OutdoorReading(double? Temperature, OutdoorFrom From, RoomReading Sensors);

/// <summary>
/// The outdoor temperature, from the sensors a person chose and from the forecast behind them.
/// </summary>
/// <remarks>
///     The sensors go through the same check a room's own do: one that has gone quiet is left out, one sitting at
///     a single value is left out as a dying battery, a disagreeing pair loses both, and an outlier among three or
///     more loses itself. Where that leaves no temperature, the forecast is what the rooms run on.
/// </remarks>
internal static class TheOutdoorTemperature
{
	/// <summary>The attribute a weather entity carries its own current temperature in.</summary>
	public const string ForecastAttribute = "temperature";

	private static readonly RoomReading NoneChosen = new(null, 0, 0, []);

	public static OutdoorReading Read(
		IReadOnlyList<EntityState> states,
		OutdoorChoice chosen,
		DateTimeOffset asAt,
		PlannerDefaults defaults)
	{
		ArgumentNullException.ThrowIfNull(states);
		ArgumentNullException.ThrowIfNull(chosen);
		ArgumentNullException.ThrowIfNull(defaults);

		if (!chosen.Chosen)
			return new OutdoorReading(null, OutdoorFrom.NothingChosen, NoneChosen);

		List<SensorReading> reporting = [];

		foreach (string sensorId in chosen.Sensors)
		{
			if (Find(states, sensorId) is not { } sensor || Number(sensor.State) is not { } temperature)
				continue;

			reporting.Add(new SensorReading(
				sensorId,
				temperature,
				sensor.LastUpdated ?? asAt,
				sensor.LastChanged ?? asAt));
		}

		RoomReading reading = RoomSensors.Read(reporting, asAt, defaults);

		if (reading.Temperature is { } fromTheSensors)
			return new OutdoorReading(fromTheSensors, OutdoorFrom.Sensors, reading);

		if (chosen.Forecast is { Length: > 0 } forecast
			&& Find(states, forecast) is { Attributes: { } attributes }
			&& Attributes.Number(attributes, ForecastAttribute) is { } fromTheForecast)
		{
			return new OutdoorReading(fromTheForecast, OutdoorFrom.Forecast, reading);
		}

		return new OutdoorReading(null, OutdoorFrom.Nothing, reading);
	}

	private static EntityState? Find(IReadOnlyList<EntityState> states, string entityId) =>
		states.FirstOrDefault(state => string.Equals(state.EntityId, entityId, StringComparison.Ordinal));

	// Invariant: a state is a machine-readable value, and under nb-NO a full stop would read as a thousands mark.
	// A sensor reading unavailable or unknown parses as nothing, which is the same as one that never reported.
	private static double? Number(string? state) =>
		double.TryParse(state, NumberStyles.Float, CultureInfo.InvariantCulture, out double value) ? value : null;
}
