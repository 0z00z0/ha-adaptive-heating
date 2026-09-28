using System.Reactive.Linq;
using System.Reactive.Threading.Tasks;
using System.Text.Json;
using System.Text.Json.Serialization;

using NetDaemon.Client;
using NetDaemon.Client.HomeAssistant.Extensions;
using NetDaemon.Client.HomeAssistant.Model;
using NetDaemon.Client.Internal.HomeAssistant.Commands;

namespace AdaptiveHeating.AddOn.Integration;

/// <summary>
/// What Home Assistant said about one message: whether it went through, and its own code and sentence where it
/// did not.
/// </summary>
internal sealed record ReplyFromTheCore(bool Succeeded, string? Code, string? Said)
{
	/// <summary>The connection was not usable, so nothing was sent. Not one of Home Assistant's codes.</summary>
	public const string NoConnection = "no_connection";

	/// <summary>The message went out and nothing came back in time. Not one of Home Assistant's codes.</summary>
	public const string NoAnswer = "no_answer";

	/// <summary>What Home Assistant answered with, where the message asked for an answer rather than only an outcome.</summary>
	public JsonElement? Result { get; init; }
}

/// <summary>The codes Home Assistant answers a call with, as its own websocket component defines them.</summary>
/// <remarks>Read from <c>websocket_api/const.py</c> and <c>commands.py</c> at 2026.9.1, the version the cabin runs.</remarks>
internal static class HomeAssistantErrors
{
	/// <summary>Nobody registered that action. The integration is older than the add-on, or it failed to load.</summary>
	public const string NotFound = "not_found";

	/// <summary>The thermostat refused, and the sentence says why. An answer, not a fault.</summary>
	public const string ServiceValidation = "service_validation_error";
}

/// <summary>
/// The one connection to Home Assistant, held by NetDaemon's own client for as long as the add-on runs.
/// Everything the add-on asks of Home Assistant goes over it, and everything Home Assistant reports arrives on
/// it.
/// </summary>
/// <remarks>
///     The handshake, the reconnection, the numbering of messages and the subscription are the client's.
///     What stays here is the action call, because the client's own call reports no reason a call failed, and
///     the table of what the house holds, because the client's entity model would fetch five registries the
///     heating has no use for.
/// </remarks>
internal sealed class CoreConnection : BackgroundService
{
	/// <summary>Where the Supervisor proxies Home Assistant's websocket. The token goes in the handshake.</summary>
	public const string SupervisorHost = "supervisor";

	public const int SupervisorPort = 80;

	public const string SupervisorWebsocketPath = "core/websocket";

	/// <summary>How long a message waits for its answer before giving up on it.</summary>
	public static readonly TimeSpan WaitForAnAnswer = TimeSpan.FromSeconds(20);

	/// <summary>
	/// How long before the connection is tried again. The client doubles it to a ceiling of its own while it is
	/// running; this is also the wait before the client itself is started afresh.
	/// </summary>
	public static readonly TimeSpan WaitBeforeTryingAgain = TimeSpan.FromSeconds(5);

	/// <summary>The registry read that says which integration created each entity, which is how a calendar's is known.</summary>
	/// <remarks>The display form rather than the full one: it carries the entity id and the platform under two-letter
	/// names and leaves out disabled entities, which is the whole of what is read from it.</remarks>
	public const string EntityRegistryCommand = "config/entity_registry/list_for_display";

	private const string StateChanged = "state_changed";
	private const string Result = "result";

	private static readonly ReplyFromTheCore Down =
		new(false, ReplyFromTheCore.NoConnection, "The connection to Home Assistant is not open.");

	private readonly IHomeAssistantRunner _runner;
	private readonly Func<string?> _token;
	private readonly IReadOnlyCollection<string> _alsoNamed;
	private readonly TimeProvider _time;
	private readonly ILogger<CoreConnection> _logger;
	private readonly EntitiesNow _house = new();

	private volatile IHomeAssistantConnection? _live;
	private IDisposable? _watching;
	private int _opened;

	/// <param name="alsoNamed">
	///     The entities the add-on's own configuration points at, beyond the climate entities and the sun: the
	///     presence helper, the chosen outdoor sensors and the forecast.
	/// </param>
	public CoreConnection(
		IHomeAssistantRunner runner,
		Func<string?> token,
		IReadOnlyCollection<string> alsoNamed,
		TimeProvider time,
		ILogger<CoreConnection> logger)
	{
		_runner = runner ?? throw new ArgumentNullException(nameof(runner));
		_token = token ?? throw new ArgumentNullException(nameof(token));
		_alsoNamed = alsoNamed ?? throw new ArgumentNullException(nameof(alsoNamed));
		_time = time ?? throw new ArgumentNullException(nameof(time));
		_logger = logger ?? throw new ArgumentNullException(nameof(logger));
	}

	/// <summary>Raised when an entity the heating reads has changed, and when a fresh connection has read the house.</summary>
	public event Action? SomethingChanged;

	/// <summary>
	/// Whether a message sent now would reach Home Assistant. False until the client has a connection Home
	/// Assistant confirmed is running, the subscription is in place and the house has been read.
	/// </summary>
	public bool IsOpen => _live is not null;

	/// <summary>How many connections have been opened and read the house, counted from the add-on starting.</summary>
	/// <remarks>
	///     A reader comparing this against the number it last saw finds a connection that went and came back
	///     between two of its own passes, which watching <see cref="IsOpen"/> for a transition does not.
	/// </remarks>
	public int TimesOpened => Volatile.Read(ref _opened);

	/// <summary>Every entity the heating reads, as the last thing heard from Home Assistant left it.</summary>
	public IReadOnlyList<EntityState> House => _house.Snapshot();

	/// <summary>
	/// Calls one action and waits for Home Assistant's own answer. A call made while the connection is down is
	/// lost, not queued: it answers at once saying so, and the caller carries on.
	/// </summary>
	/// <param name="entityId">The entity it is called against, or <c>null</c> for an action that takes no target.</param>
	public Task<ReplyFromTheCore> CallAsync(
		string domain,
		string action,
		string? entityId,
		IReadOnlyDictionary<string, object?> fields,
		CancellationToken token) =>
		CallAsync(domain, action, entityId, fields, wantsAnAnswer: false, token);

	/// <summary>
	/// Calls one action, asking Home Assistant to carry its answer back where <paramref name="wantsAnAnswer"/> is
	/// set. An action that only answers refuses a call made without it.
	/// </summary>
	public Task<ReplyFromTheCore> CallAsync(
		string domain,
		string action,
		string? entityId,
		IReadOnlyDictionary<string, object?> fields,
		bool wantsAnAnswer,
		CancellationToken token) =>
		SendAndWaitAsync(
			new CallAnAction
			{
				Domain = domain,
				Service = action,
				Fields = fields,

				// Home Assistant refuses a target naming no entity, so raising a notification sends none at all.
				Target = entityId is { Length: > 0 } named ? new HassTarget { EntityIds = [named] } : null,
				ReturnResponse = wantsAnAnswer ? true : null
			},
			token);

	/// <summary>Sends one command that is not an action call, and waits for Home Assistant's own answer.</summary>
	public Task<ReplyFromTheCore> AskAsync(string command, CancellationToken token)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(command);

		return SendAndWaitAsync(new AskTheCore(command), token);
	}

	private async Task<ReplyFromTheCore> SendAndWaitAsync<TCommand>(TCommand call, CancellationToken token)
		where TCommand : CommandMessage
	{
		// The raw message stream is the only place the code and the sentence survive: the client's own helper
		// that returns a result throws with the error folded into a sentence of its own.
		if (_live is not IHomeAssistantConnection live || live is not IHomeAssistantHassMessages messages)
			return Down;

		// Subscribed before the message goes out, because the answer can arrive before the send returns. Until
		// the send assigns a number the filter matches nothing: Home Assistant never answers with number zero.
		CancellationTokenSource waiting = CancellationTokenSource.CreateLinkedTokenSource(token);

		try
		{
			Task<HassMessage> answer = messages.OnHassMessage
				.Where(one => one.Id == call.Id && string.Equals(one.Type, Result, StringComparison.Ordinal))
				.FirstAsync()
				.ToTask(waiting.Token);

			try
			{
				await live.SendCommandAsync(call, token).ConfigureAwait(false);
			}
			catch (Exception failure) when (failure is not OperationCanceledException)
			{
				return new ReplyFromTheCore(false, ReplyFromTheCore.NoConnection, failure.Message);
			}

			try
			{
				return Answered(await answer.WaitAsync(WaitForAnAnswer, _time, token).ConfigureAwait(false));
			}
			catch (TimeoutException)
			{
				return new ReplyFromTheCore(false, ReplyFromTheCore.NoAnswer, "Home Assistant did not answer.");
			}
			catch (InvalidOperationException)
			{
				// The stream ended with nothing on it, which is the connection closing under the call. Every
				// restart would otherwise leave the room waiting out the twenty seconds.
				return Down;
			}
		}
		finally
		{
			await waiting.CancelAsync().ConfigureAwait(false);
			waiting.Dispose();
		}
	}

	/// <inheritdoc/>
	protected override async Task ExecuteAsync(CancellationToken stoppingToken)
	{
		// The client raises this on its own loop, so the work goes to a task of its own. A handler that waits on
		// Home Assistant would hold up the connection it was told about.
		using IDisposable opening = _runner.OnConnect.Subscribe(connection => _ = StartUsingAsync(connection, stoppingToken));
		using IDisposable closing = _runner.OnDisconnect.Subscribe(WhenItGoes);

		while (!stoppingToken.IsCancellationRequested)
		{
			try
			{
				await _runner.RunAsync(
					SupervisorHost,
					SupervisorPort,
					ssl: false,
					_token() ?? string.Empty,
					SupervisorWebsocketPath,
					WaitBeforeTryingAgain,
					stoppingToken).ConfigureAwait(false);
			}
			catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
			{
				return;
			}
			catch (Exception failure)
			{
				_logger.LogDebug(failure, "The connection to Home Assistant did not hold.");
			}

			if (stoppingToken.IsCancellationRequested)
				return;

			// The client stops retrying for good on a token Home Assistant will not take. The Supervisor rotates
			// the add-on's token, so the token is read afresh and the client started again.
			_logger.LogInformation(
				"The connection to Home Assistant stopped. Starting it again in {Seconds} second(s); the heating carries on meanwhile.",
				WaitBeforeTryingAgain.TotalSeconds);

			try
			{
				await Task.Delay(WaitBeforeTryingAgain, _time, stoppingToken).ConfigureAwait(false);
			}
			catch (OperationCanceledException)
			{
				return;
			}
		}
	}

	/// <inheritdoc/>
	public override void Dispose()
	{
		base.Dispose();

		_watching?.Dispose();
		_watching = null;
	}

	// Subscribed before the house is read. A change arriving between the two is held, so the read cannot put an
	// older value back over it. The house is read once per connection and never again.
	private async Task StartUsingAsync(IHomeAssistantConnection connection, CancellationToken token)
	{
		try
		{
			// Every event in the house arrives whatever type is asked for, a measured defect in the client at
			// 26.36.0. Naming one opens a second subscription carrying the same traffic, so nothing is named and
			// the filter is this side's.
			IObservable<HassEvent> events = await connection
				.SubscribeToHomeAssistantEventsAsync(eventType: null, token)
				.ConfigureAwait(false);

			_house.Reading();

			_watching?.Dispose();
			_watching = events
				.Where(one => string.Equals(one.EventType, StateChanged, StringComparison.Ordinal))
				.Subscribe(WhenAnEntityChanges, _ => { }, () => { });

			IReadOnlyCollection<HassState> states =
				await connection.GetStatesAsync(token).ConfigureAwait(false) ?? [];

			int kept = _house.Read(states, _alsoNamed);

			_live = connection;

			Interlocked.Increment(ref _opened);

			_logger.LogInformation(
				"The connection to Home Assistant is open. {Kept} of {Read} entities are ones the heating reads.",
				kept,
				states.Count);

			SomethingChanged?.Invoke();
		}
		catch (OperationCanceledException)
		{
			StopUsingIt();
		}
		catch (Exception failure)
		{
			StopUsingIt();
			_logger.LogWarning(failure, "The connection to Home Assistant opened and then could not be used.");
		}
	}

	// Nothing arrives once the watch is let go, so no change is held against a read that is never coming.
	private void StopUsingIt()
	{
		_live = null;
		_watching?.Dispose();
		_watching = null;
	}

	private void WhenItGoes(DisconnectReason reason)
	{
		StopUsingIt();

		_logger.LogInformation(
			"The connection to Home Assistant is down ({Reason}); the heating carries on with what it last heard.",
			reason);
	}

	private void WhenAnEntityChanges(HassEvent arrived)
	{
		if (arrived.DataElement?.Deserialize<HassStateChangedEventData>() is not { } changed
			|| changed.EntityId is not { Length: > 0 } entityId
			|| !WhatTheHeatingReads.Reads(entityId, _alsoNamed))
			return;

		_house.Record(entityId, changed.NewState);

		SomethingChanged?.Invoke();
	}

	private static ReplyFromTheCore Answered(HassMessage reply) =>
		reply.Success == true
			? new ReplyFromTheCore(true, null, null) { Result = reply.ResultElement }
			: new ReplyFromTheCore(false, reply.Error?.Code?.ToString(), reply.Error?.Message);

	/// <summary>One call to one action. The client's own command is internal, so the message is declared here.</summary>
	private sealed record CallAnAction : CommandMessage
	{
		public CallAnAction() => Type = "call_service";

		[JsonPropertyName("domain")]
		public string Domain { get; init; } = string.Empty;

		[JsonPropertyName("service")]
		public string Service { get; init; } = string.Empty;

		[JsonPropertyName("service_data")]
		public IReadOnlyDictionary<string, object?>? Fields { get; init; }

		[JsonPropertyName("target")]
		public HassTarget? Target { get; init; }

		/// <summary>Left out entirely rather than sent as false, because an action that does not answer refuses it.</summary>
		[JsonPropertyName("return_response")]
		public bool? ReturnResponse { get; init; }
	}

	/// <summary>One command carrying nothing but its own type, which is the shape of every registry read.</summary>
	private sealed record AskTheCore : CommandMessage
	{
		public AskTheCore(string command) => Type = command;
	}
}
