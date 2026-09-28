using System.Reactive.Concurrency;
using System.Reactive.Disposables;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// A boundary written on the day's profile has to bring the room's new temperature when it arrives. Without a
/// timer a boundary is noticed by the pass a minute, up to sixty seconds late, every day.
/// </summary>
public sealed class ABoundaryTimerTests
{
	[Fact]
	public void A_boundary_arriving_asks_for_a_pass_and_the_timer_arms_for_the_one_after_it()
	{
		DateTimeOffset[] boundaries =
		[
			new(2026, 9, 25, 6, 0, 0, TimeSpan.Zero),
			new(2026, 9, 25, 22, 0, 0, TimeSpan.Zero)
		];

		int next = 0;
		int passes = 0;
		SchedulerUnderTest scheduler = new();

		using BoundaryTimer timer = new(
			scheduler,
			() => boundaries[Math.Min(next, boundaries.Length - 1)],
			() => passes++,
			NullLogger.Instance);

		timer.Arm();

		// Armed one second past the boundary, so the pass the callback runs reads a clock on the new entry's side
		// of it. Armed on the boundary itself, the pass would resolve the entry that is going out.
		Assert.Equal(boundaries[0].AddSeconds(1), Assert.Single(scheduler.Armed).At);
		Assert.Equal(0, passes);

		next = 1;
		scheduler.FireTheOldest();

		Assert.Equal(1, passes);

		// It re-arms itself for the boundary after the one that fired. A one-shot that does not is a timer that
		// works once and then never again.
		Assert.Equal(2, scheduler.Armed.Count);
		Assert.Equal(boundaries[1].AddSeconds(1), scheduler.Armed[1].At);
	}

	[Fact]
	public void Arming_again_for_the_same_boundary_leaves_the_one_timer_running()
	{
		DateTimeOffset boundary = new(2026, 9, 25, 6, 0, 0, TimeSpan.Zero);
		SchedulerUnderTest scheduler = new();

		using BoundaryTimer timer = new(scheduler, () => boundary, () => { }, NullLogger.Instance);

		// Every pass arms, because a save or a sun that has moved changes where the next boundary falls. Arming
		// afresh for the boundary already waited for would push it back a whole interval each pass.
		timer.Arm();
		timer.Arm();
		timer.Arm();

		Assert.Single(scheduler.Armed);
	}

	[Fact]
	public void A_profile_that_places_no_boundary_arms_nothing()
	{
		SchedulerUnderTest scheduler = new();

		using BoundaryTimer timer = new(scheduler, () => null, () => { }, NullLogger.Instance);

		timer.Arm();

		// A house with no day profile, and a sun-anchored boundary the sun entity cannot place, both answer with
		// nothing. The pass a minute is what carries such a house.
		Assert.Empty(scheduler.Armed);
		Assert.Null(DayProfile.NextBoundaryAfter([], TimeZoneInfo.Utc, SunTimes.Unknown, DateTimeOffset.UnixEpoch));
	}

	/// <summary>One thing the timer scheduled, which a test fires by hand.</summary>
	private sealed record Armed(DateTimeOffset At, Action Run);

	/// <summary>A scheduler that records what was scheduled and runs it only when a test says to.</summary>
	private sealed class SchedulerUnderTest : IScheduler
	{
		public List<Armed> Armed { get; } = [];

		public DateTimeOffset Now => DateTimeOffset.UnixEpoch;

		public void FireTheOldest() => Armed[0].Run();

		public IDisposable Schedule<TState>(TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
		{
			Armed.Add(new Armed(dueTime, () => action(this, state)));

			return Disposable.Empty;
		}

		public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action) =>
			throw new NotSupportedException();

		public IDisposable Schedule<TState>(TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action) =>
			throw new NotSupportedException();
	}
}
