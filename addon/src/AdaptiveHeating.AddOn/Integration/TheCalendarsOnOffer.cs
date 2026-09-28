using AdaptiveHeating.Page.Settings;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>
/// The calendars the settings page offers, and which integration created each one.
/// </summary>
/// <remarks>
///     Every calendar declares the same capabilities, so capability cannot say which one Home Assistant keeps
///     itself. The entity registry names the integration behind an entity, and that read is the only thing that
///     can. It is taken once per connection, and only where the house reports a calendar at all, so a cabin with
///     none never sends it.
/// </remarks>
internal sealed class TheCalendarsOnOffer
{
	private static readonly Dictionary<string, string> NothingKnown = new(StringComparer.Ordinal);

	private readonly CoreConnection _connection;
	private readonly ILogger<TheCalendarsOnOffer> _logger;

	private IReadOnlyDictionary<string, string> _platforms = NothingKnown;
	private int _readOnConnection = -1;

	public TheCalendarsOnOffer(CoreConnection connection, ILogger<TheCalendarsOnOffer> logger)
	{
		_connection = connection ?? throw new ArgumentNullException(nameof(connection));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <summary>Every calendar in the house, each marked with whether Home Assistant keeps it itself.</summary>
	public async Task<IReadOnlyList<CalendarOnOffer>> OfferedAsync(IReadOnlyList<EntityState> states, CancellationToken token)
	{
		ArgumentNullException.ThrowIfNull(states);

		if (HoldsACalendar(states))
			await ReadTheRegistryAsync(token).ConfigureAwait(false);

		return CalendarsInTheHouse.Offered(states, _platforms);
	}

	private static bool HoldsACalendar(IReadOnlyList<EntityState> states)
	{
		foreach (EntityState state in states)
		{
			if (state.EntityId.StartsWith(WhatTheHeatingReads.CalendarPrefix, StringComparison.Ordinal))
				return true;
		}

		return false;
	}

	// Taken again on a connection this has not read on. A read that did not go through leaves the marker where it
	// was, so the next pass tries again rather than the cabin waiting for a reconnection.
	private async Task ReadTheRegistryAsync(CancellationToken token)
	{
		int opened = _connection.TimesOpened;

		if (_readOnConnection == opened)
			return;

		ReplyFromTheCore reply = await _connection
			.AskAsync(CoreConnection.EntityRegistryCommand, token)
			.ConfigureAwait(false);

		if (!reply.Succeeded || reply.Result is not { } answer)
		{
			_logger.LogDebug(
				"The entity registry could not be read ({Code}), so no calendar is offered for the record yet.",
				reply.Code);

			return;
		}

		_platforms = EntityRegistryReading.CalendarPlatformsIn(answer);
		_readOnConnection = opened;

		_logger.LogInformation("Home Assistant reports {Count} calendar(s), and which integration keeps each.", _platforms.Count);
	}
}
