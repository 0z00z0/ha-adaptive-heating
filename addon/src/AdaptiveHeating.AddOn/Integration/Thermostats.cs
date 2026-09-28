namespace AdaptiveHeating.AddOn.Integration;

/// <summary>The five actions, each with its own fields, called against one room's thermostat.</summary>
internal sealed class Thermostats
{
	private readonly CoreApi _api;

	public Thermostats(CoreApi api) =>
		_api = api ?? throw new ArgumentNullException(nameof(api));

	/// <summary>The room starts early enough to be at <paramref name="temperature"/> by <paramref name="byTime"/>.</summary>
	public Task<ActionOutcome> WarmRoomByAsync(string thermostat, double temperature, DateTimeOffset byTime, CancellationToken token) =>
		_api.CallAsync(HeatingActions.Domain, HeatingActions.WarmRoomBy, thermostat, new Dictionary<string, object?>(StringComparer.Ordinal)
		{
			[HeatingActions.Temperature] = temperature,
			[HeatingActions.ByTime] = CoreApi.AsTime(byTime)
		}, token);

	/// <summary>The room holds <paramref name="temperature"/> for <paramref name="lasts"/>, then falls back to its target.</summary>
	public Task<ActionOutcome> HoldTemperatureAsync(string thermostat, double temperature, TimeSpan lasts, CancellationToken token) =>
		_api.CallAsync(HeatingActions.Domain, HeatingActions.HoldTemperature, thermostat, new Dictionary<string, object?>(StringComparer.Ordinal)
		{
			[HeatingActions.Temperature] = temperature,
			[HeatingActions.Duration] = lasts.TotalSeconds
		}, token);

	/// <summary>The room works backwards from a deadline on <paramref name="degreesPerHour"/>.</summary>
	public Task<ActionOutcome> SetWarmingRateAsync(
		string thermostat,
		double degreesPerHour,
		double? measuredAtOutdoor,
		CancellationToken token) =>
		_api.CallAsync(HeatingActions.Domain, HeatingActions.SetWarmingRate, thermostat, new Dictionary<string, object?>(StringComparer.Ordinal)
		{
			[HeatingActions.DegreesPerHour] = degreesPerHour,
			[HeatingActions.MeasuredAtOutdoor] = measuredAtOutdoor
		}, token);

	/// <summary>The loop runs on these numbers until it is given others. Anything left out is left as it was.</summary>
	public Task<ActionOutcome> SetRegulationAsync(
		string thermostat,
		string? behaviour = null,
		double? band = null,
		double? outdoorShiftPerDegree = null,
		TimeSpan? cycleLength = null,
		double? fullOutputBelow = null,
		TimeSpan? shortestTimeBetweenRelayChanges = null,
		string? switched = null,
		CancellationToken token = default) =>
		_api.CallAsync(HeatingActions.Domain, HeatingActions.SetRegulation, thermostat, new Dictionary<string, object?>(StringComparer.Ordinal)
		{
			[HeatingActions.Behaviour] = behaviour,
			[HeatingActions.Band] = band,
			[HeatingActions.OutdoorShiftPerDegree] = outdoorShiftPerDegree,
			[HeatingActions.CycleLength] = cycleLength?.TotalSeconds,
			[HeatingActions.FullOutputBelow] = fullOutputBelow,
			[HeatingActions.ShortestTimeBetweenRelayChanges] = shortestTimeBetweenRelayChanges?.TotalSeconds,
			[HeatingActions.Switched] = switched
		}, token);

	/// <summary>The temperature the room holds now, through Home Assistant's own climate action rather than one of ours.</summary>
	/// <remarks>Nothing clamps it. The away mode's temperature is the frost protection and not a floor, so a
	/// temperature set below it is accepted and reaches the room.</remarks>
	public Task<ActionOutcome> SetTemperatureAsync(string thermostat, double temperature, CancellationToken token) =>
		_api.CallAsync(HeatingActions.ClimateDomain, HeatingActions.SetTemperature, thermostat,
			new Dictionary<string, object?>(StringComparer.Ordinal) { [HeatingActions.Temperature] = temperature }, token);

	/// <summary>A room with no reading takes on or off in a mode's place, and this is how it arrives.</summary>
	public Task<ActionOutcome> SwitchAsync(string thermostat, bool on, CancellationToken token) =>
		SetRegulationAsync(thermostat, switched: on ? HeatingActions.SwitchedOn : HeatingActions.SwitchedOff, token: token);

	/// <summary>Any warm-up and any timed hold end, and the room holds the temperature it was last set.</summary>
	public Task<ActionOutcome> ReturnToTargetAsync(string thermostat, CancellationToken token) =>
		_api.CallAsync(HeatingActions.Domain, HeatingActions.ReturnToTarget, thermostat,
			new Dictionary<string, object?>(StringComparer.Ordinal), token);
}
