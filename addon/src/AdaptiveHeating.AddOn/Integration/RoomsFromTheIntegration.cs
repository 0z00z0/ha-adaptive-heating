using System.Text.Json;

using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>The settings after a pass over the entities, and whether that pass learnt anything.</summary>
internal readonly record struct MergedRooms(HeatingDocument Document, bool Changed);

/// <summary>What the add-on learns about the rooms by reading Home Assistant's own entities.</summary>
/// <remarks>
///     A room is set up in the integration, so this is where the add-on finds out one exists and which
///     thermostat every action for it targets. A room already held is kept whatever Home Assistant says, so a
///     core that is down or still coming up never costs a person the temperatures they typed.
/// </remarks>
internal static class RoomsFromTheIntegration
{
	private const string FriendlyName = "friendly_name";

	// A starting value must lose every contest against a number somebody typed, whenever they typed it.
	private static readonly Stamp Starting = Stamp.Certain(default);

	/// <summary>One room as its thermostat reports it.</summary>
	private readonly record struct ReportedRoom(string RoomId, string Name, string Thermostat, string Version, bool NoReadingAtAll);

	/// <summary>Folds what the states say into the settings, leaving everything they do not mention alone.</summary>
	/// <remarks><c>Changed</c> is false where the pass learnt nothing new, so an unchanged minute costs no write.</remarks>
	public static MergedRooms Merge(HeatingDocument held, IReadOnlyList<EntityState> states, PlannerDefaults defaults)
	{
		ArgumentNullException.ThrowIfNull(held);
		ArgumentNullException.ThrowIfNull(states);
		ArgumentNullException.ThrowIfNull(defaults);

		List<ReportedRoom> reported = [.. Ours(states)];

		if (reported.Count == 0)
			return new MergedRooms(held, Changed: false);

		List<RoomSlice> rooms = [];
		HashSet<string> placed = new(StringComparer.Ordinal);
		bool changed = !string.Equals(held.Versions.Integration, reported[0].Version, StringComparison.Ordinal);

		foreach (RoomSlice room in held.Rooms)
		{
			int at = reported.FindIndex(one => string.Equals(one.RoomId, room.Id, StringComparison.Ordinal));

			if (at < 0)
			{
				rooms.Add(room);
				continue;
			}

			placed.Add(room.Id);

			changed |= !string.Equals(room.Name, reported[at].Name, StringComparison.Ordinal)
				|| !string.Equals(room.Thermostat, reported[at].Thermostat, StringComparison.Ordinal)
				|| room.NoReadingAtAll != reported[at].NoReadingAtAll;

			RoomSlice updated = room with
			{
				Name = reported[at].Name,
				Thermostat = reported[at].Thermostat,
				NoReadingAtAll = reported[at].NoReadingAtAll,
			};

			// A room set up with nothing to measure it needs its on-or-off cells, and the away cell starts on.
			if (updated.NoReadingAtAll && updated.ModeSwitches.Count == 0)
				updated = updated with { ModeSwitches = RoomModeSwitches.Starting(Starting) };

			rooms.Add(updated);
		}

		foreach (ReportedRoom one in reported)
		{
			if (!placed.Add(one.RoomId))
				continue;

			rooms.Add(FirstSeen(one, defaults));
			changed = true;
		}

		return new MergedRooms(
			held with { Rooms = rooms, Versions = held.Versions with { Integration = reported[0].Version } },
			changed);
	}

	// The integration's own version on a climate entity is the marker, because nothing else publishes it. Reading
	// a set of attribute names instead would claim any thermostat that happened to carry them.
	private static IEnumerable<ReportedRoom> Ours(IReadOnlyList<EntityState> states)
	{
		foreach (EntityState state in states)
		{
			if (!state.EntityId.StartsWith(WhatTheHeatingReads.ClimatePrefix, StringComparison.Ordinal) || state.Attributes is null)
				continue;

			if (Text(state.Attributes, HeatingActions.IntegrationVersionAttribute) is not { Length: > 0 } version)
				continue;

			if (Text(state.Attributes, HeatingActions.RoomAttribute) is not { Length: > 0 } roomId)
				continue;

			yield return new ReportedRoom(
				roomId,
				Text(state.Attributes, FriendlyName) ?? roomId,
				state.EntityId,
				version,
				Flag(state.Attributes, HeatingActions.NoReadingAtAllAttribute));
		}
	}

	private static RoomSlice FirstSeen(ReportedRoom reported, PlannerDefaults defaults) =>
		new(
			reported.RoomId,
			reported.Name,
			new Dictionary<HeatingMode, Stamped<double>>(),
			RoomSensorSettings.Standard(defaults),
			RoomLearntNumbers.Starting(defaults),
			TemperatureSetByHand: null)
		{
			Thermostat = reported.Thermostat,
			NoReadingAtAll = reported.NoReadingAtAll,
			ModeSwitches = reported.NoReadingAtAll
				? RoomModeSwitches.Starting(Starting)
				: new Dictionary<HeatingMode, Stamped<bool>>(),
		};

	private static bool Flag(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) && value.ValueKind == JsonValueKind.True;

	private static string? Text(IReadOnlyDictionary<string, JsonElement> attributes, string name) =>
		attributes.TryGetValue(name, out JsonElement value) && value.ValueKind == JsonValueKind.String
			? value.GetString()
			: null;
}
