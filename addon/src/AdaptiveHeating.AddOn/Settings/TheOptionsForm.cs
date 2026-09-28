namespace AdaptiveHeating.AddOn.Settings;

/// <summary>The outdoor sensors a person chose, and the forecast that stands in when every one of them fails.</summary>
/// <param name="Sensors">Entity ids, in the order they were given. Empty where none was chosen.</param>
/// <param name="Forecast">The weather entity whose own temperature the rooms run on when the sensors say nothing.</param>
internal sealed record OutdoorChoice(IReadOnlyList<string> Sensors, string? Forecast)
{
	public static OutdoorChoice Nothing { get; } = new([], null);

	/// <summary>Whether anything was chosen at all. Where nothing was, the thermostat's own attribute is all there is.</summary>
	public bool Chosen => Sensors.Count > 0 || Forecast is { Length: > 0 };

	/// <summary>Every entity this choice names, which is what the connection has to be watching.</summary>
	public IEnumerable<string> Entities =>
		Forecast is { Length: > 0 } forecast ? [.. Sensors, forecast] : Sensors;
}

/// <summary>What the add-on's own configuration page answers, as the process reads it.</summary>
/// <remarks>
///     The Supervisor writes the form to <c>/data/options.json</c>, so the configuration provider reads it like any
///     other file and the keys sit at the root. A key the form leaves empty falls back to what the image carries,
///     which is what keeps a house running while nobody has opened the form.
/// </remarks>
internal static class TheOptionsForm
{
	/// <summary>Where the Supervisor writes the answers. Named in the manifest's schema and nowhere else.</summary>
	public const string Path = "/data/options.json";

	public const string PresenceHelperKey = "presence_helper";
	public const string OutdoorSensorsKey = "outdoor_sensors";
	public const string ForecastEntityKey = "forecast_entity";

	/// <summary>The presence helper from the form, or the one the image was built with.</summary>
	public static string? PresenceHelper(IConfiguration configuration)
	{
		ArgumentNullException.ThrowIfNull(configuration);

		return configuration[PresenceHelperKey] is { Length: > 0 } fromTheForm
			? fromTheForm
			: configuration["AdaptiveHeating:PresenceHelper"];
	}

	/// <summary>The outdoor sensors and the forecast from the form.</summary>
	public static OutdoorChoice Outdoor(IConfiguration configuration)
	{
		ArgumentNullException.ThrowIfNull(configuration);

		// Read child by child rather than bound to an array: an empty list in the form arrives as a section with
		// no children, and a blank row a person left behind is not an entity id.
		List<string> sensors = [.. configuration
			.GetSection(OutdoorSensorsKey)
			.GetChildren()
			.Select(one => one.Value)
			.Where(one => one is { Length: > 0 })
			.Select(one => one!)];

		string? forecast = configuration[ForecastEntityKey] is { Length: > 0 } named ? named : null;

		return sensors.Count == 0 && forecast is null ? OutdoorChoice.Nothing : new OutdoorChoice(sensors, forecast);
	}
}
