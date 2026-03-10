# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Figaro is a NATS-based orchestration system for managing Claude agent workers running in containerized desktop environments. Workers execute browser automation tasks via the claude-agent-sdk, with live desktop streaming through Apache Guacamole (guacd + guacamole-common-js). A supervisor agent handles task optimization and delegation. A channel-agnostic gateway service routes messages to/from external channels (Telegram, etc.) for human-in-the-loop interactions.

All services communicate via NATS (pub/sub + JetStream for durable task events). The UI connects to NATS via WebSocket (nats.ws) for both real-time events and mutations (request/reply). HTTP endpoints are minimal: `GET /api/config` (NATS URL discovery), `GET /api/guacamole/token` (encrypted connection tokens), and `WS /guacamole/webSocket` (Guacamole WebSocket tunnel via guapy).

## Long-Running Task Design

**This system is built for tasks that run for minutes to hours.** Browser automation with Claude agents is inherently long-running — a single task may involve navigating dozens of pages, filling forms, waiting for page loads, and interacting with complex web applications. All timeouts, subscriptions, and communication patterns must account for this.

Key principles:
- **Never use fixed wall-clock timeouts for task execution.** Use inactivity-based timeouts that reset on worker progress. A task actively streaming messages is healthy regardless of how long it's been running.
- **NATS request/reply timeouts are for API calls, not task lifecycles.** The `request()` timeout (default 10s, UI 30s) covers orchestrator round-trips, NOT how long a task takes. Task progress is tracked via JetStream subscriptions, not request/reply.
- **JetStream provides durable delivery.** Task events (messages, completion, errors) go through JetStream so they survive reconnections. Core NATS is only for ephemeral operations (registration, heartbeats, API calls).
- **Supervisor delegation is blocking but progress-aware.** `waitForDelegation()` in `supervisor/tools.ts` subscribes to `figaro.task.{id}.message` and resets its inactivity timer on every worker message. The `DELEGATION_INACTIVITY_TIMEOUT` (600s) is a silence detector, not a task duration limit.
- **Help requests have their own timeouts.** Human-in-the-loop requests wait independently (default 300s) and don't affect the task execution timeout.
- **Use Core NATS subscriptions for waiting on task events in the worker/supervisor.** JetStream ephemeral push consumers (`js.subscribe()` in nats.js v2) are unreliable — they can fail silently or throw during setup, causing tools like `delegate_to_worker` to return immediately instead of blocking. Since JetStream publishes also deliver to Core NATS subscribers on the same subject, use `nc.subscribe()` instead (same pattern as `HelpRequestHandler`). Both are ephemeral and behave identically for `DeliverPolicy.New` use cases.

When adding new features or modifying existing ones, always ask: "What happens if this task runs for 2 hours?" If the answer involves a timeout killing it while it's still making progress, the design is wrong.

## Code Style

- **Use f-strings for all string interpolation.** No `%s`-style formatting or `.format()` calls — always use f-strings.
- **Use high-level asyncio APIs.** Prefer `asyncio.create_task()`, `asyncio.gather()`, `asyncio.wait_for()`, etc. over low-level primitives like `loop.create_future()`, `ensure_future()`, or direct event loop access.
- **Use `pathlib` for all path operations.** No `os.path` calls — always use `pathlib.Path` for constructing, joining, and manipulating file paths.
- **Avoid nested functions.** Don't define functions inside other functions — extract them as module-level or class-level methods instead.
- **No inline imports.** All imports must be at the top of the file — never import inside functions, methods, or conditional blocks.
- **Use `Subjects` constants for all NATS subjects.** Never use raw strings like `"figaro.broadcast.foo"` — always use `Subjects.SOME_CONSTANT` or `Subjects.some_method(id)` from `figaro_nats.Subjects` (Python) or `nats/subjects.ts` (TypeScript). When adding a new NATS subject, add the constant to `figaro-nats/src/figaro_nats/subjects.py` first, then reference it everywhere.
- **Keep files under 500 lines.** If a file exceeds 500 lines, split it into smaller, focused modules.

## Build & Run Commands

### Shared NATS Library (figaro-nats/)
```bash
cd figaro-nats
uv sync --frozen
uv run pytest             # Run tests
uv run ruff check .       # Lint
uv run ruff format .      # Format
```

### Orchestrator (figaro/)
```bash
cd figaro
uv sync --frozen          # Install dependencies
uv run figaro             # Start orchestrator on port 8000
uv run pytest             # Run all tests
uv run pytest tests/test_registry.py -k "test_register"  # Single test
uv run ruff check .       # Lint
uv run ruff format .      # Format
```

### Worker (figaro-worker/) — Bun/TypeScript
```bash
cd figaro-worker
bun install               # Install dependencies
bun run dev               # Start worker
bun run dev --supervisor  # Start as supervisor
bun test                  # Run tests
bun run build             # Compile to standalone binary
```

**Pyodide with Bun single-file executables:** Bun's single-file compilation doesn't support Pyodide's dynamic `pyodide.asm.js` loading. To fix this, explicitly import it so Bun bundles it and its side effect sets `globalThis._createPyodideModule`, causing pyodide to skip the dynamic load:
```ts
import "pyodide/pyodide.asm.js";
```

### Gateway (figaro-gateway/)
```bash
cd figaro-gateway
uv sync --frozen
uv run figaro-gateway     # Start gateway service
uv run pytest             # Run tests
uv run ruff check .       # Lint
uv run ruff format .      # Format
```

### UI (figaro-ui/)
```bash
cd figaro-ui
npm install
npm run dev               # Dev server on port 3000
npm run build             # TypeScript check + production build (tsc && vite build)
npm run test              # Run tests (vitest)
npm run test:watch        # Watch mode
```

### Docker (Full Stack)
Always use both the base and dev overlay compose files:
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml ps
```

### Database Migrations (figaro/)
```bash
cd figaro
uv run alembic upgrade head   # Apply migrations
uv run alembic revision --autogenerate -m "description"  # New migration
```

## Architecture

```
                     ┌──────────────────┐
                     │   NATS Server    │
                     │  (+ JetStream)   │
                     │  (+ WebSocket)   │
                     └────────┬─────────┘
       ┌──────────┬───────────┼───────────┬──────────────┐
       │          │           │           │              │
  ┌────┴────┐ ┌───┴────┐ ┌───┴─────┐ ┌───┴──────────┐ ┌┴───────────┐
  │ Worker  │ │Orchestr│ │Supervis │ │   Gateway    │ │    UI      │
  │  (x N)  │ │  ator  │ │   or    │ │  (channels)  │ │   (SPA)    │
  └─────────┘ └───┬────┘ └─────────┘ └──────────────┘ └────────────┘
                   │
              ┌────┴────┐
              │  guacd  │
              │(Guacam.)│
              └─────────┘
```

- **NATS Server**: Central message broker with JetStream for durable task event streaming
- **Orchestrator**: NATS-first service (request/reply + pub/sub); manages task lifecycle, worker registry, scheduling. Minimal FastAPI for config endpoint, Guacamole token endpoint, and guapy WebSocket tunnel
- **guacd**: Apache Guacamole server daemon — proxies VNC/RDP/SSH/telnet connections from the browser. Built from source via `docker/Dockerfile.guacd` for multi-arch support (official image is amd64-only). The orchestrator connects to guacd via the `guapy` Python library
- **Worker (x N)**: Bun/TypeScript service; executes browser automation via claude-agent-sdk; publishes task events to JetStream. Also runs as supervisor when started with the `--supervisor` flag
- **Supervisor**: Same Bun/TypeScript binary as the worker, started with `--supervisor` flag. Handles task optimization/delegation using SDK-native custom tools (`tool()` + `createSdkMcpServer()`) backed by NATS request/reply
- **Gateway**: Channel-agnostic messaging gateway (Telegram, future: WhatsApp, Slack, etc.)
- **UI**: React SPA; connects to NATS via WebSocket (nats.ws) for all communication — real-time events via pub/sub, mutations via request/reply

## NATS Subject Design

```
# Registration & Presence (Core NATS)
figaro.register.worker                    # Worker publishes registration info
figaro.register.supervisor                # Supervisor publishes registration info
figaro.register.gateway                   # Gateway publishes registration info
figaro.deregister.{type}.{id}             # Graceful disconnect notification
figaro.heartbeat.{type}.{id}              # Periodic liveness heartbeat

# Task Assignment (Core NATS - point-to-point)
figaro.worker.{worker_id}.task            # Assign task to specific worker
figaro.supervisor.{supervisor_id}.task    # Assign task to specific supervisor

# Task Events (JetStream TASKS stream - figaro.task.>)
figaro.task.{task_id}.assigned            # Task assigned to worker/supervisor
figaro.task.{task_id}.message             # Streaming SDK output messages
figaro.task.{task_id}.complete            # Task completed with result
figaro.task.{task_id}.error               # Task failed with error

# Help Requests (Core NATS)
figaro.help.request                       # New help request published
figaro.help.{request_id}.response         # Response to specific help request

# Broadcasts (Core NATS)
figaro.broadcast.workers                  # Updated workers list
figaro.broadcast.supervisors              # Updated supervisors list
figaro.broadcast.task_healing             # Task healing event (healer task created)

# API (NATS request/reply - used by supervisor tools + UI)
figaro.api.delegate                       # Delegate task to worker
figaro.api.workers                        # List connected workers
figaro.api.tasks                          # List tasks (filterable)
figaro.api.tasks.get                      # Get specific task
figaro.api.tasks.create                   # Create task (claims idle worker)
figaro.api.tasks.search                   # Search tasks by prompt
figaro.api.supervisor.status              # Get supervisor status
figaro.api.scheduled-tasks                # List scheduled tasks
figaro.api.scheduled-tasks.{get,create,update,delete,toggle,trigger}
figaro.api.help-requests.respond          # Respond to help request
figaro.api.help-requests.dismiss          # Dismiss help request
figaro.api.vnc                            # VNC operations (screenshot, type, key, click)
figaro.api.ssh                            # SSH operations (run_command)
figaro.api.telnet                         # Telnet operations (run_command)

# Gateway (Core NATS)
figaro.gateway.{channel}.send             # Send message via channel
figaro.gateway.{channel}.task             # New task received from channel
figaro.gateway.{channel}.question         # Ask question via channel (request/reply)
figaro.gateway.{channel}.register         # Channel gateway registers availability
```

## Key Components

### Shared NATS Library (figaro-nats/)
- `client.py`: `NatsConnection` class wrapping `nats.aio.client.Client` with JSON serialization, auto-reconnect, typed publish/subscribe/request/subscribe_request methods for both Core NATS and JetStream
- `subjects.py`: `Subjects` class with all NATS subject constants, builder functions, and API request/reply subjects
- `streams.py`: `ensure_streams(js)` creates/updates the TASKS JetStream stream (7-day retention)
- `tracing.py`: `init_tracing(service_name)`, `inject_trace_context()`, `extract_trace_context()`, `traced()` decorator — core OTel setup and W3C trace context propagation over NATS headers
- `trace_chain.py`: `get_span_chain()`, `assert_span_chain()` — builds deterministic span chains from flat span lists for test assertions
- `jaeger.py`: `get_trace_spans(trace_id)` — polls Jaeger HTTP API until span count stabilizes, used by live tracing tests

### Figaro Orchestrator (figaro/)
- `app.py`: FastAPI app factory with lifespan, mounts routers (config, guacamole token, VNC proxy) and guapy WebSocket server at `/guacamole`, starts NatsService
- `services/nats_service.py`: Core NATS integration — subscribes to registration/heartbeat/task events/help requests, publishes task assignments and broadcasts, handles all NATS API request/reply (task CRUD, scheduled tasks, help requests, supervisor tools)
- `services/registry.py`: In-memory connection registry with heartbeat-based presence detection
- `services/task_manager.py`: Task queue, assignment, and persistence to PostgreSQL
- `services/scheduler.py`: Cron-like scheduling for recurring tasks, publishes assignments via NATS. Supports manual trigger via `trigger_scheduled_task()` (executes immediately regardless of enabled state). Supports self-learning mode for automatic prompt optimization
- `services/help_request.py`: Human-in-the-loop request management with channel-agnostic routing
- `routes/config.py`: `GET /api/config` — returns NATS WebSocket URL for UI discovery
- `routes/guacamole.py`: `GET /api/guacamole/token` — generates encrypted Guacamole connection tokens for workers. Resolves worker connection URL (VNC/RDP/SSH/telnet) from registry, builds connection settings, encrypts via `guapy.crypto.GuacamoleCrypto` with the orchestrator's `encryption_key`
- `routes/websocket.py`: `WS /vnc/{worker_id}` — VNC proxy endpoint (deprecated, use guacamole instead)
- `services/vnc_client.py`: Low-level VNC interaction via `asyncvnc` — `vnc_screenshot()`, `vnc_type()`, `vnc_key()`, `vnc_click()`. Used by the `figaro.api.vnc` handler to execute supervisor VNC tool requests against worker desktops
- `db/models.py`: SQLAlchemy models (TaskModel, ScheduledTaskModel, HelpRequestModel, etc.)
- `db/repositories/`: Data access layer for each model type
- `tracing.py`: `init_tracing(app, engine)` — wraps `figaro_nats.init_tracing("figaro-orchestrator")` and adds FastAPI, SQLAlchemy, and logging auto-instrumentation
- `config.py`: Settings via `FIGARO_*` env vars (includes `nats_url`, `nats_ws_url`, `guacd_host`, `guacd_port`, `encryption_key`)

### Figaro Worker (figaro-worker/) — Bun/TypeScript
The worker and supervisor are the same Bun/TypeScript binary. The `--supervisor` flag switches the mode at startup (see `src/config.ts` and `src/index.ts`).

**Worker mode (default):**
- `src/worker/executor.ts`: Executes tasks using claude-agent-sdk, streams output via JetStream
- `src/worker/help-request.ts`: Routes AskUserQuestion to orchestrator via NATS
- `src/worker/prompt-formatter.ts`: Formats task prompts for the agent
- `src/worker/tools.ts`: Tool definitions for the agent

**Supervisor mode (`--supervisor`):**
- `src/supervisor/executor.ts`: Processes tasks using claude-agent-sdk with SDK custom tools, all delegation is blocking (waits for worker result)
- `src/supervisor/tools.ts`: SDK-native custom tools (`tool()` + `createSdkMcpServer()`) with NATS-backed handlers. A fresh server is created per session to avoid lifecycle issues. Includes delegation tools (delegate_to_worker, list_tasks, etc.) and VNC tools (`take_screenshot`, `type_text`, `press_key`, `click`) for direct interaction with worker desktops. `waitForDelegation()` uses inactivity-based timeout (resets on every worker message) rather than a fixed wall-clock timeout.
- `src/supervisor/prompt-formatter.ts`: Formats supervisor prompts with system instructions
- `src/supervisor/hooks.ts`: Claude Code hooks (pre_tool_use, post_tool_use, stop)

**Shared:**
- `src/nats/client.ts`: `NatsClient` — publishes registration, subscribes to task assignments, typed publish methods for task messages/completion/errors via JetStream. Supports both worker and supervisor `clientType`
- `src/nats/subjects.ts`: NATS subject constants
- `src/nats/streams.ts`: JetStream stream setup
- `src/shared/serialize.ts`: Message serialization shared between worker and supervisor
- `src/config.ts`: Settings via `WORKER_*` env vars (worker mode) or `SUPERVISOR_*` env vars (supervisor mode)
- `src/types.ts`: TypeScript type definitions
- `src/tracing/tracer.ts`: `initTracing()`, `traced()`, custom `FetchOTLPExporter` (uses `fetch()` instead of Node HTTP for Bun compatibility, uses `sdk-trace-base` instead of `sdk-trace-node`)
- `src/tracing/propagation.ts`: `injectTraceContext()`, `extractTraceContext()` — custom `TextMapGetter`/`TextMapSetter` bridging OTel propagation to NATS `MsgHdrs`
- `src/tracing/trace-chain.ts`: TypeScript port of `figaro_nats.trace_chain` for cross-language span chain assertions

### Legacy Implementations (legacy/)
The original Python supervisor (`legacy/figaro-supervisor/`) and Python worker (`legacy/figaro-worker/`) implementations, kept for reference. Use the Bun/TypeScript worker above for active development.

### Figaro Gateway (figaro-gateway/)
- `core/channel.py`: `Channel` protocol — interface for communication channels (start, stop, send_message, ask_question, on_message)
- `core/router.py`: `NatsRouter` — wires NATS subjects to channel methods, routes help requests to channels
- `core/registry.py`: `ChannelRegistry` — tracks active channel instances
- `channels/telegram/channel.py`: `TelegramChannel` — wraps TelegramBot to implement Channel protocol
- `channels/telegram/bot.py`: Telegram bot for message handling, inline keyboards, question/answer
- `config.py`: Settings via `GATEWAY_*` env vars

Adding a new channel (e.g. WhatsApp):
1. Create `channels/whatsapp/channel.py` implementing `Channel` protocol
2. Register in `__init__.py`
3. Gateway auto-creates NATS subjects for `figaro.gateway.whatsapp.*`

### Figaro UI (figaro-ui/)
- `api/nats.ts`: `NatsManager` — connects to NATS via WebSocket (nats.ws), subscribes to broadcasts + JetStream task events, provides `request()` method for NATS request/reply mutations
- `api/guacamole.ts`: `getGuacamoleToken()` fetches encrypted token from orchestrator, `getGuacamoleWsUrl()` builds the guapy WebSocket URL
- `api/scheduledTasks.ts`: Scheduled task CRUD + trigger functions using NATS request/reply
- `hooks/useGuacamole.ts`: React hook wrapping `guacamole-common-js` — manages Guacamole client lifecycle, auto-reconnect with exponential backoff, display scaling via ResizeObserver, keyboard/mouse input forwarding
- `hooks/useNats.ts`: React hook for NATS connection, task submission via NATS request/reply
- `stores/`: Zustand stores for workers, messages, connection, scheduledTasks, helpRequests, supervisors
- `components/`: Dashboard, DesktopGrid, VNCViewer (uses useGuacamole), ChatInput, EventStream
- `types/guacamole.d.ts`: TypeScript type declarations for `guacamole-common-js`
- `tracing.ts`: `initTracing()`, `createTaskSpan()`, `injectTraceContext()` — uses `WebTracerProvider` (browser), forces XHR transport to avoid CORS issues with `sendBeacon`

## HTTP Endpoints (Minimal)

All business operations use NATS request/reply. HTTP endpoints:

- `GET /api/config` — Returns NATS WebSocket URL for UI discovery (needed before NATS connects)
- `GET /api/guacamole/token?worker_id=...` — Returns an encrypted Guacamole connection token. Resolves the worker's connection URL from the registry, detects the protocol (VNC/RDP/SSH/telnet) from the URL scheme, and encrypts connection settings with `GuacamoleCrypto` (AES-256-CBC)
- `WS /guacamole/webSocket?token=...` — Guacamole WebSocket tunnel served by guapy. Decrypts the token, connects to guacd, and proxies the Guacamole protocol to the browser's `guacamole-common-js` client
- `WS /vnc/{worker_id}` — Legacy VNC proxy endpoint (deprecated, use guacamole instead)

### Desktop Streaming via Guacamole

Desktop streaming uses Apache Guacamole (replacing the previous noVNC approach):

1. UI calls `GET /api/guacamole/token?worker_id=...` to get an encrypted connection token
2. UI opens a WebSocket to `/guacamole/webSocket?token=...` using `guacamole-common-js`
3. The guapy server (mounted in the orchestrator) decrypts the token and connects to guacd
4. guacd connects to the worker's VNC server (or RDP/SSH/telnet based on URL scheme)
5. The Guacamole protocol streams the desktop to the browser

**Key libraries:**
- `guapy` (Python): Guacamole WebSocket server + crypto for FastAPI, used by orchestrator
- `guacamole-common-js` (JS): Browser client library, used by UI via `useGuacamole` hook
- `guacd`: Apache Guacamole server daemon, built from source (`docker/Dockerfile.guacd`) for multi-arch support

**Protocol detection:** The `novnc_url` field on worker connections is parsed to detect the protocol — `vnc://` → VNC, `rdp://` → RDP, `ssh://` → SSH, `telnet://` → telnet, `ws://`/`wss://` → VNC (legacy noVNC URLs).

### Docker Dev Files

- `docker/Dockerfile.guacd`: Multi-arch guacd build from source (Guacamole 1.6.0)
- `docker/Dockerfile.test-target`: Lightweight Alpine container with SSH + telnet for testing non-VNC protocols

## Distributed Tracing (OpenTelemetry)

All services are instrumented with OpenTelemetry for end-to-end distributed tracing. Traces propagate across NATS messages using W3C Trace Context (`traceparent` header).

**Architecture:**
- **Protocol:** W3C Trace Context over NATS message headers
- **Export:** OTLP/HTTP JSON (`/v1/traces`) to Jaeger
- **Tracer name:** `"figaro"` (all services)
- **Service names:** `figaro-ui`, `figaro-orchestrator`, `figaro-worker`, `figaro-supervisor`
- **No-op when disabled:** All `initTracing()` functions are no-ops when the OTLP endpoint env var is unset

**Trace flow:** UI creates a root span (`ui.task_submission`) → injects `traceparent` into NATS headers → orchestrator extracts context, creates child spans, injects into task assignment → worker/supervisor extracts, creates child spans, injects into completion/error messages → orchestrator extracts from completion and creates final child spans. All spans share the same trace ID.

**Span naming convention:** `component.operation` (e.g., `orchestrator.api_create_task`, `worker.execute_task`, `task_manager.complete_task`, `registry.claim_idle_worker`).

**Span chain testing utilities** (`figaro-nats`): The `get_span_chain()` function builds a deterministic depth-first chain from flat span lists, filtering out auto-instrumented spans (HTTP, SQLAlchemy) by checking for known prefixes (`orchestrator.`, `worker.`, `task_manager.`, `registry.`, `supervisor.`, `ui.`). Consecutive duplicate spans at the same depth are normalized to `"name (repeat)"`. `assert_span_chain()` compares actual vs expected with unified diff output.

**Bun/TypeScript compatibility notes:**
- Worker uses `BasicTracerProvider` from `@opentelemetry/sdk-trace-base` (not `NodeTracerProvider` from `sdk-trace-node`) for Bun compatibility
- Worker uses a custom `FetchOTLPExporter` that serializes spans to OTLP JSON and exports via `fetch()`, avoiding CJS class inheritance issues with `@opentelemetry/exporter-trace-otlp-http` under Bun's bundler
- UI uses `WebTracerProvider` from `@opentelemetry/sdk-trace-web` with explicit empty `headers: {}` on the exporter to force XHR transport (avoids CORS errors from `sendBeacon` including credentials)

## Testing

Tests use pytest-asyncio with SQLite in-memory for database tests. NATS connections are mocked in tests.

**Orchestrator fixtures** (`figaro/tests/conftest.py`):
- `db_session`: In-memory SQLite session (PostgreSQL-compatible types mapped)
- `registry`, `task_manager`, `mock_nats_service`: Service-level fixtures for unit testing

**Worker fixtures** (`figaro-worker/tests/`): Bun test mocks for NATS client and executor.

**Supervisor fixtures** (`figaro-worker/tests/`): Bun test mocks for NatsClient in supervisor mode and SupervisorExecutor.

**Gateway fixtures**: Mock `NatsConnection` and `Channel` implementations.

**UI tests**: Vitest with `natsManager.request()` mocked via `vi.spyOn` for NATS request/reply operations.

**Live tracing tests** (`figaro/tests/test_trace_live.py`): End-to-end tests marked `@pytest.mark.live` that verify distributed trace propagation across services. Require running NATS (`nats://nats:4222`) and Jaeger (`http://jaeger:16686`); auto-skip when infrastructure is unavailable. Tests submit real tasks via NATS, wait for completion/error events, poll Jaeger for the trace via `get_trace_spans()`, build the span chain, and compare against JSON snapshots in `tests/snapshots/`. Uses `SimpleSpanProcessor` (immediate flush) for deterministic test output.

```bash
cd figaro
uv run pytest -m live              # Run live tracing tests
uv run pytest -m live --record     # Re-record span chain snapshots
```

**Span chain unit tests** (`figaro-nats/tests/test_trace_chain.py`): Pure unit tests for the `get_span_chain()` / `assert_span_chain()` utilities — deterministic ordering, repeat normalization, auto-instrumented span filtering, empty input handling.

## After Every Code Change

Always run these checks after modifying code:

**Python (figaro/, figaro-gateway/, figaro-nats/):**
```bash
uv run ruff check .      # Linting (required)
uv run pytest            # Tests (required)
```

**TypeScript — Worker (figaro-worker/):**
```bash
bun run lint             # Linting (required)
bunx tsc --noEmit        # Type check (required)
bun test                 # Tests (required)
```

**TypeScript — UI (figaro-ui/):**
```bash
npm run lint             # Linting (required)
npm run test             # Type check (tsc --noEmit) + Vitest (required)
```

**Shell scripts (*.sh):**
```bash
shellcheck <file>.sh     # Lint (required)
```

## Environment Variables

| Variable | Component | Description |
|----------|-----------|-------------|
| `FIGARO_HOST` | Orchestrator | Bind address (default: 0.0.0.0) |
| `FIGARO_PORT` | Orchestrator | Listen port (default: 8000) |
| `FIGARO_DATABASE_URL` | Orchestrator | PostgreSQL connection string |
| `FIGARO_NATS_URL` | Orchestrator | NATS server URL (default: nats://localhost:4222) |
| `FIGARO_NATS_WS_URL` | Orchestrator | NATS WebSocket URL for UI (default: ws://localhost:8443) |
| `FIGARO_STATIC_DIR` | Orchestrator | Path to built UI files |
| `WORKER_NATS_URL` | Worker | NATS server URL |
| `WORKER_ID` | Worker | Unique worker identifier |
| `WORKER_NOVNC_URL` | Worker | External noVNC URL for UI |
| `FIGARO_SELF_HEALING_ENABLED` | Orchestrator | Enable automatic task retry on failure (default: true) |
| `FIGARO_SELF_HEALING_MAX_RETRIES` | Orchestrator | Max healing retries per task chain (default: 2) |
| `FIGARO_GUACD_HOST` | Orchestrator | Guacamole daemon hostname (default: localhost) |
| `FIGARO_GUACD_PORT` | Orchestrator | Guacamole daemon port (default: 4822) |
| `FIGARO_ENCRYPTION_KEY` | Orchestrator | AES-256-CBC key for Guacamole tokens (auto-generated if not set) |
| `FIGARO_VNC_PASSWORD` | Orchestrator | VNC password for worker desktops (default: none) |
| `FIGARO_VNC_PORT` | Orchestrator | VNC display port on workers (default: 5901) |
| `SUPERVISOR_NATS_URL` | Worker (supervisor mode) | NATS server URL |
| `SUPERVISOR_ID` | Worker (supervisor mode) | Unique supervisor identifier |
| `SUPERVISOR_MODEL` | Worker (supervisor mode) | Claude model to use (default: claude-opus-4-6) |
| `SUPERVISOR_CLAUDE_CODE_PATH` | Worker (supervisor mode) | Path to Claude Code CLI binary |
| `SUPERVISOR_MAX_TURNS` | Worker (supervisor mode) | Max conversation turns |
| `SUPERVISOR_DELEGATION_INACTIVITY_TIMEOUT` | Worker (supervisor mode) | Inactivity timeout for delegated tasks in seconds (default: 600) |
| `GATEWAY_NATS_URL` | Gateway | NATS server URL |
| `GATEWAY_TELEGRAM_BOT_TOKEN` | Gateway | Telegram bot token |
| `GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS` | Gateway | Allowed Telegram chat IDs (JSON array) |
| `VITE_NATS_WS_URL` | UI | NATS WebSocket URL (default: ws://localhost:8443) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Orchestrator, Worker, Gateway | OTLP endpoint for trace export (tracing disabled if unset) |
| `VITE_OTEL_EXPORTER_OTLP_ENDPOINT` | UI | OTLP endpoint for browser trace export (tracing disabled if unset) |

## Message Flow

### Task Submission (UI -> Worker)
1. UI sends NATS request to `figaro.api.tasks.create`
2. Orchestrator creates task, claims idle worker, publishes to `figaro.worker.{id}.task`
3. Worker receives task, executes with claude-agent-sdk
4. Worker streams messages via JetStream (`figaro.task.{id}.message`)
5. UI receives messages via JetStream subscription
6. Worker publishes completion via JetStream (`figaro.task.{id}.complete`)
7. Orchestrator updates DB, sets worker idle, processes pending queue

### Help Request Flow
1. Worker/Supervisor publishes to `figaro.help.request`
2. Orchestrator creates help request, broadcasts to UI
3. Gateway receives help request, routes to Telegram (or other channel)
4. First responder (UI via `figaro.api.help-requests.respond` or channel) responds
5. Response routed back to requesting worker/supervisor

### Gateway Task Flow (Channel -> Worker)
1. User sends message via channel (e.g. Telegram bot)
2. Gateway publishes to `figaro.gateway.{channel}.task`
3. Orchestrator creates task, assigns to supervisor
4. Supervisor processes, delegates to worker via NATS request/reply
5. Supervisor waits for worker completion via JetStream
6. Result flows back through NATS to gateway
7. Gateway sends response to user via channel

### Supervisor VNC Interaction (Supervisor -> Worker Desktop)
The supervisor agent can directly observe and interact with worker desktops via 4 VNC tools, without delegating a full task. This enables the supervisor to monitor progress, take corrective action, or perform quick interactions on a worker's screen.

**Tools available to the supervisor agent:**
- `take_screenshot(worker_id, quality=70)` — captures the worker's desktop as a base64 JPEG image
- `type_text(worker_id, text)` — types text on the worker's desktop keyboard
- `press_key(worker_id, key, modifiers=[])` — presses a key combination (e.g. `key="Enter"`, `modifiers=["ctrl"]`)
- `click(worker_id, x, y, button="left")` — clicks at coordinates on the worker's desktop

**Flow:**
1. Supervisor agent calls a VNC tool (e.g. `take_screenshot`)
2. Tool sends NATS request to `figaro.api.vnc` with `{worker_id, action, ...params}`
3. Orchestrator looks up worker in registry, extracts VNC hostname from `novnc_url`
4. Orchestrator connects directly to worker's VNC server via `asyncvnc` (port from `FIGARO_VNC_PORT`)
5. Orchestrator executes the VNC operation and returns the result via NATS reply
6. Supervisor agent receives the result (screenshot image or success confirmation)

**Design notes:**
- The supervisor has no direct VNC client — all VNC operations are proxied through the orchestrator
- Each VNC tool call uses a 10s NATS request/reply timeout (appropriate since these are quick operations, not long-running tasks)
- `vnc_client.py` normalizes 65+ key name aliases (e.g. "ctrl" → "Ctrl", "escape" → "Esc") to X11 keysym names required by asyncvnc
- Screenshot quality is configurable (0-100, default 70) to balance image clarity vs payload size

### Supervisor SSH/Telnet Interaction (Supervisor -> Worker Terminal)
The supervisor agent can execute commands on workers with SSH or telnet connections, without delegating a full task. This enables the supervisor to run diagnostics, check status, or perform quick operations on terminal-based workers.

**Tools available to the supervisor agent:**
- `ssh_run_command(worker_id, command, timeout=30)` — executes a shell command via SSH, returns stdout, stderr, and exit code
- `telnet_run_command(worker_id, command, timeout=10)` — executes a command via telnet, returns the terminal output

**Flow:**
1. Supervisor agent calls a terminal tool (e.g. `ssh_run_command`)
2. Tool sends NATS request to `figaro.api.ssh` (or `figaro.api.telnet`) with `{worker_id, action, command, ...}`
3. Orchestrator looks up worker in registry, extracts connection details from `novnc_url`
4. Orchestrator connects to the worker via asyncssh (or telnetlib3) and executes the command
5. Orchestrator returns the result via NATS reply
6. Supervisor agent receives stdout/stderr/exit_code (SSH) or output (telnet)

**Design notes:**
- Only works for workers with `ssh://` or `telnet://` connection URLs
- SSH uses `known_hosts=None` (appropriate for containerized environments)
- Telnet handles login prompts automatically when credentials are provided
- Each tool call opens a fresh connection (no connection pooling)
- NATS request timeout is set dynamically: `max(30s, command_timeout + 5s)`

### Self-Learning Scheduled Task Flow
Scheduled tasks with `self_learning=True` automatically optimize their prompts after each run:
1. Worker completes a scheduled task
2. Orchestrator's `_handle_task_complete()` fires `_maybe_optimize_scheduled_task()` via `asyncio.create_task()`
3. Method checks: task has `scheduled_task_id`, `source="scheduler"`, and scheduled task has `self_learning=True`
4. Retrieves conversation history, filters to key message types (assistant, tool_result, result), caps at last 50 messages
5. Creates an optimization task (`source="optimizer"`) with a prompt containing the current scheduled task prompt + conversation history
6. Assigns to an idle supervisor, which analyzes the conversation and calls `update_scheduled_task` to save an improved prompt
7. Next scheduled run uses the improved prompt

Key implementation details:
- Optimization runs fire-and-forget (background task) — failures are logged but don't affect the main completion flow
- No throttling: optimization runs after every completed scheduled task run
- The supervisor is instructed to ONLY update the prompt field, preserving schedule/enabled/start_url settings
- The `ScheduledTaskModel` has a `self_learning` boolean column (default `False`), exposed through the full stack (DB → repository → scheduler → nats_service API → UI form toggle)

### Self-Healing Failed Task Flow
When a task fails, the orchestrator can automatically create a "healer" task that analyzes the failure and retries with an improved approach. The supervisor uses conversation history and VNC tools to understand what went wrong and recover.

**Flow:**
1. Worker publishes error to `figaro.task.{id}.error`
2. Orchestrator's `_handle_task_error()` fires `_maybe_heal_failed_task()` as a background task
3. Healing decision tree evaluates (in priority order):
   a. Task-level: `options.self_healing` flag on the failed task
   b. Scheduled task-level: `self_healing` field on the associated scheduled task
   c. System-level: `FIGARO_SELF_HEALING_ENABLED` (default: true)
4. If enabled and retry count < `FIGARO_SELF_HEALING_MAX_RETRIES` (default: 2), creates a healer task containing:
   - Original prompt + error message + conversation history (last 50 messages)
   - Start URL from original task options
   - Retry tracking metadata (`original_task_id`, `failed_task_id`, `retry_number`, `max_retries`)
5. Healer task is assigned to an idle supervisor (or queued if none available)
6. Supervisor analyzes the failure, determines if recoverable, and either:
   - **Recoverable** (element not found, timing issues, navigation errors): uses `delegate_to_worker` with an improved prompt addressing the failure. May use VNC tools to inspect/recover the desktop state first.
   - **Unrecoverable** (invalid credentials, service down, fundamental approach problems): explains why and does NOT retry.
7. If the healer's delegated task also fails and retries remain, another healer is created (up to `max_retries`)

**Loop prevention:**
- Tasks with `source="healer"` or `source="optimizer"` are never healed — only original tasks trigger healing
- Retry chain is tracked via `original_task_id` and `retry_number` to enforce the max retries limit

**Task source routing:** Healer tasks (like optimizer tasks) are always assigned to supervisors, never directly to workers. The supervisor applies intelligent analysis before deciding whether and how to retry.

**Key files:**
- `figaro/services/nats_service.py`: `_maybe_heal_failed_task()` — healing decision tree and healer task creation
- `figaro/config.py`: `self_healing_enabled`, `self_healing_max_retries` settings
- `figaro/db/models.py`: `ScheduledTaskModel.self_healing` column
- `figaro/tests/test_self_healing.py`: comprehensive test suite (9 tests)
