using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Reporting;

/// <summary>
/// Where everything the add-on says goes: the activity record, the log, and a card in Home Assistant for the few
/// things a person has to see.
/// </summary>
/// <remarks>
///     One call, three destinations, so nothing the add-on does is said in only one of them. The record is bounded
///     and journalled, so a restart keeps it; the log is the durable copy; the card is only for what the add-on
///     cannot put right itself.
/// </remarks>
internal sealed class ReportsWhatHappened
{
	private readonly ActivityRecord _record;
	private readonly ITellsAPerson _person;
	private readonly Func<string, string> _nameOf;
	private readonly TheHouseholdClock _household;
	private readonly ILogger<ReportsWhatHappened> _logger;

	/// <param name="record">The bounded, journalled record every report is kept in.</param>
	/// <param name="person">Where a card goes for the few reports that need one.</param>
	/// <param name="nameOf">What a person calls a room, given its id. The record holds the id and never the name.</param>
	/// <param name="household">The household's clock, which every time in a line is rendered on.</param>
	/// <param name="logger">The log both the line and the card are also written to.</param>
	public ReportsWhatHappened(
		ActivityRecord record,
		ITellsAPerson person,
		Func<string, string> nameOf,
		TheHouseholdClock household,
		ILogger<ReportsWhatHappened> logger)
	{
		_record = record ?? throw new ArgumentNullException(nameof(record));
		_person = person ?? throw new ArgumentNullException(nameof(person));
		_nameOf = nameOf ?? throw new ArgumentNullException(nameof(nameOf));
		_household = household ?? throw new ArgumentNullException(nameof(household));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <summary>What the add-on has recently done, for a reader of the record.</summary>
	public ActivityTimeline Recent() => _record.Read();

	/// <summary>Files one report, and raises a card for it where it needs a person.</summary>
	/// <returns>
	///     Whether nothing about this report is outstanding: false only where a card was needed and did not reach
	///     Home Assistant. A latch that stops the same card arriving every minute reads this, so a card refused
	///     while the connection was down is raised again by the next pass.
	/// </returns>
	public async Task<bool> ReportAsync(HeatingReport report, CancellationToken token)
	{
		ArgumentNullException.ThrowIfNull(report);

		_record.Record(report);

		ActivityLine line = ReportWords.Describe(report, NameOf(report.RoomId), _household);

		if (report.NeedsAPerson)
		{
			_logger.LogWarning("{What}. {Why}", line.What, line.Why);

			return await _person.NotifyAsync(line.What, line.Why, token).ConfigureAwait(false);
		}

		_logger.LogInformation("{What}. {Why}", line.What, line.Why);

		return true;
	}

	// A room the settings no longer hold reads as its own id, which is still something a person can look up.
	private string NameOf(string? roomId) => roomId is { Length: > 0 } named ? _nameOf(named) : "The cabin";
}
