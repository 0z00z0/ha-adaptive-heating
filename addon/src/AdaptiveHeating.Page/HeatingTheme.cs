namespace AdaptiveHeating.Page;

/// <summary>One entry in the theme picker.</summary>
/// <param name="Id">
///     The stored id. Held in the browser and carried as <c>data-theme</c>, so renaming one drops every
///     browser that had chosen it: add themes, never rename them.
/// </param>
/// <param name="NameKey">The resource key holding what the picker calls it.</param>
/// <param name="IsDark">Which group the picker lists it under. Meaningless for <see cref="HeatingThemes.System"/>.</param>
public sealed record HeatingTheme(string Id, string NameKey, bool IsDark);

/// <summary>The two palettes and the device-following default.</summary>
/// <remarks>Heating has one design, so it has one dark palette and one light one. Each is defined once in the
/// stylesheet; a colour written in two places is the defect that reached a live house.</remarks>
public static class HeatingThemes
{
	/// <summary>The default. Resolves to <see cref="DarkDefault"/> or <see cref="LightDefault"/> in the browser.</summary>
	public static readonly HeatingTheme System = new("system", "ThemeFollowsDevice", false);

	public static readonly HeatingTheme Dark = new("dark", "ThemeDark", true);

	public static readonly HeatingTheme Light = new("light", "ThemeLight", false);

	/// <summary>Every theme, in picker order.</summary>
	public static IReadOnlyList<HeatingTheme> All { get; } = [System, Dark, Light];

	/// <summary>What a dark device with nothing stored gets.</summary>
	public static HeatingTheme DarkDefault => Dark;

	/// <summary>What a light device with nothing stored gets.</summary>
	public static HeatingTheme LightDefault => Light;

	/// <summary>The <c>data-theme</c> values, space-separated, for the head script's allow-list. Excludes
	/// <see cref="System"/>, which paints as an absence of a stored choice rather than a value of its own.</summary>
	public static string DataThemeIds { get; } =
		string.Join(' ', All.Where(theme => theme != System).Select(theme => theme.Id));

	/// <summary>The theme a stored id names, or <see cref="System"/> when it names nothing this build ships.</summary>
	public static HeatingTheme Resolve(string? storedId) =>
		// Ordinal: these are storage keys, not words, and a Turkish locale lower-casing an I would break the match.
		All.FirstOrDefault(theme => string.Equals(theme.Id, storedId, StringComparison.Ordinal)) ?? System;
}
