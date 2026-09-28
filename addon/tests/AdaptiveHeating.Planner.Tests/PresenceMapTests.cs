using Xunit;

namespace AdaptiveHeating.Planner.Tests;

/// <summary>
/// What a dropdown value means is the row stored for it, never the words in it. Renaming an option in Home
/// Assistant therefore costs that row's text; under text matching it moved a whole cabin between modes with
/// nothing on any screen saying so.
/// </summary>
public sealed class PresenceMapTests
{
	private static readonly PresenceMap ACabinsOptions = PresenceMap.Of(
	[
		new PresenceOption("Hjemme", PresenceState.Everyday),
		new PresenceOption("Borte", PresenceState.Away),
		new PresenceOption("Natt", PresenceState.Night),
	]);

	[Fact]
	public void RenamingAnOptionLeavesTheStateItStandsFor()
	{
		Assert.Equal(PresenceState.Away, ACabinsOptions.StateFor("Borte"));

		// The words would call this one everyday, because "hjemme" is in them. The row says away, and the row wins.
		PresenceMap renamed = ACabinsOptions.Renamed("Borte", "Ikke hjemme");

		Assert.Equal(PresenceState.Away, renamed.StateFor("Ikke hjemme"));
		Assert.Equal(HeatingMode.Away, Presence.ModeFor(renamed.StateFor("Ikke hjemme")!.Value));
		Assert.True(Presence.ReadsAsAnEmptyCabin(renamed.StateFor("Ikke hjemme")!.Value));

		// The control, so the test above cannot pass for the wrong reason: matching the text is what breaks.
		Assert.Equal(PresenceState.Everyday, PresenceVocabulary.Classify("Ikke hjemme"));

		Assert.Equal(ACabinsOptions.Count, renamed.Count);
		Assert.Null(renamed.StateFor("Borte"));
	}

	[Fact]
	public void ARowBeatsWhatTheWordsWouldSay()
	{
		PresenceMap mapped = PresenceMap.Of([new PresenceOption("Hjemmekontor", PresenceState.Away)]);

		Assert.Equal(PresenceState.Everyday, PresenceVocabulary.Classify("Hjemmekontor"));
		Assert.Equal(PresenceState.Away, Presence.Read(mapped, "Hjemmekontor")!.Value.State);
		Assert.True(Presence.Read(mapped, "Hjemmekontor")!.Value.Recognised);
	}

	/// <summary>The ordinals a settings file's numbers would mean. Moving one re-points every row that carried it.</summary>
	[Fact]
	public void TheStatesOrdinalsArePinned()
	{
		Assert.Equal(0, (int)PresenceState.NoEvidence);
		Assert.Equal(1, (int)PresenceState.Away);
		Assert.Equal(2, (int)PresenceState.Everyday);
		Assert.Equal(3, (int)PresenceState.Night);
		Assert.Equal(4, (int)PresenceState.Guest);
		Assert.Equal(5, (int)PresenceState.PlannedToArrive);
		Assert.Equal(6, (int)PresenceState.OnTheWay);
		Assert.Equal(7, (int)PresenceState.TemporarilyAway);
	}

	[Theory]
	[InlineData("borte")]
	[InlineData("BORTE")]
	[InlineData("  Borte  ")]
	public void CaseAndSurroundingSpaceChangeNothing(string value) =>
		Assert.Equal(PresenceState.Away, ACabinsOptions.StateFor(value));

	[Fact]
	public void TheFirstRowWinsWhereTwoNameOneOption()
	{
		PresenceMap twice = PresenceMap.Of(
		[
			new PresenceOption("Borte", PresenceState.Away),
			new PresenceOption("Borte", PresenceState.Guest),
		]);

		Assert.Equal(PresenceState.Away, twice.StateFor("Borte"));
	}

	[Fact]
	public void AValueNoRowNamesHoldsTheComfortModeAndSaysItWasNotRecognised()
	{
		PresenceReading read = Presence.Read(ACabinsOptions, "Hjemmekontor")!.Value;

		Assert.False(read.Recognised);

		// The fall-through the owner chose to keep: a cabin with people in it must not go cold on an option
		// nobody has mapped. The mode is the expensive one, and the reporting is what makes that visible.
		Assert.Equal(PresenceState.Everyday, read.State);
		Assert.Equal(HeatingMode.Home, Presence.ModeFor(read.State));
		Assert.False(Presence.ReadsAsAnEmptyCabin(read.State));
	}

	[Fact]
	public void NothingMappedReadsEveryValueAsUnrecognised()
	{
		PresenceReading read = Presence.Read(PresenceMap.Empty, "Borte")!.Value;

		Assert.False(read.Recognised);
		Assert.Equal(PresenceState.Everyday, read.State);
	}

	[Fact]
	public void AnUnavailableOrEmptyValueHoldsWhateverWasLastSeen()
	{
		Assert.Null(Presence.Read(ACabinsOptions, null));
		Assert.Null(Presence.Read(ACabinsOptions, ""));
		Assert.Null(Presence.Read(ACabinsOptions, "unknown"));
		Assert.Null(Presence.Read(ACabinsOptions, "unavailable"));
	}
}
