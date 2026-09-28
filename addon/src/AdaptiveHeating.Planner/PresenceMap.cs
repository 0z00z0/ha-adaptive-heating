namespace AdaptiveHeating.Planner;

/// <summary>One option of the presence dropdown, and the state it stands for.</summary>
/// <param name="Value">
///     The option text exactly as Home Assistant reports it. Matched trimmed and case-insensitively, and free to
///     change: it belongs to whoever edits the helper.
/// </param>
/// <param name="State">The state the option means, named by identifier so no rename of the text can move it.</param>
public sealed record PresenceOption(string Value, PresenceState State);

/// <summary>Every option the presence dropdown offers, and the state each one stands for.</summary>
/// <remarks>
///     The one thing a read of the dropdown consults. Word recognition fills this once at setup and is never asked
///     again, so the state a room runs under hangs on a row and not on the words in a helper.
/// </remarks>
public sealed record PresenceMap
{
	/// <summary>Nothing mapped, which is what a cabin starts on and what an unreadable dropdown leaves behind.</summary>
	public static PresenceMap Empty { get; } = new();

	/// <summary>One row per dropdown option, in the order the settings page draws them.</summary>
	public IReadOnlyList<PresenceOption>? Options { get; init; } = [];

	/// <summary>Whether nothing is mapped, so every value read falls through and reports itself.</summary>
	public bool IsEmpty => Rows.Count == 0;

	/// <summary>How many options are mapped, which is what the settings page states.</summary>
	public int Count => Rows.Count;

	// A settings file may carry an explicit null here, and every reader below would then throw on a pass over
	// the rooms.
	private IReadOnlyList<PresenceOption> Rows => Options ?? [];

	/// <summary>Builds a map over <paramref name="options"/>, dropping any row with no option text.</summary>
	public static PresenceMap Of(IEnumerable<PresenceOption> options)
	{
		ArgumentNullException.ThrowIfNull(options);

		return new PresenceMap
		{
			Options = [.. options.Where(option => !string.IsNullOrWhiteSpace(option.Value))]
		};
	}

	/// <summary>The state <paramref name="value"/> stands for, or <c>null</c> where no row names it.</summary>
	/// <remarks>First row wins on a duplicate, as every other lookup over this document does.</remarks>
	public PresenceState? StateFor(string? value)
	{
		if (value is not { Length: > 0 })
			return null;

		// Trimmed once, outside the loop: this runs on every pass over the rooms.
		string wanted = value.Trim();

		foreach (PresenceOption option in Rows)
		{
			if (string.Equals(option.Value?.Trim(), wanted, StringComparison.OrdinalIgnoreCase))
				return option.State;
		}

		return null;
	}

	/// <summary>The option text standing for <paramref name="state"/>, or <c>null</c> where no row carries it.</summary>
	public string? ValueFor(PresenceState state)
	{
		foreach (PresenceOption option in Rows)
		{
			if (option.State == state && option.Value?.Trim() is { Length: > 0 } text)
				return text;
		}

		return null;
	}

	/// <summary>The same map with one row's option text replaced, which is what a rename in Home Assistant takes.</summary>
	/// <remarks>The state each row stands for is untouched, so a rename costs the text and nothing else.</remarks>
	public PresenceMap Renamed(string was, string now)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(was);
		ArgumentException.ThrowIfNullOrWhiteSpace(now);

		return new PresenceMap
		{
			Options =
			[
				.. Rows.Select(option =>
					string.Equals(option.Value?.Trim(), was.Trim(), StringComparison.OrdinalIgnoreCase)
						? option with { Value = now.Trim() }
						: option)
			]
		};
	}
}
