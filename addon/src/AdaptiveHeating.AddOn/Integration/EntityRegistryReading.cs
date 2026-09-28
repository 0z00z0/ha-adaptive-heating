using System.Text.Json;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>
/// Reads which integration created each calendar entity out of Home Assistant's entity registry.
/// </summary>
/// <remarks>
///     The display form of the registry names an entity id <c>ei</c> and the integration behind it <c>pl</c>, read
///     from <c>RegistryEntry.as_display_dict</c> on 2026-09-25. Nothing else in the answer is read, and an entry
///     the wrong shape is skipped rather than refused, so one odd row cannot cost the whole reading.
/// </remarks>
internal static class EntityRegistryReading
{
	private const string Entities = "entities";
	private const string EntityIdField = "ei";
	private const string PlatformField = "pl";

	/// <summary>Every calendar entity in the answer, against the integration that created it.</summary>
	public static IReadOnlyDictionary<string, string> CalendarPlatformsIn(JsonElement answer)
	{
		Dictionary<string, string> found = new(StringComparer.Ordinal);

		if (answer.ValueKind != JsonValueKind.Object
			|| !answer.TryGetProperty(Entities, out JsonElement entities)
			|| entities.ValueKind != JsonValueKind.Array)
			return found;

		foreach (JsonElement entry in entities.EnumerateArray())
		{
			if (entry.ValueKind != JsonValueKind.Object)
				continue;

			if (!entry.TryGetProperty(EntityIdField, out JsonElement id) || id.ValueKind != JsonValueKind.String)
				continue;

			if (id.GetString() is not { Length: > 0 } entityId
				|| !entityId.StartsWith(WhatTheHeatingReads.CalendarPrefix, StringComparison.Ordinal))
				continue;

			if (!entry.TryGetProperty(PlatformField, out JsonElement platform) || platform.ValueKind != JsonValueKind.String)
				continue;

			if (platform.GetString() is { Length: > 0 } named)
				found[entityId] = named;
		}

		return found;
	}
}
