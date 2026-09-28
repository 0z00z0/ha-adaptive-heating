using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace PageHost;

/// <summary>
/// A cabin made up, so every state the page can draw is on screen at once: a room standing off the plan, a
/// room borrowing its neighbour's reading, a learnt number nobody has measured, and one a person has locked.
/// </summary>
internal static class HouseSeed
{
	public static HeatingDocument Cabin()
	{
		PlannerDefaults defaults = PlannerDefaults.Standard;
		DateTimeOffset when = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);

		RoomSlice living = Room("stue", "Living room", 4, 16, 21, 23, 20, defaults, when);
		RoomSlice bedroom = Room("soverom", "Bedroom", 4, 15, 19, 22, 18, defaults, when);

		RoomSlice annexe = Room("tilbygg", "Annexe", 4, 14, 19, 22, 18, defaults, when) with
		{
			// No sensor of its own: it holds the living room's reading and its card says whose.
			Sensors = RoomSensorSettings.Standard(defaults) with { BorrowsFrom = "stue" }
		};

		RoomSlice cloakroom = Room("toalett", "Cloakroom", 4, 12, 17, 20, 16, defaults, when) with
		{
			// Somebody turned it up at the card, so it stands off the plan until something replaces it.
			TemperatureSetByHand = 21
		};

		return new HeatingDocument(
			[living, bedroom, annexe, cloakroom],
			[
				Period("morning", BoundaryAnchor.ClockTime, new TimeSpan(6, 30, 0), BoundaryMeaning.Starts, 20, when),
				Period("evening", BoundaryAnchor.Sunset, TimeSpan.FromMinutes(-30), BoundaryMeaning.Starts, 21, when),
				Period("night", BoundaryAnchor.ClockTime, new TimeSpan(23, 0, 0), BoundaryMeaning.Starts, 16, when)
			],
			WritesPresence: false,
			SecondWriterSeen: false,
			DeadlineMeaningAvailable: true,
			new HalfVersions(HalfVersions.AddOnVersion, "0.1.0-preview.1", Vocabulary.Version))
		{
			// Chosen by hand, so the source and the expiry are both on screen. Following presence draws neither.
			ModeSetByHand = ModeByHand.Of(HeatingMode.DayProfile, ModeByHand.Standard, Stamp.Certain(when)),

			// Three calendars, so every state of the two settings is on screen: a local one the record may use, a
			// calendar of somebody else's that only the arrivals may read, and a chosen one Home Assistant has
			// stopped reporting.
			CalendarsOffered =
			[
				new CalendarOnOffer("calendar.adaptiveheating_log", "Heating record", Local: true),
				new CalendarOnOffer("calendar.alex", "Alex", Local: false),
			],
			ArrivalCalendar = "calendar.adaptiveheating_plan",
			RecordCalendar = "calendar.adaptiveheating_log",

			// Five options offered and three mapped, so both states of a presence row are on screen at once: one
			// naming its state, and one the page can map because the dropdown offers it.
			PresenceOptionsOffered = ["Hjemme", "Borte", "Natt", "Planlagt", "Midlertidig borte"],
			Presence = PresenceMap.Of(
			[
				new PresenceOption("Hjemme", PresenceState.Everyday),
				new PresenceOption("Borte", PresenceState.Away),
				new PresenceOption("Natt", PresenceState.Night),
			]),

			// What each room reads and holds, so the live readout is on screen. The cloakroom is left out of both,
			// because a room nothing has been heard about is itself a state the page has to draw.
			Now = new Dictionary<string, RoomNow>(StringComparer.Ordinal)
			{
				["stue"] = new("stue", 20.4, 21, HeatingNow: true, when.AddMinutes(41)),
				["soverom"] = new("soverom", 18.8, 19, HeatingNow: false, when.AddMinutes(41)),

				// The annexe borrows its reading, so its own thermostat reports none.
				["tilbygg"] = new("tilbygg", null, 19, HeatingNow: false, when.AddMinutes(41)),
			},

			InForce = InForceRecord.Empty with
			{
				Mode = new Stamped<string>(nameof(HeatingMode.DayProfile), Stamp.Certain(when), ChangeOrigin.SettingsPage),
				ModeFrom = ModeChosenBy.Hand,

				// The annexe is told nothing, which is the third state the readout has to draw.
				Temperatures = new Dictionary<string, Stamped<double>>(StringComparer.Ordinal)
				{
					["stue"] = Held(21, when),
					["soverom"] = Held(19, when),
				},
			},
		};
	}

	private static RoomSlice Room(
		string id,
		string name,
		double away,
		double night,
		double home,
		double boost,
		double dayProfile,
		PlannerDefaults defaults,
		DateTimeOffset when)
	{
		Dictionary<HeatingMode, Stamped<double>> temperatures = new()
		{
			[HeatingMode.Away] = Held(away, when),
			[HeatingMode.Night] = Held(night, when),
			[HeatingMode.Home] = Held(home, when),
			[HeatingMode.Boost] = Held(boost, when),
			[HeatingMode.DayProfile] = Held(dayProfile, when)
		};

		return new RoomSlice(id, name, temperatures, RoomSensorSettings.Standard(defaults), Learnt(defaults, id), null);
	}

	// The living room has a winter behind it, the bedroom's band is held by a person, and the annexe has
	// nothing measured at all — which is the state that has to read as "not measured" rather than a figure.
	private static RoomLearntNumbers Learnt(PlannerDefaults defaults, string roomId)
	{
		RoomLearntNumbers starting = RoomLearntNumbers.Starting(defaults);

		return roomId switch
		{
			"stue" => starting with
			{
				WarmingRate = starting.WarmingRate with { SystemValue = 1.35, MeasurementCount = 47 },
				OutdoorTerm = starting.OutdoorTerm with { SystemValue = 0.0072, MeasurementCount = 31 },
				Band = starting.Band with { SystemValue = 0.4, MeasurementCount = 88 }
			},
			"soverom" => starting with
			{
				WarmingRate = starting.WarmingRate with { SystemValue = 0.9, MeasurementCount = 12 },
				Band = starting.Band with { SystemValue = 0.45, MeasurementCount = 40, ValueSetByAPerson = 0.6 }
			},
			_ => starting
		};
	}

	private static Stamped<double> Held(double value, DateTimeOffset when) =>
		new(value, Stamp.Certain(when), ChangeOrigin.SettingsPage);

	private static ProfileEntry Period(
		string id,
		BoundaryAnchor anchor,
		TimeSpan at,
		BoundaryMeaning meaning,
		double everywhere,
		DateTimeOffset when)
	{
		Dictionary<string, Stamped<double>> temperatures = new()
		{
			["stue"] = Held(everywhere, when),
			["soverom"] = Held(everywhere - 2, when),
			["tilbygg"] = Held(everywhere - 2, when),
			["toalett"] = Held(everywhere - 4, when)
		};

		return new ProfileEntry(id, anchor, at, meaning, temperatures);
	}
}
