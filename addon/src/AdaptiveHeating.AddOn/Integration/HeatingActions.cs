namespace AdaptiveHeating.AddOn.Integration;

/// <summary>The five actions and their fields, named once on this side of the boundary.</summary>
/// <remarks>
///     The integration declares the same five in <c>core/actions.py</c>. The two copies drift, and a field
///     renamed on one side has to be renamed on the other by hand. A field the integration does not know is
///     dropped there rather than refused, and an action it does not have is absent rather than fatal.
/// </remarks>
internal static class HeatingActions
{
	public const string Domain = "adaptive_heating";

	/// <summary>Home Assistant's own climate domain, whose standard action carries the temperature to hold now.</summary>
	public const string ClimateDomain = "climate";

	public const string SetTemperature = "set_temperature";

	public const string WarmRoomBy = "warm_room_by";
	public const string HoldTemperature = "hold_temperature";
	public const string SetWarmingRate = "set_warming_rate";
	public const string SetRegulation = "set_regulation";
	public const string ReturnToTarget = "return_to_target";

	public const string Temperature = "temperature";
	public const string ByTime = "by_time";
	public const string Duration = "duration";
	public const string DegreesPerHour = "degrees_per_hour";
	public const string MeasuredAtOutdoor = "measured_at_outdoor";
	public const string Behaviour = "behaviour";
	public const string Band = "band";
	public const string OutdoorShiftPerDegree = "outdoor_shift_per_degree";
	public const string CycleLength = "cycle_length";
	public const string FullOutputBelow = "full_output_below";
	public const string ShortestTimeBetweenRelayChanges = "shortest_time_between_relay_changes";

	/// <summary>On or off for a room with no reading, in place of the temperature another room is given.</summary>
	public const string Switched = "switched";

	public const string SwitchedOn = "on";
	public const string SwitchedOff = "off";

	/// <summary>The attributes every one of this integration's thermostats carries, and nothing else does.</summary>
	public const string RoomAttribute = "room";
	public const string IntegrationVersionAttribute = "integration_version";
	public const string VocabularyVersionAttribute = "vocabulary_version";

	/// <summary>What the add-on reads off a thermostat to drive it.</summary>
	public const string CurrentTemperatureAttribute = "current_temperature";
	public const string TargetTemperatureAttribute = "temperature";
	public const string HvacActionAttribute = "hvac_action";
	public const string NoReadingAtAllAttribute = "no_reading_at_all";
	public const string OutdoorAttribute = "outdoor";
	public const string TargetSetAtAttribute = "target_set_at";
	public const string WarmUpAttribute = "warm_up";
	public const string HoldEndsAtAttribute = "hold_ends_at";
	public const string PowerAttribute = "power";
	public const string HasAPowerMeterAttribute = "has_a_power_meter";

	/// <summary>What <see cref="HvacActionAttribute"/> reads while the relay is closed.</summary>
	public const string Heating = "heating";
}
