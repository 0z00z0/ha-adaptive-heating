using System.Reactive.Concurrency;
using System.Threading.Channels;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Hosting;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>Keeps the add-on and the integration in touch: drives the rooms, sends what is queued, watches the clock.</summary>
/// <remarks>
///     Three things ask for a pass over the rooms: a change to an entity the heating reads, the next schedule
///     boundary, and the clock a minute at a time behind both. Start-up order does not matter: a core that is
///     not up yet is a connection that is not open, and the settings the add-on holds are its own whatever the
///     other half is doing.
/// </remarks>
internal sealed class ConnectionToTheIntegration : BackgroundService
{
	/// <summary>How long a pass may be from the one before it when nothing has changed. The safety net behind the events.</summary>
	public static readonly TimeSpan PassAtLeastEvery = TimeSpan.FromMinutes(1);

	private readonly CoreConnection _connection;
	private readonly TellsTheThermostats _tells;
	private readonly DrivesTheRooms _drives;
	private readonly TheCalendarsOnOffer _offered;
	private readonly ISettingsStore _store;
	private readonly NetworkSetClock _clock;
	private readonly IScheduler _scheduler;
	private readonly TimeProvider _time;
	private readonly ILogger<ConnectionToTheIntegration> _logger;

	// One pass is pending at a time. Anything asking for one during a pass collapses into the single pass after
	// it, and nothing is lost by the collapse: a pass reads the whole house when it runs and carries no queue.
	private readonly Channel<byte> _wanted =
		Channel.CreateBounded<byte>(new BoundedChannelOptions(1) { FullMode = BoundedChannelFullMode.DropWrite });

	private DateTimeOffset? _nextBoundary;
	private int _openedSeen;

	public ConnectionToTheIntegration(
		CoreConnection connection,
		TellsTheThermostats tells,
		DrivesTheRooms drives,
		TheCalendarsOnOffer offered,
		ISettingsStore store,
		NetworkSetClock clock,
		IScheduler scheduler,
		TimeProvider time,
		ILogger<ConnectionToTheIntegration> logger)
	{
		_connection = connection ?? throw new ArgumentNullException(nameof(connection));
		_tells = tells ?? throw new ArgumentNullException(nameof(tells));
		_drives = drives ?? throw new ArgumentNullException(nameof(drives));
		_offered = offered ?? throw new ArgumentNullException(nameof(offered));
		_store = store ?? throw new ArgumentNullException(nameof(store));
		_clock = clock ?? throw new ArgumentNullException(nameof(clock));
		_scheduler = scheduler ?? throw new ArgumentNullException(nameof(scheduler));
		_time = time ?? throw new ArgumentNullException(nameof(time));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <inheritdoc/>
	protected override async Task ExecuteAsync(CancellationToken stoppingToken)
	{
		Task sending = _tells.PumpAsync(stoppingToken);

		using BoundaryTimer boundary = new(_scheduler, () => _nextBoundary, OnePassPlease, _logger);

		_connection.SomethingChanged += OnePassPlease;

		Task ticking = TickAsync(stoppingToken);

		OnePassPlease();

		try
		{
			while (!stoppingToken.IsCancellationRequested)
			{
				try
				{
					await _wanted.Reader.ReadAsync(stoppingToken).ConfigureAwait(false);
				}
				catch (OperationCanceledException)
				{
					break;
				}

				_clock.Check();

				await OnePassAsync(boundary, stoppingToken).ConfigureAwait(false);
			}
		}
		finally
		{
			_connection.SomethingChanged -= OnePassPlease;
		}

		try
		{
			await Task.WhenAll(sending, ticking).ConfigureAwait(false);
		}
		catch (OperationCanceledException)
		{
			// Stopping, which is what the token asked for.
		}
	}

	private async Task OnePassAsync(BoundaryTimer boundary, CancellationToken token)
	{
		// A pass before the connection opens reads an empty house, so it reports an empty cabin: no presence, no
		// outdoor sensor and no forecast, none of which it can see yet. Opening the connection asks for a pass of
		// its own, and the pass a minute is behind that.
		if (!_connection.IsOpen)
		{
			_logger.LogDebug("No pass over the rooms: the connection to Home Assistant is not open yet.");

			return;
		}

		// Counted rather than watched for: a connection that went and came back between two passes leaves no
		// transition to see, and a core restart clears every card it was showing. What still holds is said again
		// on the first pass over a connection this loop has not seen before.
		int opened = _connection.TimesOpened;

		if (_openedSeen != opened)
		{
			_openedSeen = opened;
			_drives.TheConnectionCameBack();
		}

		IReadOnlyList<EntityState> states = _connection.House;

		// The settings page chooses a calendar out of what Home Assistant holds, and which integration created
		// each one is what says whether the record may be written to it.
		_store.ReceiveTheCalendarsOffered(await _offered.OfferedAsync(states, token).ConfigureAwait(false));

		MergedRooms merged = RoomsFromTheIntegration.Merge(_store.Read(), states, PlannerDefaults.Standard);

		if (merged.Changed)
		{
			_store.Receive(merged.Document);
			_logger.LogInformation("The integration reports {Count} room(s), running {Version}.",
				merged.Document.Rooms.Count, merged.Document.Versions.Integration);
		}

		// After the rooms are known, so a room this pass learnt about is driven on the same pass.
		DrivingPass pass = await _drives.RunAsync(states, _time.GetUtcNow(), token).ConfigureAwait(false);

		_nextBoundary = pass.NextBoundary;

		boundary.Arm();
	}

	private async Task TickAsync(CancellationToken token)
	{
		while (!token.IsCancellationRequested)
		{
			try
			{
				await Task.Delay(PassAtLeastEvery, _time, token).ConfigureAwait(false);
			}
			catch (OperationCanceledException)
			{
				return;
			}

			OnePassPlease();
		}
	}

	private void OnePassPlease() => _wanted.Writer.TryWrite(0);
}
