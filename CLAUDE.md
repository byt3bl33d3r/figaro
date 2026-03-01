# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Figaro is a NATS-based orchestration system for managing Claude agent workers running in containerized desktop environments. Workers execute browser automation tasks via the claude-agent-sdk, with live desktop streaming through noVNC. A supervisor agent handles task optimization and delegation. A channel-agnostic gateway service routes messages to/from external channels (Telegram, etc.) for human-in-the-loop interactions.

All services communicate via NATS (pub/sub + JetStream for durable task events). The UI connects to NATS via WebSocket (nats.ws) for both real-time events and mutations (request/reply). The only REST endpoints are `GET /api/config` (NATS URL discovery) and `WS /vnc/{worker_id}` (VNC proxy).

## Long-Running Task Design

**This system is built for tasks that run for minutes to hours.** Browser automation with Claude agents is inherently long-running — a single task may involve navigating dozens of pages, filling forms, waiting for page loads, and interacting with complex web applications. All timeouts, subscriptions, and communication patterns must account for this.

Key principles:
- **Never use fixed wall-clock timeouts for task execution.** Use inactivity-based timeouts that reset on worker progress. A task actively streaming messages is healthy regardless of how long it's been running.
- **NATS request/reply timeouts are for API calls, not task lifecycles.** The `request()` timeout (default 10s, UI 30s) covers orchestrator round-trips, NOT how long a task takes. Task progress is tracked via JetStream subscriptions, not request/reply.
- **JetStream provides durable delivery.** Task events (messages, completion, errors) go through JetStream so they survive reconnections. Core NATS is only for ephemeral operations (registration, heartbeats, API calls).
- **Supervisor delegation is blocking but progress-aware.** `_wait_for_delegation()` in `tools.py` subscribes to `figaro.task.{id}.message` and resets its inactivity timer on every worker message. The `DELEGATION_INACTIVITY_TIMEOUT` (600s) is a silence detector, not a task duration limit.
- **Help requests have their own timeouts.** Human-in-the-loop requests wait independently (default 300s) and don't affect the task execution timeout.

When adding new features or modifying existing ones, always ask: "What happens if this task runs for 2 hours?" If the answer involves a timeout killing it while it's still making progress, the design is wrong.

## Code Style

- **Use f-strings for all string interpolation.** No `%s`-style formatting or `.format()` calls — always use f-strings.
- **Use high-level asyncio APIs.** Prefer `asyncio.create_task()`, `asyncio.gather()`, `asyncio.wait_for()`, etc. over low-level primitives like `loop.create_future()`, `ensure_future()`, or direct event loop access.
- **Use `pathlib` for all path operations.** No `os.path` calls — always use `pathlib.Path` for constructing, joining, and manipulating file paths.
- **Avoid nested functions.** Don't define functions inside other functions — extract them as module-level or class-level methods instead.
- **No inline imports.** All imports must be at the top of the file — never import inside functions, methods, or conditional blocks.

## Build & Run Commands

### Shared NATS Library (figaro-nats/)
```bash
cd figaro-nats
uv sync --frozen
uv run pytest             # Run tests
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

### Supervisor (figaro-supervisor/)
```bash
cd figaro-supervisor
uv sync --frozen
uv run figaro-supervisor  # Start supervisor agent
uv run pytest             # Run tests
```

### Worker (figaro-worker/) — Bun/TypeScript
```bash
cd figaro-worker
bun install               # Install dependencies
bun run dev               # Start worker
bun test                  # Run tests
bun run build             # Compile to standalone binary
```

### Gateway (figaro-gateway/)
```bash
cd figaro-gateway
uv sync --frozen
uv run figaro-gateway     # Start gateway service
uv run pytest             # Run tests
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
```bash
docker compose up --build     # Start postgres + nats + orchestrator + workers + supervisor + gateway
docker compose ps             # Check assigned ports
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
  └─────────┘ └────────┘ └─────────┘ └──────────────┘ └────────────┘
```

- **NATS Server**: Central message broker with JetStream for durable task event streaming
- **Orchestrator**: NATS-first service (request/reply + pub/sub); manages task lifecycle, worker registry, scheduling. Minimal FastAPI for config endpoint and VNC proxy only
- **Worker (x N)**: Bun/TypeScript service; executes browser automation via claude-agent-sdk; publishes task events to JetStream
- **Supervisor**: Claude agent for task optimization/delegation; uses SDK-native custom tools (`@tool` + `create_sdk_mcp_server`) backed by NATS request/reply
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

### Figaro Orchestrator (figaro/)
- `app.py`: FastAPI app factory with lifespan, mounts minimal routers (config + VNC proxy), starts NatsService
- `services/nats_service.py`: Core NATS integration — subscribes to registration/heartbeat/task events/help requests, publishes task assignments and broadcasts, handles all NATS API request/reply (task CRUD, scheduled tasks, help requests, supervisor tools)
- `services/registry.py`: In-memory connection registry with heartbeat-based presence detection
- `services/task_manager.py`: Task queue, assignment, and persistence to PostgreSQL
- `services/scheduler.py`: Cron-like scheduling for recurring tasks, publishes assignments via NATS. Supports manual trigger via `trigger_scheduled_task()` (executes immediately regardless of enabled state). Supports self-learning mode for automatic prompt optimization
- `services/help_request.py`: Human-in-the-loop request management with channel-agnostic routing
- `routes/config.py`: `GET /api/config` — returns NATS WebSocket URL for UI discovery
- `routes/websocket.py`: `WS /vnc/{worker_id}` — VNC proxy endpoint
- `services/vnc_client.py`: Low-level VNC interaction via `asyncvnc` — `vnc_screenshot()`, `vnc_type()`, `vnc_key()`, `vnc_click()`. Used by the `figaro.api.vnc` handler to execute supervisor VNC tool requests against worker desktops
- `db/models.py`: SQLAlchemy models (TaskModel, ScheduledTaskModel, HelpRequestModel, etc.)
- `db/repositories/`: Data access layer for each model type
- `config.py`: Settings via `FIGARO_*` env vars (includes `nats_url`, `nats_ws_url`)

### Figaro Worker (figaro-worker/) — Bun/TypeScript
- `src/nats/client.ts`: `NatsClient` — publishes registration, subscribes to task assignments, typed publish methods for task messages/completion/errors via JetStream
- `src/nats/subjects.ts`: NATS subject constants
- `src/nats/streams.ts`: JetStream stream setup
- `src/worker/executor.ts`: Executes tasks using claude-agent-sdk, streams output via JetStream
- `src/worker/help-request.ts`: Routes AskUserQuestion to orchestrator via NATS
- `src/worker/prompt-formatter.ts`: Formats task prompts for the agent
- `src/worker/tools.ts`: Tool definitions for the agent
- `src/config.ts`: Settings via `WORKER_*` env vars (includes `nats_url`)
- `src/types.ts`: TypeScript type definitions

### Figaro Worker Legacy (figaro-worker-legacy/) — Python (deprecated)
The original Python worker implementation, kept for reference. Use the Bun/TypeScript worker above for active development.

### Figaro Supervisor (figaro-supervisor/)
- `supervisor/client.py`: `SupervisorNatsClient` — same pattern as worker client but for supervisor subjects, includes `subscribe_task_complete()` for monitoring delegated tasks
- `supervisor/tools.py`: SDK-native custom tools (`@tool` + `create_sdk_mcp_server`) with NATS-backed handlers — passed directly to `ClaudeAgentOptions.mcp_servers`. A fresh server is created per session to avoid lifecycle issues. Includes delegation tools (delegate_to_worker, list_tasks, etc.) and VNC tools (`take_screenshot`, `type_text`, `press_key`, `click`) for direct interaction with worker desktops. `_wait_for_delegation()` is a module-level function that uses inactivity-based timeout (resets on every worker message) rather than a fixed wall-clock timeout.
- `supervisor/processor.py`: Processes tasks using claude-agent-sdk with SDK custom tools, all delegation is blocking (waits for worker result)
- `supervisor/help_request.py`: Routes help requests via NATS
- `hooks/`: Claude Code hooks (pre_tool_use, post_tool_use, stop)
- `config.py`: Settings via `SUPERVISOR_*` env vars (includes `nats_url`)

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
- `api/scheduledTasks.ts`: Scheduled task CRUD + trigger functions using NATS request/reply
- `hooks/useNats.ts`: React hook for NATS connection, task submission via NATS request/reply
- `stores/`: Zustand stores for workers, messages, connection, scheduledTasks, helpRequests, supervisors
- `components/`: Dashboard, DesktopGrid, VNCViewer, ChatInput, EventStream

## HTTP Endpoints (Minimal)

All business operations use NATS request/reply. Only two HTTP endpoints remain:

- `GET /api/config` — Returns NATS WebSocket URL for UI discovery (needed before NATS connects)
- `WS /vnc/{worker_id}` — WebSocket proxy to worker's noVNC (binary streaming)

## Testing

Tests use pytest-asyncio with SQLite in-memory for database tests. NATS connections are mocked in tests.

**Orchestrator fixtures** (`figaro/tests/conftest.py`):
- `db_session`: In-memory SQLite session (PostgreSQL-compatible types mapped)
- `registry`, `task_manager`, `mock_nats_service`: Service-level fixtures for unit testing

**Worker fixtures** (`figaro-worker/tests/`): Bun test mocks for NATS client and executor.

**Supervisor fixtures**: Mock `SupervisorNatsClient` with AsyncMock publish methods.

**Gateway fixtures**: Mock `NatsConnection` and `Channel` implementations.

**UI tests**: Vitest with `natsManager.request()` mocked via `vi.spyOn` for NATS request/reply operations.

## After Every Code Change

Always run these checks after modifying code:

**Python (figaro/, figaro-supervisor/, figaro-gateway/, figaro-nats/):**
```bash
uv run ruff check .      # Linting (required)
uv run pytest            # Tests (required)
```

**TypeScript — Worker (figaro-worker/):**
```bash
bun test                 # Tests (required)
```

**TypeScript — UI (figaro-ui/):**
```bash
npm run build            # TypeScript check + Vite build (required)
npm run test             # Vitest (required)
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
| `FIGARO_VNC_PASSWORD` | Orchestrator | VNC password for worker desktops (default: none) |
| `FIGARO_VNC_PORT` | Orchestrator | VNC display port on workers (default: 5901) |
| `SUPERVISOR_NATS_URL` | Supervisor | NATS server URL |
| `GATEWAY_NATS_URL` | Gateway | NATS server URL |
| `GATEWAY_TELEGRAM_BOT_TOKEN` | Gateway | Telegram bot token |
| `GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS` | Gateway | Allowed Telegram chat IDs (JSON array) |
| `VITE_NATS_WS_URL` | UI | NATS WebSocket URL (default: ws://localhost:8443) |

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
