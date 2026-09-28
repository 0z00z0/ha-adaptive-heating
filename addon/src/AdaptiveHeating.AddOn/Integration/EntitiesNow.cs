using System.Text.Json;

using NetDaemon.Client.HomeAssistant.Model;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>
/// The entities the heating reads, as the last thing heard from Home Assistant left them. Filled once per
/// connection and kept current by the changes Home Assistant reports.
/// </summary>
/// <remarks>
///     A subscription reports only what changes after it starts, so a fresh connection reads the whole house
///     once and this table is replaced by what came back. A change arriving while that read is in flight is held
///     and applied after it, because the read carries the house as it was when Home Assistant served it and
///     would otherwise put an older value back over a newer one.
/// </remarks>
internal sealed class EntitiesNow
{
	private readonly Lock _gate = new();
	private readonly Dictionary<string, EntityState> _entities = new(StringComparer.Ordinal);
	private readonly List<(string EntityId, HassState? State)> _whileReading = [];

	private bool _reading;

	/// <summary>Every entity held, which is what one pass over the rooms works from.</summary>
	public IReadOnlyList<EntityState> Snapshot()
	{
		lock (_gate)
			return [.. _entities.Values];
	}

	/// <summary>The read of the whole house has gone out. From here a change is held until it lands.</summary>
	public void Reading()
	{
		lock (_gate)
		{
			_reading = true;
			_whileReading.Clear();
		}
	}

	/// <summary>The house as it was read. Returns how many of those entities the heating reads.</summary>
	public int Read(IEnumerable<HassState> states, IReadOnlyCollection<string> alsoNamed)
	{
		ArgumentNullException.ThrowIfNull(states);
		ArgumentNullException.ThrowIfNull(alsoNamed);

		lock (_gate)
		{
			_entities.Clear();

			foreach (HassState state in states)
			{
				if (state.EntityId is { Length: > 0 } entityId && WhatTheHeatingReads.Reads(entityId, alsoNamed))
					_entities[entityId] = Of(entityId, state);
			}

			foreach ((string entityId, HassState? state) in _whileReading)
				Write(entityId, state);

			_whileReading.Clear();
			_reading = false;

			return _entities.Count;
		}
	}

	/// <summary>One entity as Home Assistant has just reported it, or gone where it reported none.</summary>
	public void Record(string entityId, HassState? state)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(entityId);

		lock (_gate)
		{
			if (_reading)
				_whileReading.Add((entityId, state));
			else
				Write(entityId, state);
		}
	}

	private void Write(string entityId, HassState? state)
	{
		if (state is null)
			_entities.Remove(entityId);
		else
			_entities[entityId] = Of(entityId, state);
	}

	private static EntityState Of(string entityId, HassState state) =>
		new(entityId, state.State, state.AttributesJson?.Deserialize<Dictionary<string, JsonElement>>())
		{
			LastChanged = Moment(state.LastChanged),
			LastUpdated = Moment(state.LastUpdated),
		};

	// The client hands over a DateTime, so the zone is named here. An unspecified kind is Home Assistant's own
	// UTC and must not be read as this machine's local time.
	private static DateTimeOffset? Moment(DateTime? value) =>
		value is { } at
			? new DateTimeOffset(at.Kind == DateTimeKind.Unspecified ? DateTime.SpecifyKind(at, DateTimeKind.Utc) : at)
			: null;
}
