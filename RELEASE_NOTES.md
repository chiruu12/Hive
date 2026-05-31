# Hive v0.5.2 Release Notes

## Headline: Hardened No-Tools Recovery

A follow-up to v0.5.1 that incorporates review feedback on the no-tools recovery
path, plus the Phase 3 simulation core that landed on `main`.

## What's Fixed

- **Streaming recovery is scoped to pre-content failures**: the OpenAI-compatible
  adapter now recovers a `tool_use_failed` only when it happens *before* any text has
  reached the caller, so a mid-stream error can never produce duplicated output. If a
  recovery stream errors after emitting text, the terminal result preserves the text
  already streamed.
- **Recovery no longer masks real errors**: a `tool_use_failed` on a request that
  *did* offer tools (e.g. a malformed tool schema) is surfaced instead of being
  swallowed by the recovery retry.
- **No mid-thread system messages**: both the agent-layer wrap-up nudge and the
  adapter's text-only recovery nudge are sent as `user`-role messages, which strict
  providers accept mid-conversation (some reject mid-thread `system` messages). The
  agent nudge is sent only for the wrap-up call and is not written to the logged
  conversation.

## Also Included

- **Phase 3 simulation core**: registry-driven world catalogs (events & jobs) and
  wired simulation feedback loops.

## Upgrade

```bash
pip install --upgrade hive-agent
```

No code changes required. The happy path (tools provided, or no error) is unchanged.

---

# Hive v0.5.1 Release Notes

## Headline: Resilient No-Tools Wrap-Up Across Strict Providers

A focused reliability fix. When `Agent.run_once` finishes its tool loop it makes a
final wrap-up call with no tools offered. If the model still emits a tool call on
that call -- common on multi-action requests -- strict OpenAI-compatible providers
(notably **Groq**) reject it with a `tool_use_failed` 400, failing the whole turn
even though the tools that ran during the loop already persisted.

## What's Fixed

- **Provider-agnostic recovery** in the OpenAI-compatible adapter: a `tool_use_failed`
  rejection on a no-tools request is detected by error code/message (no provider
  hardcoding) and recovered with a single bounded retry carrying a strong text-only
  instruction. If the retry still fails, the turn completes with clean text instead
  of raising -- the tools already ran. Covers both `generate_with_metadata` and
  `generate_stream`.
- **Belt-and-suspenders nudge** at the agent layer: `Agent.run_once` now appends a
  "tool budget exhausted, reply in plain text" user message before the final
  wrap-up call, reducing the chance of hitting the error at all. (A user-role message
  is used deliberately -- some strict providers reject mid-thread system messages.)

A multi-action turn (e.g. "make three notes") now completes on Groq without surfacing
a 400.

## Upgrade

```bash
pip install --upgrade hive-agent
```

No code changes required. The happy path (tools provided, or no error) is unchanged.

---

# Hive v0.5.0 Release Notes

## Headline: A Composable Core That Scales

This release hardens and decouples Hive's shared core. The runtime `Agent` is now
a clean, standalone, streaming-capable building block, and the daemon runs many
agents concurrently. Most changes are additive -- the public `Agent`, provider,
and toolkit APIs stay backward compatible.

## What's New

### Streaming
- `BaseProvider.generate_stream()` + `StreamEvent` -- token streaming with a base
  fallback so every provider works out of the box.
- Native streaming for Anthropic and OpenAI-compatible providers (Groq, Fireworks,
  Ollama, LM Studio, OpenRouter).
- `Agent(on_text=...)` streams assistant text token-by-token during `run()`.

### Provider capabilities & availability
- `Capability` + `supports(...)` -- branch on what a provider can do, not its class.
- `Availability` + `availability()` -- distinguishes "no API key" from "unreachable";
  `hive models` now shows the reason for unavailable local servers.

### Daemon scalability
- Agent cycles run **concurrently** with bounded concurrency
  (`daemon.max_concurrent_agents`, default 8). Each cycle is isolated, so one slow,
  timed-out, or failing agent never blocks or breaks the others.
- Per-agent provider and profile are cached across cycles.

### Framework polish
- **Concurrent tool execution** -- multiple tool calls in one model turn run in
  parallel, with per-call error isolation and ordered results.
- **Typed errors** -- `HiveError`, `AgentNotFoundError`, `ProfileNotFoundError`.
- **Standalone `Agent`** is first-class: 2-line usage, no daemon (see example 23).
- **`InstructionLike` protocol** unifies `Instructions` / `Persona` / custom objects.
- Structured output works on every provider (prompt-based fallback default).

### Persistence
- SQLite store gained indexes on hot columns and versioned migrations
  (`PRAGMA user_version`) that upgrade older databases in place.

### Tools
- `ClipboardToolkit.read_clipboard` -- read the system clipboard, complementing the
  existing copy tools.

## Upgrade

```bash
pip install --upgrade hive-agent
```

No code changes required for existing agents. To stream, pass `on_text=...` to
`Agent`; to bound daemon throughput, set `daemon.max_concurrent_agents`.

## Stats

- Anthropic, OpenAI, Groq, Fireworks, Ollama, LM Studio, OpenRouter providers
- Full test suite green on Python 3.11 / 3.12 / 3.13
