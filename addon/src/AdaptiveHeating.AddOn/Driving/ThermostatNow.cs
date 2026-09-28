using System.Globalization;
using System.Text.Json;

using AdaptiveHeating.AddOn.Integration;

namespace AdaptiveHeating.AddOn.Driving;

/// <summary>What one thermostat says about its room at this moment.</summary>
/// <param name="Target">
///     The temperature the room is holding, which is the warm-up's or the hold's while one runs, or
///     <c>null</c> where the thermostat publishes none.
/// </param>
/// <param name="TargetSetAt">When that temperature was last set, as the integration recorded it.</param>
internal sealed record ThermostatNow(
	string RoomId,
	string EntityId,
	double? RoomTemperature,
	double? Target,
	bool HeaterCommandedOn,
	bool NoReadingAtAll,
	double? Outdoor,
	DateTimeOffset? TargetSetAt,
	bool WarmUpRunning,
	DateTimeOffset? HoldEndsAt,
	double? PowerWatts,
	bool HasAPowerMeter)
{
	/// <summary>Reads one climate entity, or <c>null</c> where it is not one of this integration's thermostats.</summary>
	/// <remarks>
	///     The marker is the pair of attributes <see cref="RoomsFromTheIntegration"/> finds the rooms by, so a room
	///     this projection answers for is a room the settings hold and the other way round.
	/// </remarks>
	public static ThermostatNow? From(EntityState state, DateTimeOffset now)
	{
		ArgumentNullException.ThrowIfNull(state);

		if (state.Attributes is not { } attributes)
			return null;

		if (Attributes.Text(attributes, HeatingActions.IntegrationVersionAttribute) is not { Length: > 0 })
			return null;

		if (Attributes.Text(attributes, HeatingActions.RoomAttribute) is not { Length: > 0 } roomId)
			return null;

		(DateTimeOffset? starts, DateTimeOffset? deadline) = WarmUpWindow(attributes);

		// Not refused for a missing target. That is a room with no reading, which publishes none and takes on or
		// off in a mode's place; refusing it here takes the room out of the pass and the on-or-off path with it.
		return new ThermostatNow(
			roomId,
			state.EntityId,
			Attributes.Number(attributes, HeatingActions.CurrentTemperatureAttribute),
			Attributes.Number(attributes, HeatingActions.TargetTemperatureAttribute),
			string.Equals(Attributes.Text(attributes, HeatingActions.HvacActionAttribute), HeatingActions.Heating, StringComparison.Ordinal),
			Attributes.Flag(attributes, HeatingActions.NoReadingAtAllAttribute) ?? false,
			Attributes.Number(attributes, HeatingActions.OutdoorAttribute),
			Attributes.Moment(attributes, HeatingActions.TargetSetAtAttribute),
			starts <= now && now < deadline,
			Attributes.Moment(attributes, HeatingActions.HoldEndsAtAttribute),
			Attributes.Number(attributes, HeatingActions.PowerAttribute),
			Attributes.Flag(attributes, HeatingActions.HasAPowerMeterAttribute) ?? false);
	}

	public bool HoldUnexpiredAt(DateTimeOffset now) => HoldEndsAt > now;

	private static (DateTimeOffset? Starts, DateTimeOffset? Deadline) WarmUpWindow(IReadOnlyDictionary<string, JsonElement> attributes)
	{
		if (!attributes.TryGetValue(HeatingActions.WarmUpAttribute, out JsonElement warmUp) || warmUp.ValueKind != JsonValueKind.Object)
			return (null, null);

		return (Attributes.Moment(warmUp, "starts_at"), Attributes.Moment(warmUp, "deadline"));
	}
}

/// <summary>Reading one attribute of one entity, where anything the wrong shape reads as absent.</summary>
internal static class Attributes
{
	public static string? Text(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) && value.ValueKind == JsonValueKind.String
			? value.GetString()
			: null;

	public static double? Number(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) && value.ValueKind == JsonValueKind.Number
			? value.GetDouble()
			: null;

	/// <summary>Every string of a list-valued attribute, in the order reported. Anything else reads as empty.</summary>
	public static IReadOnlyList<string> TextList(IReadOnlyDictionary<string, JsonElement> attributes, string name)
	{
		ArgumentNullException.ThrowIfNull(attributes);

		if (!attributes.TryGetValue(name, out JsonElement value) || value.ValueKind != JsonValueKind.Array)
			return [];

		List<string> found = [];

		foreach (JsonElement one in value.EnumerateArray())
		{
			if (one.ValueKind == JsonValueKind.String && one.GetString() is { Length: > 0 } text)
				found.Add(text);
		}

		return found;
	}

	public static bool? Flag(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
			? value.GetBoolean()
			: null;

	public static DateTimeOffset? Moment(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) ? Moment(value) : null;

	public static DateTimeOffset? Moment(JsonElement holder, string name) =>
		holder.ValueKind == JsonValueKind.Object && holder.TryGetProperty(name, out JsonElement value) ? Moment(value) : null;

	private static DateTimeOffset? Moment(JsonElement value) =>
		value.ValueKind == JsonValueKind.String
		&& DateTimeOffset.TryParse(value.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out DateTimeOffset moment)
			? moment
			: null;
}
