using System.Globalization;

using AdaptiveHeating.Page;
using AdaptiveHeating.Page.Presentation;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

using Microsoft.AspNetCore.Localization;

using PageHost;

// A host for the Razor Class Library, so a change to the settings page can be rendered against the real
// stylesheet and photographed before it reaches a cabin.
//
// Run:  dotnet run --project addon/tools/pagehost                 ->  http://localhost:5299
//       dotnet run --project addon/tools/pagehost -- --port 5300  ->  a second worktree
//       dotnet run --project addon/tools/pagehost -- --port 0     ->  any free port, printed on startup

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

if (!TryResolvePort(builder.Configuration["port"], out int port))
{
	Console.Error.WriteLine("pagehost: --port takes a number from 0 to 65535.");

	return 1;
}

// Explicit, not left to the environment: static web assets are wired up automatically only in Development,
// and without them the library's _content/** and _framework/blazor.web.js both 404. The page then renders
// unstyled with no circuit, which reads as broken UI rather than a broken host.
builder.WebHost.UseStaticWebAssets();

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<ISettingsStore>(new InMemorySettingsStore(HouseSeed.Cabin()));

// No box under this host, so nothing watches the clock and every stamp reads as made with a good one.
builder.Services.AddSingleton<IStampSource>(new CertainStamps(TimeProvider.System));

// No Supervisor under this host either, so the household's clock is this machine's own and reads as resolved.
// A page rendered here therefore draws times in the zone whoever is looking at it is sitting in.
builder.Services.AddSingleton(TheHouseholdClock.Of(TimeZoneInfo.Local));

builder.Services.AddLocalization();

IReadOnlyList<CultureInfo> languages = PageLanguages.Available();

builder.Services.Configure<RequestLocalizationOptions>(options =>
{
	options.DefaultRequestCulture = new RequestCulture(PageLanguages.Fallback);
	options.SupportedCultures = [.. languages];
	options.SupportedUICultures = [.. languages];
});

builder.Services.AddAntiforgery(options => options.Cookie.Name = "adaptive-heating.antiforgery");
builder.Services.AddRazorComponents().AddInteractiveServerComponents();

WebApplication app = builder.Build();

app.UseRequestLocalization();
app.UseAntiforgery();
app.MapStaticAssets();
app.MapRazorComponents<HeatingApp>().AddInteractiveServerRenderMode();

// Read after start, not from the value above: with --port 0 only the server knows which port it got.
app.Lifetime.ApplicationStarted.Register(() =>
	Console.WriteLine($"pagehost listening on {string.Join(", ", app.Urls)}"));

// 127.0.0.1 only for port 0: Kestrel refuses a dynamic port on the "localhost" name, which resolves to both
// loopback families. A fixed port keeps the name.
app.Urls.Add(port == 0
	? "http://127.0.0.1:0"
	: $"http://localhost:{port.ToString(CultureInfo.InvariantCulture)}");

try
{
	app.Run();
}
catch (IOException error)
{
	Console.Error.WriteLine($"pagehost: could not bind port {port.ToString(CultureInfo.InvariantCulture)} — {error.Message}");
	Console.Error.WriteLine("pagehost: pass --port <number> for another one, or --port 0 for any free port.");

	return 1;
}

return 0;

// A port that is taken fails on bind rather than moving to a free one quietly: a host that lands somewhere
// unannounced points the next screenshot run at another worktree's page.
static bool TryResolvePort(string? requested, out int port)
{
	if (requested is not { Length: > 0 })
	{
		port = 5299;

		return true;
	}

	// Invariant, not the current culture: this is a machine-readable argument, and nb-NO digit grouping would
	// otherwise accept "5 299".
	return int.TryParse(requested, NumberStyles.None, CultureInfo.InvariantCulture, out port) && port <= 65535;
}
