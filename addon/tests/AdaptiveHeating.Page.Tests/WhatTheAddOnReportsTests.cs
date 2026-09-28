using System.Text.Json;

using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Persistence;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

using Xunit;

namespace AdaptiveHeating.Page.Tests;

/// <summary>
/// Everything the add-on says used to go to the logger and nowhere else, so a restart lost it and nothing reached
/// a person. Both of those are what a household notices, so both are proved here.
/// </summary>
public sealed class WhatTheAddOnReportsTests
{
	private static readonly DateTimeOffset Morning = new(2026, 9, 25, 7, 0, 0, TimeSpan.Zero);

	[Fact]
	public void The_record_still_holds_what_happened_after_a_restart()
	{
		string directory = ACabin.ScratchDirectory();

		try
		{
			string document = Path.Combine(directory, "heating.json");

			// The run that did something.
			StateStoreRegistry first = new(document, NullLogger<StateStoreRegistry>.Instance);
			ActivityRecord before = new(new ActivityJournal(first, TimeProvider.System, NullLogger<ActivityJournal>.Instance));

			before.Record(HeatingReport.About(WhatHappened.Started, Morning));
			before.Record(HeatingReport.About(WhatHappened.RoomHolds, Morning.AddMinutes(1), ACabin.RoomId) with { Temperature = 20 });

			// The journal is written coalesced, so the flush on the way out is what a restart reads.
			first.Dispose();

			// The run after it, reading the same file and nothing else.
			StateStoreRegistry second = new(document, NullLogger<StateStoreRegistry>.Instance);
			ActivityRecord after = new(new ActivityJournal(second, TimeProvider.System, NullLogger<ActivityJournal>.Instance));

			ActivityTimeline restored = after.Read();

			Assert.Equal(2, restored.Entries.Count);
			Assert.Equal(2, restored.Newest);

			// Newest first, and each one is the report that was filed rather than a placeholder for it.
			Assert.Equal(WhatHappened.RoomHolds, restored.Entries[0].Report.What);
			Assert.Equal(ACabin.RoomId, restored.Entries[0].RoomId);
			Assert.Equal(20, restored.Entries[0].Report.Temperature);
			Assert.Equal(WhatHappened.Started, restored.Entries[1].Report.What);

			// The count carries on from where it stopped, so nothing written next reuses a number.
			after.Record(HeatingReport.About(WhatHappened.ModeInForce, Morning.AddMinutes(2)));
			Assert.Equal(3, after.Newest);

			second.Dispose();
		}
		finally
		{
			Directory.Delete(directory, recursive: true);
		}
	}

	[Fact]
	public async Task A_report_that_needs_a_person_reaches_Home_Assistant_as_a_card()
	{
		await using AnOpenConnection open = await AnOpenConnection.StartAsync();

		TellsAPerson person = new(open.Api, NullLogger<TellsAPerson>.Instance);

		ReportsWhatHappened reports = new(
			new ActivityRecord(),
			person,
			// A display name that shares no word with the room's id, so a card built from the id could not pass.
			roomId => roomId == ACabin.RoomId ? "Scullery" : roomId,
			TheHouseholdClock.Of(TimeZoneInfo.Utc),
			NullLogger<ReportsWhatHappened>.Instance);

		// A room that cannot reach its deadline is something the add-on cannot put right itself.
		await reports.ReportAsync(
			HeatingReport.About(WhatHappened.CannotWarmInTime, Morning, ACabin.RoomId) with
			{
				Temperature = 20,
				Against = 18,
				Deadline = Morning.AddHours(2)
			},
			CancellationToken.None);

		SentCall raised = Assert.Single(open.Core.Calls);

		Assert.Equal($"{TellsAPerson.Domain}.{TellsAPerson.Create}", raised.Action);

		// Read as fields, not as a substring of the message: the writer escapes the degree sign, so a search for
		// the words as they are written would pass or fail on the encoder rather than on the card.
		using JsonDocument sent = JsonDocument.Parse(raised.Json);
		JsonElement fields = sent.RootElement.GetProperty("service_data");

		// The room is named as a person calls it, and the words say what is wrong and what it does reach.
		Assert.Equal("Scullery cannot reach 20 °C", fields.GetProperty("title").GetString());
		Assert.Equal("Reaches 18 °C by 09:00", fields.GetProperty("message").GetString());

		// The id is what makes the same problem replace its own card instead of stacking one.
		Assert.Equal(TellsAPerson.IdFor("Scullery cannot reach 20 °C"), fields.GetProperty("notification_id").GetString());

		// No card names the room by its identifier, which is not a word a person reads.
		Assert.DoesNotContain(ACabin.RoomId, raised.Json, StringComparison.Ordinal);

		// An ordinary report is filed and raises nothing: a card for every temperature trains a person to
		// dismiss them.
		await reports.ReportAsync(
			HeatingReport.About(WhatHappened.RoomHolds, Morning, ACabin.RoomId) with { Temperature = 20 },
			CancellationToken.None);

		Assert.Single(open.Core.Calls);
		Assert.Equal(2, reports.Recent().Entries.Count);
	}
}
