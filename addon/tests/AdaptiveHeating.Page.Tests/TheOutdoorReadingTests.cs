using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Planner;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// The outdoor temperature drives how hard every room works, so where it comes from when the sensors fail is what
/// a household feels. One or more sensors are chosen, and the forecast takes over when all of them are out.
/// </summary>
public sealed class TheOutdoorReadingTests
{
	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public void The_forecast_takes_over_when_every_chosen_sensor_fails()
	{
		PlannerDefaults defaults = PlannerDefaults.Standard;

		// The control: both sensors reported a moment ago, so the reading is theirs and the forecast is not read.
		OutdoorReading fromSensors = TheOutdoorTemperature.Read(
			States(
				Sensor(ACabin.OutdoorSensor, -4.0, Morning.AddMinutes(-2), Morning.AddMinutes(-2)),
				Sensor(ACabin.SecondOutdoorSensor, -4.4, Morning.AddMinutes(-3), Morning.AddMinutes(-3)),
				Forecast(2.0)),
			ACabin.Outdoor,
			Morning,
			defaults);

		Assert.Equal(OutdoorFrom.Sensors, fromSensors.From);
		Assert.Equal(-4.2, fromSensors.Temperature!.Value, precision: 6);

		// Both gone quiet for longer than the freshness window, which is what a dead battery looks like.
		DateTimeOffset longAgo = Morning - defaults.SensorFreshness - TimeSpan.FromMinutes(5);

		OutdoorReading fromForecast = TheOutdoorTemperature.Read(
			States(
				Sensor(ACabin.OutdoorSensor, -4.0, longAgo, longAgo),
				Sensor(ACabin.SecondOutdoorSensor, -4.4, longAgo, longAgo),
				Forecast(2.0)),
			ACabin.Outdoor,
			Morning,
			defaults);

		Assert.Equal(OutdoorFrom.Forecast, fromForecast.From);
		Assert.Equal(2.0, fromForecast.Temperature);

		// Both sensors are named as left out, and the reading is not quietly one of theirs.
		Assert.Equal(2, fromForecast.Sensors.LeftOut.Count());
		Assert.All(fromForecast.Sensors.LeftOut, verdict => Assert.Equal(SensorExclusion.Quiet, verdict.Excluded));
		Assert.NotEqual(-4.2, fromForecast.Temperature!.Value);

		// With no forecast to fall back on the answer is nothing, never the last sensor value.
		OutdoorReading nothing = TheOutdoorTemperature.Read(
			States(Sensor(ACabin.OutdoorSensor, -4.0, longAgo, longAgo)),
			new OutdoorChoice([ACabin.OutdoorSensor], Forecast: null),
			Morning,
			defaults);

		Assert.Equal(OutdoorFrom.Nothing, nothing.From);
		Assert.Null(nothing.Temperature);
	}

	private static List<EntityState> States(params string[] entities) =>
		JsonSerializer.Deserialize<List<EntityState>>($"[{string.Join(",", entities)}]")!;

	private static string Sensor(string entityId, double temperature, DateTimeOffset reportedAt, DateTimeOffset movedAt) =>
		$$"""
		{
			"entity_id": "{{entityId}}",
			"state": "{{Invariant(temperature)}}",
			"last_updated": "{{Moment(reportedAt)}}",
			"last_changed": "{{Moment(movedAt)}}",
			"attributes": { "friendly_name": "Outside", "unit_of_measurement": "°C" }
		}
		""";

	private static string Forecast(double temperature) =>
		$$"""
		{
			"entity_id": "{{ACabin.Forecast}}",
			"state": "cloudy",
			"attributes": { "friendly_name": "Cabin", "temperature": {{Invariant(temperature)}} }
		}
		""";

	private static string Moment(DateTimeOffset at) => at.ToString("O", CultureInfo.InvariantCulture);

	// A temperature written the Norwegian way is not a number to a JSON reader, and a state is a machine value.
	private static string Invariant(double value) => value.ToString(CultureInfo.InvariantCulture);
}
