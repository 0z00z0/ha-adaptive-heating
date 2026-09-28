using System.Globalization;

using Xunit;

namespace AdaptiveHeating.Planner.Tests;

/// <summary>
/// The words that pick the right option the first time. They run at setup and never on a read, so a word that
/// classifies wrongly costs one correction on the settings page rather than a cabin heated on nobody.
/// </summary>
public sealed class PresenceVocabularyTests
{
	/// <summary>
	/// The lighting engine's vocabulary, copied here as the value it must keep matching: the four groups of
	/// <c>HouseModeAutoDetect</c>, in its order, with its words. A difference between this table and
	/// <see cref="PresenceVocabulary"/> is a divergence between the two applications, not a test to adjust.
	/// </summary>
	private static readonly (PresenceState State, string[] Words)[] TheLightingEnginesWords =
	[
		(PresenceState.Night,    ["sleep", "sleeping", "asleep", "night", "sover", "sove", "natt", "senga"]),
		(PresenceState.Away,     ["away", "gone", "out", "empty", "borte", "ute", "reist"]),
		(PresenceState.Guest,    ["guest", "guests", "visitor", "visitors", "gjest", "gjester", "besok", "besøk"]),
		(PresenceState.Everyday, ["home", "normal", "default", "day", "hjemme", "dag", "vanlig"]),
	];

	public static TheoryData<string, PresenceState> EveryWord()
	{
		TheoryData<string, PresenceState> words = [];

		foreach ((PresenceState state, string[] group) in TheLightingEnginesWords)
		{
			foreach (string word in group)
				words.Add(word, state);
		}

		return words;
	}

	[Theory]
	[MemberData(nameof(EveryWord))]
	public void EveryWordReachesTheStateItBelongsTo(string word, PresenceState expected) =>
		Assert.Equal(expected, PresenceVocabulary.Classify(word));

	[Fact]
	public void TheVocabularyIsWordForWordTheLightingEngines()
	{
		List<(PresenceState State, string Word)> expected =
		[
			.. TheLightingEnginesWords.SelectMany(group => group.Words.Select(word => (group.State, word)))
		];

		IReadOnlyList<(PresenceState State, string Word)> held = PresenceVocabulary.Words;

		Assert.Equal(30, expected.Count);
		Assert.Equal(expected.Count, held.Count);
		Assert.Empty(expected.Except(held));
		Assert.Empty(held.Except(expected));
		Assert.Equal(expected, held);
	}

	[Theory]
	[InlineData("Borte", PresenceState.Away)]
	[InlineData("  natt  ", PresenceState.Night)]
	[InlineData("GJESTER", PresenceState.Guest)]
	[InlineData("Hjemme igjen", PresenceState.Everyday)]
	public void CaseAndSurroundingSpaceChangeNothing(string option, PresenceState expected) =>
		Assert.Equal(expected, PresenceVocabulary.Classify(option));

	/// <summary>Turkish uppercases i to a dotted I, so a run under that culture proves no culture reaches this.</summary>
	[Fact]
	public void TheWordsClassifyTheSameUnderACultureWhoseCasingRulesDiffer()
	{
		Exception? failed = null;

		Thread underTurkish = new(() =>
		{
			try
			{
				// Set inside the thread, and on a thread of its own, so no other test ever runs under this culture.
				CultureInfo.CurrentCulture = new CultureInfo("tr-TR");
				CultureInfo.CurrentUICulture = CultureInfo.CurrentCulture;

				Assert.Equal(PresenceState.Away, PresenceVocabulary.Classify("REIST"));
				Assert.Equal(PresenceState.Night, PresenceVocabulary.Classify("I SENGA"));
				Assert.Equal(PresenceState.Guest, PresenceVocabulary.Classify("BESØK"));
			}
			catch (Exception thrown)
			{
				failed = thrown;
			}
		});

		underTurkish.Start();
		underTurkish.Join();

		Assert.Null(failed);
	}

	/// <summary>The lean the lighting engine takes: a word nothing matches is the everyday one.</summary>
	[Fact]
	public void AWordNothingMatchesClassifiesAsEveryday() =>
		Assert.Equal(PresenceState.Everyday, PresenceVocabulary.Classify("Hjemmekontor"));

	[Fact]
	public void SeedingMapsEachOptionToWhatItsWordsSay()
	{
		PresenceMap seeded = Assert.IsType<PresenceMap>(PresenceVocabulary.Seed(["Hjemme", "Borte", "Natt", "Gjester"]));

		Assert.Equal(4, seeded.Count);
		Assert.Equal(PresenceState.Everyday, seeded.StateFor("Hjemme"));
		Assert.Equal(PresenceState.Away, seeded.StateFor("Borte"));
		Assert.Equal(PresenceState.Night, seeded.StateFor("Natt"));
		Assert.Equal(PresenceState.Guest, seeded.StateFor("Gjester"));
	}

	/// <summary>The lighting engine's bar: an everyday option, and at least two states between them.</summary>
	[Fact]
	public void OptionsThatSayNothingAreNotMapped()
	{
		// Three options classifying the same way say only that the words mean nothing on this helper.
		Assert.Null(PresenceVocabulary.Seed(["Eco", "Comfort", "Boost"]));
		Assert.Null(PresenceVocabulary.Seed(["Hjemme", "Vanlig", "Dag"]));

		// Two states but no everyday option, which is the same bar the lighting engine sets.
		Assert.Null(PresenceVocabulary.Seed(["Borte", "Natt"]));

		Assert.Null(PresenceVocabulary.Seed([]));
		Assert.Null(PresenceVocabulary.Seed(null));
	}
}
