namespace AdaptiveHeating.Planner;

/// <summary>Says what each option of a presence dropdown probably means, so a setup starts on the right answer.</summary>
/// <remarks>
///     Setup only. Nothing reading the dropdown consults a word: a read goes to <see cref="PresenceMap"/>, which
///     this fills once and a person corrects on the settings page. Matching text on every read would let a rename
///     in Home Assistant move a whole cabin between modes with nothing on any screen saying so.
/// </remarks>
public static class PresenceVocabulary
{
	/// <summary>The attribute a Home Assistant dropdown lists its own options under.</summary>
	public const string OptionsAttribute = "options";

	// Word for word the lighting engine's vocabulary, in its order, from AdaptiveLighting's HouseModeAutoDetect.
	// Four groups there, so four states here; the other states carry no word and are picked by hand. The two
	// copies are meant to stay identical, and a test asserts it.
	// Matched as a substring of the lower-cased option text. An unrecognised word classifies as everyday.
	private static readonly (PresenceState State, string[] Words)[] Groups =
	[
		(PresenceState.Night,    ["sleep", "sleeping", "asleep", "night", "sover", "sove", "natt", "senga"]),
		(PresenceState.Away,     ["away", "gone", "out", "empty", "borte", "ute", "reist"]),
		(PresenceState.Guest,    ["guest", "guests", "visitor", "visitors", "gjest", "gjester", "besok", "besøk"]),
		(PresenceState.Everyday, ["home", "normal", "default", "day", "hjemme", "dag", "vanlig"]),
	];

	/// <summary>Every word, with the state it classifies to, which is what a test reads.</summary>
	public static IReadOnlyList<(PresenceState State, string Word)> Words =>
		[.. Groups.SelectMany(group => group.Words.Select(word => (group.State, word)))];

	/// <summary>The state an option probably means. A word nothing matches is everyday.</summary>
	public static PresenceState Classify(string option)
	{
		ArgumentNullException.ThrowIfNull(option);

		string text = option.Trim().ToLowerInvariant();

		foreach ((PresenceState state, string[] words) in Groups)
		{
			if (words.Any(word => text.Contains(word, StringComparison.Ordinal)))
				return state;
		}

		return PresenceState.Everyday;
	}

	/// <summary>
	///     The mapping the dropdown's own options obviously want, or <c>null</c> where it is not obvious and a person
	///     maps them instead.
	/// </summary>
	/// <remarks>
	///     The lighting engine's bar, unchanged: an everyday option and at least two distinct states. A helper
	///     offering eco, comfort and boost classifies as three everydays, which says only that the words mean
	///     nothing here.
	/// </remarks>
	public static PresenceMap? Seed(IEnumerable<string>? options)
	{
		if (options is null)
			return null;

		List<PresenceOption> classified =
			[.. options
				.Where(option => !string.IsNullOrWhiteSpace(option))
				.Select(option => new PresenceOption(option.Trim(), Classify(option)))];

		if (classified.Count == 0)
			return null;

		bool hasEveryday = classified.Any(option => option.State == PresenceState.Everyday);
		int distinctStates = classified.Select(option => option.State).Distinct().Count();

		return hasEveryday && distinctStates >= 2 ? PresenceMap.Of(classified) : null;
	}
}
