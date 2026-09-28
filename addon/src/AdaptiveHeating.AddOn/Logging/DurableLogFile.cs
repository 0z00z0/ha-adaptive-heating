using Serilog;

namespace AdaptiveHeating.AddOn.Logging;

/// <summary>The durable copy of the log: one file a day, pruned by age and by count, where an update does not reach.</summary>
/// <remarks>
///     Taken from the lighting engine's <c>DurableLogFile</c>, read on 2026-09-25. What did not come with it is the
///     removal of an undated pair an earlier version of that package wrote: no version of this add-on ever wrote one.
///     <para>
///         The Supervisor's own buffer holds only the newest lines and two restarts overwrite it, so the lines are
///         also kept beside the settings document. <see cref="RetainedFileTime"/> is what a reader gets;
///         <see cref="RetainedFileCount"/> times <see cref="MaxFileBytes"/> caps the disk.
///     </para>
/// </remarks>
internal static class DurableLogFile
{
	/// <summary>The subdirectory the log lives in, beside the document instead of on top of it.</summary>
	public const string FolderName = "log";

	/// <summary>What one day's file may reach before the day rolls early.</summary>
	public const long MaxFileBytes = 4L * 1024 * 1024;

	/// <summary>How many files are kept, so the directory has a ceiling however noisy the cabin is.</summary>
	public const int RetainedFileCount = 15;

	private const string Extension = ".log";

	// Serilog inserts the date between the stem and the extension, so the separator has to be part of the stem.
	private const string DatePrefix = "-";

	/// <summary>How far back a reader can look in the ordinary case, which a byte budget alone cannot promise.</summary>
	public static readonly TimeSpan RetainedFileTime = TimeSpan.FromDays(14);

	/// <summary>The log directory beside a settings document, or <c>null</c> where the path names no directory.</summary>
	public static string? DirectoryBeside(string? documentPath) =>
		documentPath is { Length: > 0 } && Path.GetDirectoryName(Path.GetFullPath(documentPath)) is { Length: > 0 } directory
			? Path.Combine(directory, FolderName)
			: null;

	/// <summary>The document's file stem, so two documents in one directory cannot collide.</summary>
	public static string StemOf(string? documentPath, string fallback)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(fallback);

		if (documentPath is not { Length: > 0 })
			return fallback;

		string stem = Path.GetFileNameWithoutExtension(documentPath);

		return stem.Length > 0 ? stem : fallback;
	}

	/// <summary>The path Serilog rolls, which is never itself written: a date goes in before the extension.</summary>
	public static string PathTemplate(string directory, string stem)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(directory);
		ArgumentException.ThrowIfNullOrWhiteSpace(stem);

		return Path.Combine(directory, stem + DatePrefix + Extension);
	}

	/// <summary>Attaches the durable copy to a logger being built.</summary>
	/// <param name="logger">The configuration the console sink is already on; a second one would replace it.</param>
	/// <param name="directory">Where the files go, normally <see cref="FolderName"/> beside the document.</param>
	/// <param name="stem">The document's stem.</param>
	/// <param name="maxFileBytes">Overrides <see cref="MaxFileBytes"/>, for tests.</param>
	/// <param name="retainedFileCount">Overrides <see cref="RetainedFileCount"/>, for tests.</param>
	public static LoggerConfiguration AddTo(
		LoggerConfiguration logger,
		string directory,
		string stem,
		long maxFileBytes = MaxFileBytes,
		int retainedFileCount = RetainedFileCount)
	{
		ArgumentNullException.ThrowIfNull(logger);
		ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maxFileBytes);
		ArgumentOutOfRangeException.ThrowIfNegativeOrZero(retainedFileCount);

		// Rolling daily is what makes retention answer in days; rolling on size as well is what keeps the ceiling
		// true on a day that misbehaves. Dropping either leaves one of the two bounds unenforced.
		return logger.WriteTo.File(
			new DurableLogFormatter(),
			PathTemplate(directory, stem),
			fileSizeLimitBytes: maxFileBytes,
			rollingInterval: RollingInterval.Day,
			rollOnFileSizeLimit: true,
			retainedFileCountLimit: retainedFileCount,
			retainedFileTimeLimit: RetainedFileTime);
	}
}
