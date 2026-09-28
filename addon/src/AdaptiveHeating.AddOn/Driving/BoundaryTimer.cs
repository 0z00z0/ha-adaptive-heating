using System.Reactive.Concurrency;
using System.Reactive.Disposables;

namespace AdaptiveHeating.AddOn.Driving;

/// <summary>A one-shot that wakes at the next schedule boundary and re-arms itself for the one after it.</summary>
/// <remarks>
///     Copied from the lighting engine's <c>BoundaryTimer</c>, read on 2026-09-25. The two copies drift, and a
///     fault found in either is carried across by hand.
/// </remarks>
// Arm is idempotent and is called after every pass too, which picks up a boundary the sun has moved and a
// profile a save has rebuilt. The pass a minute is the safety net, so a timer that never fires costs lateness,
// not correctness.
internal sealed class BoundaryTimer : IDisposable
{
	// Armed just past the boundary, so the instant the callback reads is on the new entry's side of it.
	private static readonly TimeSpan Lead = TimeSpan.FromSeconds(1);

	private readonly IScheduler _scheduler;
	private readonly Func<DateTimeOffset?> _nextBoundary;
	private readonly Action _onBoundary;
	private readonly ILogger _logger;
	private readonly SerialDisposable _armed = new();
	private readonly object _gate = new();

	private DateTimeOffset? _armedFor;

	internal BoundaryTimer(IScheduler scheduler, Func<DateTimeOffset?> nextBoundary, Action onBoundary, ILogger logger)
	{
		_scheduler = scheduler ?? throw new ArgumentNullException(nameof(scheduler));
		_nextBoundary = nextBoundary ?? throw new ArgumentNullException(nameof(nextBoundary));
		_onBoundary = onBoundary ?? throw new ArgumentNullException(nameof(onBoundary));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <summary>Arms for the next boundary, re-arming when that boundary has moved; safe to call at any time.</summary>
	internal void Arm()
	{
		if (_nextBoundary() is not { } boundary)
			return;

		DateTimeOffset at = boundary + Lead;

		// The gate keeps _armedFor and the scheduled timer in step; splitting them leaves _armedFor naming one
		// boundary while the surviving timer waits for another.
		lock (_gate)
		{
			if (_armedFor == at)
				return;

			_armedFor = at;
			_armed.Disposable = _scheduler.Schedule(at, OnBoundary);
		}
	}

	private void OnBoundary()
	{
		lock (_gate)
			_armedFor = null;

		try
		{
			_onBoundary();
		}
		catch (Exception exception) when (exception is not (OutOfMemoryException or StackOverflowException))
		{
			// Swallowed so the re-arm below still runs: a one-shot that dies on one bad boundary stays dead.
			_logger.LogWarning(exception, "Asking for a pass at a schedule boundary threw; the pass a minute still runs.");
		}

		Arm();
	}

	public void Dispose() => _armed.Dispose();
}
