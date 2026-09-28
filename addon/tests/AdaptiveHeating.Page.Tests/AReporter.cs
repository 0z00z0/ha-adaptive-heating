using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

namespace AdaptiveHeating.Page.Tests;

/// <summary>One card the add-on raised, as Home Assistant would have received it.</summary>
internal sealed record ACard(string Title, string Message);

/// <summary>Stands in for Home Assistant's own notifications, keeping what it was asked to raise.</summary>
internal sealed class ACardCollector : ITellsAPerson
{
	private readonly List<ACard> _raised = [];

	public IReadOnlyList<ACard> Raised => _raised;

	/// <summary>Whether the next call answers as though the card did not reach Home Assistant.</summary>
	public bool Refuses { get; set; }

	/// <inheritdoc/>
	public Task<bool> NotifyAsync(string title, string message, CancellationToken token)
	{
		_raised.Add(new ACard(title, message));

		return Task.FromResult(!Refuses);
	}
}

/// <summary>A reporter over a record and a collector, so a test can read both what was kept and what was raised.</summary>
internal sealed class AReporter
{
	/// <param name="household">The household's clock. UTC where a test is not about a zone, so a line is easy to read.</param>
	public AReporter(
		IActivityJournal? journal = null,
		Func<string, string>? nameOf = null,
		TheHouseholdClock? household = null)
	{
		Record = new ActivityRecord(journal);
		Cards = new ACardCollector();
		Reports = new ReportsWhatHappened(
			Record,
			Cards,
			nameOf ?? (roomId => roomId),
			household ?? TheHouseholdClock.Of(TimeZoneInfo.Utc),
			NullLogger<ReportsWhatHappened>.Instance);
	}

	public ActivityRecord Record { get; }

	public ACardCollector Cards { get; }

	public ReportsWhatHappened Reports { get; }
}
