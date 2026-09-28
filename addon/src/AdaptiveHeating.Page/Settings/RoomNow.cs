namespace AdaptiveHeating.Page.Settings;

/// <summary>What one room's thermostat reads and holds, as the last pass over the rooms found it.</summary>
/// <param name="RoomId">What both halves name the room by, never what a person calls it.</param>
/// <param name="Temperature">The room's own reading, or <c>null</c> where it has none.</param>
/// <param name="Target">The temperature the thermostat is holding, which is a warm-up's while one runs.</param>
/// <param name="HeatingNow">Whether the relay is closed.</param>
/// <param name="ReadAt">When the thermostat was last read, so a stale line says so instead of reading as current.</param>
public sealed record RoomNow(
	string RoomId,
	double? Temperature,
	double Target,
	bool HeatingNow,
	DateTimeOffset ReadAt);
