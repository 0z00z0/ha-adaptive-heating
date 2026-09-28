using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.Page.Tests;

/// <summary>One room and one period, which is the smallest settings document anything can be saved against.</summary>
internal static class ACabin
{
	public const string RoomId = "kitchen";
	public const string Thermostat = "climate.kitchen";

	/// <summary>The dropdown a person moves to say the cabin is empty, which is one of the entities the heating reads.</summary>
	public const string PresenceHelper = "input_select.presence";

	/// <summary>The outdoor sensors a person chose on the add-on's own configuration page.</summary>
	public const string OutdoorSensor = "sensor.outdoor_north";

	public const string SecondOutdoorSensor = "sensor.outdoor_south";

	/// <summary>The weather entity the rooms run on when every chosen outdoor sensor fails the check.</summary>
	public const string Forecast = "weather.cabin";

	public static readonly DateTimeOffset Typed = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);

	/// <summary>The outdoor sensors and the forecast, as the add-on's configuration form hands them over.</summary>
	public static OutdoorChoice Outdoor { get; } = new([OutdoorSensor, SecondOutdoorSensor], Forecast);

	/// <summary>Every option of the dropdown against the state it stands for, as a finished setup leaves it.</summary>
	/// <remarks>A document carrying none reads every value as unmapped, which is what a fresh cabin starts on.</remarks>
	public static PresenceMap Mapped { get; } = PresenceMap.Of(
	[
		new PresenceOption("away", PresenceState.Away),
		new PresenceOption("everyday", PresenceState.Everyday),
		new PresenceOption("night", PresenceState.Night),
		new PresenceOption("guest", PresenceState.Guest),
		new PresenceOption("planned to arrive", PresenceState.PlannedToArrive),
		new PresenceOption("on the way", PresenceState.OnTheWay),
		new PresenceOption("temporarily away", PresenceState.TemporarilyAway),
	]);

	public static HeatingDocument WithOneRoom(double away = 4, double home = 20) =>
		new(
			[
				new RoomSlice(
					RoomId,
					"Kitchen",
					new Dictionary<HeatingMode, Stamped<double>>
					{
						[HeatingMode.Away] = Held(away),
						[HeatingMode.Home] = Held(home)
					},
					RoomSensorSettings.Standard(PlannerDefaults.Standard),
					RoomLearntNumbers.Starting(PlannerDefaults.Standard),
					TemperatureSetByHand: null)
				{
					Thermostat = Thermostat
				}
			],
			[],
			WritesPresence: false,
			SecondWriterSeen: false,
			DeadlineMeaningAvailable: false,
			new HalfVersions(HalfVersions.AddOnVersion, null, Vocabulary.Version));

	public static Stamped<double> Held(double value, DateTimeOffset? at = null) =>
		new(value, Stamp.Certain(at ?? Typed), ChangeOrigin.SettingsPage);

	/// <summary>A directory of its own per test, removed afterwards, so two tests never share a settings file.</summary>
	public static string ScratchDirectory()
	{
		string path = Path.Combine(Path.GetTempPath(), "adaptive-heating-tests", Guid.NewGuid().ToString("n"));
		Directory.CreateDirectory(path);

		return path;
	}
}

/// <summary>A clock a test moves by hand.</summary>
internal sealed class ClockUnderTest : TimeProvider
{
	private DateTimeOffset _now;

	public ClockUnderTest(DateTimeOffset now) => _now = now;

	public override DateTimeOffset GetUtcNow() => _now;

	public void MoveTo(DateTimeOffset now) => _now = now;
}
