using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.Extensions.Logging.Abstractions;

namespace AdaptiveHeating.Page.Tests;

/// <summary>The driving pass with everything under it, so a test names only what it is about.</summary>
internal sealed class ADrivenCabin
{
	private ADrivenCabin(
		DrivesTheRooms driver,
		TheArrivals arrivals,
		RecordsTheWarmUps record,
		Calendars calendars)
	{
		Driver = driver;
		Arrivals = arrivals;
		Record = record;
		Calendars = calendars;
	}

	public DrivesTheRooms Driver { get; }

	/// <summary>The arrivals as the last reading left them, which is how a test sees every one that was read.</summary>
	public TheArrivals Arrivals { get; }

	/// <summary>The warm-ups awaiting the record, which is how a test counts what is still to be written.</summary>
	public RecordsTheWarmUps Record { get; }

	public Calendars Calendars { get; }

	/// <param name="note">Where the warm-ups awaiting the record are kept. Nothing keeps them where it is null.</param>
	/// <param name="household">The household's clock. UTC where a test is not about a zone, so a wall time is the instant.</param>
	public static ADrivenCabin Over(
		AnOpenConnection open,
		ISettingsStore store,
		ReportsWhatHappened reports,
		string? presenceHelper = null,
		OutdoorChoice? outdoor = null,
		IWarmUpNote? note = null,
		Func<string, string>? nameOf = null,
		TheHouseholdClock? household = null)
	{
		ArgumentNullException.ThrowIfNull(open);

		Calendars calendars = new(open.Api);
		TheArrivals arrivals = new(calendars, reports, NullLogger<TheArrivals>.Instance);
		RecordsTheWarmUps record = new(note, calendars, reports, nameOf ?? (roomId => roomId));

		DrivesTheRooms driver = new(
			store,
			open.Thermostats,
			PlannerDefaults.Standard,
			household ?? TheHouseholdClock.Of(TimeZoneInfo.Utc),
			presenceHelper,
			outdoor ?? OutdoorChoice.Nothing,
			reports,
			arrivals,
			record,
			NullLogger<DrivesTheRooms>.Instance);

		return new ADrivenCabin(driver, arrivals, record, calendars);
	}
}
