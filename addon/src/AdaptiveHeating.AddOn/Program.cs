using System.Globalization;
using System.Reactive.Concurrency;
using System.Reflection;

using AdaptiveHeating.AddOn.Driving;
using AdaptiveHeating.AddOn.Ingress;
using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.AddOn.Logging;
using AdaptiveHeating.AddOn.Persistence;
using AdaptiveHeating.AddOn.Reporting;
using AdaptiveHeating.AddOn.Settings;
using AdaptiveHeating.Page;
using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Localization;

using NetDaemon.Client;
using NetDaemon.Client.Extensions;
using NetDaemon.Client.Settings;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

// What a person typed on the add-on's own configuration page. The Supervisor writes the form here, so the
// provider reads it like any other file, and it is added last so the form wins over what the image carries.
builder.Configuration.AddJsonFile(
	builder.Configuration["AdaptiveHeating:OptionsPath"] ?? TheOptionsForm.Path,
	optional: true,
	reloadOnChange: false);

// The one port Home Assistant's ingress reaches inside the container. The manifest names the same number and
// maps no port, so nothing outside the container can reach it.
int ingressPort = WayIn.PortFrom(builder.Configuration["AdaptiveHeating:IngressPort"]);

builder.WebHost.ConfigureKestrel(options => options.ListenAnyIP(ingressPort));

builder.Services.AddSingleton(new WayIn(ingressPort));
builder.Services.AddSingleton(TimeProvider.System);

// The key ring lives in the add-on's own persistent directory, not beside the binaries: an update replaces
// the image and everything in it, and a lost key ring logs every open page out with no way back.
string keyRing = builder.Configuration["AdaptiveHeating:KeyRingPath"] ?? "/data/keys";

Directory.CreateDirectory(keyRing);
builder.Services.AddDataProtection()
	.PersistKeysToFileSystem(new DirectoryInfo(keyRing))
	.SetApplicationName("adaptive-heating");

// The settings document and the notes beside it live in the add-on's own persistent directory, which is the
// one thing on the box an update does not replace.
string documentPath = builder.Configuration["AdaptiveHeating:DocumentPath"] ?? "/data/heating.json";

// The household's own clock: the one zone a boundary written as a wall time is decided on, and the one every
// time a person reads is shown in. Read once, here, and handed to everything that needs it. Above the logging
// call because the log is stamped with it, and a second read anywhere would put two clocks in one process.
TheHouseholdClock household = TheHouseholdClock.From(CoreApi.SupervisorZone(), TimeZoneInfo.Local);

builder.Services.AddSingleton(household);

// The durable copy of the log goes beside that document, because the Supervisor's own buffer holds only the
// newest lines and two restarts overwrite it. Before anything else is registered, so the first line is logged
// the same way as the last.
builder.UseIsoTimestampLogging(
	household,
	DurableLogFile.DirectoryBeside(documentPath),
	DurableLogFile.StemOf(documentPath, "adaptive-heating"));

// A stamp made before this build was written to disk cannot have been made against a clock set from the
// network, because the software did not exist then.
NetworkSetClock stamps = new(TimeProvider.System, NetworkSetClock.BuiltAt(Assembly.GetExecutingAssembly()));

builder.Services.AddSingleton(stamps);
builder.Services.AddSingleton<IStampSource>(stamps);

builder.Services.AddSingleton(services =>
	new StateStoreRegistry(
		documentPath,
		services.GetRequiredService<ILogger<StateStoreRegistry>>(),
		services.GetRequiredService<TimeProvider>()));

builder.Services.AddSingleton(services =>
{
	DurableSettingsStore durable = DurableSettingsStore.Open(
		services.GetRequiredService<StateStoreRegistry>(),
		services.GetRequiredService<TimeProvider>(),
		// Nothing has been heard from the integration and no file was found, so the page opens on no rooms
		// and says so rather than showing an empty table as though it were a finished one.
		HeatingDocument.NothingHeardYet(),
		services.GetRequiredService<ILogger<DurableSettingsStore>>());

	stamps.ClockWasSet += durable.WhenTheClockIsSet;

	return durable;
});

// The Supervisor proxies Home Assistant's websocket on the token in the add-on's environment. No user and no
// long-lived token exist anywhere. One connection for the life of the process, held by NetDaemon's own client,
// and everything the add-on asks of Home Assistant goes over it.
builder.Services.AddHomeAssistantClient();

// The client's HTTP half is never called, and it still reads these to build an address and a header at
// construction. Naming the Supervisor keeps it from pointing at a Home Assistant nobody asked for.
builder.Services.Configure<HomeAssistantSettings>(settings =>
{
	settings.Host = CoreConnection.SupervisorHost;
	settings.Port = CoreConnection.SupervisorPort;
	settings.Ssl = false;
	settings.WebsocketPath = CoreConnection.SupervisorWebsocketPath;
	settings.Token = CoreApi.SupervisorToken() ?? string.Empty;
});

// The boundary timer schedules on this. The rest of the add-on keeps its own clock, which is what a settings
// stamp and a warm-up deadline are measured against.
builder.Services.AddSingleton<IScheduler>(Scheduler.Default);

string? presenceHelper = TheOptionsForm.PresenceHelper(builder.Configuration);
OutdoorChoice outdoor = TheOptionsForm.Outdoor(builder.Configuration);

// What the heating reads beyond the climate entities and the sun. Built once: an entity nobody named is an
// entity whose changes never reach a pass over the rooms.
HashSet<string> alsoNamed = new(outdoor.Entities, StringComparer.Ordinal);

if (presenceHelper is { Length: > 0 } named)
	alsoNamed.Add(named);

builder.Services.AddSingleton(services =>
	new CoreConnection(
		services.GetRequiredService<IHomeAssistantRunner>(),
		CoreApi.SupervisorToken,
		alsoNamed,
		services.GetRequiredService<TimeProvider>(),
		services.GetRequiredService<ILogger<CoreConnection>>()));

builder.Services.AddHostedService(services => services.GetRequiredService<CoreConnection>());

// One instance for the life of the process, so an action reported as unknown is reported once across the
// whole add-on rather than once per caller.
builder.Services.AddSingleton(services =>
	new CoreApi(
		services.GetRequiredService<CoreConnection>(),
		services.GetRequiredService<ILogger<CoreApi>>()));

builder.Services.AddSingleton<Thermostats>();

// Reading a calendar and adding an entry to one. Home Assistant offers nothing else for a calendar, which is
// what makes the record durable.
builder.Services.AddSingleton<Calendars>();

// Which integration keeps each calendar, read from the entity registry once per connection and only where the
// house reports a calendar at all.
builder.Services.AddSingleton<TheCalendarsOnOffer>();

builder.Services.AddSingleton<TellsTheThermostats>(services =>
	new TellsTheThermostats(
		services.GetRequiredService<DurableSettingsStore>(),
		services.GetRequiredService<Thermostats>(),
		services.GetRequiredService<ILogger<TellsTheThermostats>>()));

builder.Services.AddSingleton<ISettingsStore>(services => services.GetRequiredService<TellsTheThermostats>());

// The activity record: bounded, and journalled into a file beside the settings so a restart does not lose what
// the add-on did. Declared in the registry the settings file already uses, so one flusher covers both.
builder.Services.AddSingleton(services =>
	new ActivityJournal(
		services.GetRequiredService<StateStoreRegistry>(),
		services.GetRequiredService<TimeProvider>(),
		services.GetRequiredService<ILogger<ActivityJournal>>()));

builder.Services.AddSingleton<IActivityJournal>(services => services.GetRequiredService<ActivityJournal>());

builder.Services.AddSingleton(services =>
	new ActivityRecord(services.GetRequiredService<IActivityJournal>()));

builder.Services.AddSingleton<ITellsAPerson>(services =>
	new TellsAPerson(
		services.GetRequiredService<CoreApi>(),
		services.GetRequiredService<ILogger<TellsAPerson>>()));

builder.Services.AddSingleton(services =>
	new ReportsWhatHappened(
		services.GetRequiredService<ActivityRecord>(),
		services.GetRequiredService<ITellsAPerson>(),
		// The record holds the room's id; what a person reads is looked up when the words are built, so a
		// rename shows at once and never splits one room's history in two.
		roomId => services.GetRequiredService<ISettingsStore>().Read().Rooms
			.FirstOrDefault(room => string.Equals(room.Id, roomId, StringComparison.Ordinal))?.Name ?? roomId,
		services.GetRequiredService<TheHouseholdClock>(),
		services.GetRequiredService<ILogger<ReportsWhatHappened>>()));

builder.Services.AddSingleton(services =>
	new TheArrivals(
		services.GetRequiredService<Calendars>(),
		services.GetRequiredService<ReportsWhatHappened>(),
		services.GetRequiredService<ILogger<TheArrivals>>()));

// The warm-ups asked for and not yet written down, in a file beside the settings: a warm-up cannot be seen
// finishing from outside, so what was asked for has to survive a restart or the entry is lost. Declared in the
// registry the settings file already uses, so one flusher and one start-up report cover all three.
builder.Services.AddSingleton(services =>
	new WarmUpNote(
		services.GetRequiredService<StateStoreRegistry>(),
		services.GetRequiredService<TimeProvider>(),
		services.GetRequiredService<ILogger<WarmUpNote>>()));

builder.Services.AddSingleton(services =>
	new RecordsTheWarmUps(
		services.GetRequiredService<WarmUpNote>(),
		services.GetRequiredService<Calendars>(),
		services.GetRequiredService<ReportsWhatHappened>(),
		// The row holds the room's id; what a person reads is looked up when the entry is written, so a rename
		// shows at once and never splits one room's record in two.
		roomId => services.GetRequiredService<ISettingsStore>().Read().Rooms
			.FirstOrDefault(room => string.Equals(room.Id, roomId, StringComparison.Ordinal))?.Name ?? roomId));

builder.Services.AddSingleton(services =>
	new DrivesTheRooms(
		services.GetRequiredService<ISettingsStore>(),
		services.GetRequiredService<Thermostats>(),
		PlannerDefaults.Standard,
		household,
		presenceHelper,
		outdoor,
		services.GetRequiredService<ReportsWhatHappened>(),
		services.GetRequiredService<TheArrivals>(),
		services.GetRequiredService<RecordsTheWarmUps>(),
		services.GetRequiredService<ILogger<DrivesTheRooms>>()));

builder.Services.AddHostedService<ConnectionToTheIntegration>();

builder.Services.AddLocalization();

// Home Assistant never tells the page which language a person chose, so the page picks from what the browser
// asks for and falls back to English. A language is added by dropping a resource file in, which builds into a
// satellite assembly PageLanguages finds on disk.
IReadOnlyList<CultureInfo> languages = PageLanguages.Available();

builder.Services.Configure<RequestLocalizationOptions>(options =>
{
	options.DefaultRequestCulture = new RequestCulture(PageLanguages.Fallback);
	options.SupportedCultures = [.. languages];
	options.SupportedUICultures = [.. languages];
	options.ApplyCurrentCultureToResponseHeaders = true;
});

builder.Services.AddAuthentication(IngressIdentity.Scheme)
	.AddScheme<AuthenticationSchemeOptions, IngressAuthenticationHandler>(IngressIdentity.Scheme, configureOptions: null);

builder.Services.AddAuthorization();

// Named after the page rather than taking the framework's default: cookies are not scoped by port, so two
// applications on one host holding the default name overwrite each other's.
builder.Services.AddAntiforgery(options => options.Cookie.Name = "adaptive-heating.antiforgery");

builder.Services.AddRazorComponents().AddInteractiveServerComponents();

WebApplication app = builder.Build();

// Reading the settings is what opens the file, so it happens before the report rather than on the first
// request. Without the report a person cannot tell a restored setting from a fresh one after a deploy.
_ = app.Services.GetRequiredService<ISettingsStore>();

// Reading the record is what opens the journal, and it happens before the report for the same reason.
_ = app.Services.GetRequiredService<ActivityRecord>();

// The warm-ups awaiting the record open their own file the same way, so the report names all three.
_ = app.Services.GetRequiredService<RecordsTheWarmUps>();

app.Services.GetRequiredService<StateStoreRegistry>().ReportRestored();

// The first line of the run, in the record and in the log. No card: nothing here needs a person.
await app.Services
	.GetRequiredService<ReportsWhatHappened>()
	.ReportAsync(
		HeatingReport.About(WhatHappened.Started, app.Services.GetRequiredService<TimeProvider>().GetUtcNow()) with
		{
			Named = HalfVersions.AddOnVersion
		},
		CancellationToken.None)
	.ConfigureAwait(false);

app.UseRequestLocalization();

// No path-base middleware anywhere: Home Assistant strips its prefix before the request arrives, so every
// route matches as though the page sat at the root of its own address. Stripping it again would strip a
// prefix that has already gone.
app.UseAuthentication();
app.UseAuthorization();
app.UseAntiforgery();

app.MapStaticAssets();
app.MapRazorComponents<HeatingApp>().AddInteractiveServerRenderMode();

app.Run();
