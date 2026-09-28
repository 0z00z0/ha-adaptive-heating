using AdaptiveHeating.AddOn.Integration;
using AdaptiveHeating.Page.Settings;
using AdaptiveHeating.Planner;

namespace AdaptiveHeating.AddOn.Driving;

/// <summary>The one place a presence word is read, and it runs only while nothing is mapped.</summary>
/// <remarks>
///     What the dropdown's own options mean is worked out once, from the words in them, and stored. Every read
///     afterwards is a lookup in that mapping, so renaming an option in Home Assistant re-points one row instead
///     of moving a whole cabin between modes.
/// </remarks>
internal static class SetsUpThePresenceMap
{
	/// <summary>
	///     Maps the dropdown's options where nothing is mapped yet, and answers whether it wrote one.
	/// </summary>
	/// <remarks>
	///     Silent where the helper is absent, lists no options, or offers words the vocabulary cannot tell apart:
	///     a mapping guessed from words that mean nothing here would pause or heat a cabin on no evidence, and an
	///     unmapped value at least reports itself.
	/// </remarks>
	/// <summary>The options the dropdown lists, or none where it lists nothing and where no helper is named.</summary>
	/// <remarks>The one place the attribute is read, so the page and the setup cannot come to different lists.</remarks>
	public static IReadOnlyList<string> OptionsOf(EntityState? dropdown) =>
		dropdown?.Attributes is { } attributes
			? Attributes.TextList(attributes, PresenceVocabulary.OptionsAttribute)
			: [];

	public static bool FromTheOptionsItOffers(ISettingsStore store, EntityState? dropdown, ILogger logger)
	{
		ArgumentNullException.ThrowIfNull(store);
		ArgumentNullException.ThrowIfNull(logger);

		if (!store.Read().Presence.IsEmpty)
			return false;

		if (dropdown is null)
			return false;

		IReadOnlyList<string> options = OptionsOf(dropdown);

		if (PresenceVocabulary.Seed(options) is not { } seeded)
			return false;

		SaveOutcome outcome = store.SavePresenceMap(seeded);

		if (!outcome.Written)
		{
			logger.LogWarning(
				"The presence dropdown {Entity} could not be mapped: {Why} Map its options on the settings page.",
				dropdown.EntityId, outcome.Message);

			return false;
		}

		logger.LogInformation(
			"Mapped {Count} option(s) of {Entity} from the words in them ({Mapping}). Nothing reads a word again; "
			+ "correct any of it on the settings page.",
			seeded.Count,
			dropdown.EntityId,
			string.Join(", ", (seeded.Options ?? []).Select(option => $"{option.Value}={option.State}")));

		return true;
	}
}
