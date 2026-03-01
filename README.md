# Figaro

[![Code LLM Generated (with a lot of human oversight)](https://img.shields.io/badge/code-LLM%20generated%20(with%20a%20lot%20of%20human%20oversight)-ff69b4)](https://en.wiktionary.org/wiki/vibecoding)

<p align="center">
  <img width="384" height="384" alt="Image" src="https://github.com/user-attachments/assets/1da03f7c-de10-482f-b215-0aa2df7f68f6" />
</p>


Figaro is an orchestration platform for Claude computer use agents. It manages fleets of Claude agents that operate full desktop environments -- navigating browsers, filling forms, clicking through UIs, and automating workflows that require real screen interaction. Every agent runs inside a containerized Linux desktop with Chromium, and all desktops are live-streamed to a central dashboard via VNC.

Beyond the built-in containerized workers, Figaro can connect to any VNC-accessible desktop -- local machines, remote servers, cloud VMs, or physical workstations running macOS, Windows, or Linux. Desktops are added from the UI with a VNC URL (`vnc://`, `ws://`, or `wss://`), and the supervisor agent can observe and interact with any connected desktop via screenshots, typing, clicking, and key presses. When a worker agent later connects with a matching ID, the desktop-only entry is automatically upgraded to a full agent worker; when the agent disconnects, the desktop remains visible.

The system is built for long-running tasks that take minutes to hours. All services communicate over NATS (pub/sub + JetStream for durable task events). A supervisor agent handles task optimization and delegation. A channel-agnostic gateway routes messages to external channels (Telegram, etc.) for human-in-the-loop interactions.

You can also manage everything by chatting with the supervisor agent through the gateway -- for example, via Telegram. Send it natural language instructions to create tasks, schedule recurring jobs, check worker status, or ask questions about running tasks. The supervisor understands the full system and can delegate work to workers, inspect desktops via VNC, and report back results, all through a conversational interface.

## UI Action shot

<img width="1389" height="1317" alt="Image" src="https://github.com/user-attachments/assets/ede0b548-22f4-4bd5-a89d-f1ff77a6c9e4" />

## Table of Contents

- [Quick Start](#quick-start)
- [Connecting External Desktops](#connecting-external-desktops)
- [Scheduled Tasks](#scheduled-tasks)
- [Self-Healing](#self-healing)
- [Self-Learning](#self-learning)
- [Security](#security)
- [Architecture](#architecture)
- [Services](#services)
- [Development Setup](#development-setup)
- [Configuration](#configuration)
- [NATS Subject Design](#nats-subject-design)
- [Message Flows](#message-flows)
- [Testing](#testing)
- [Contributing](#contributing)

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Claude credentials (`~/.claude.json` and `~/.claude/.credentials.json`) -- created by running `claude` and signing in. On MacOS (assuming you have a Claude Code subscription) once logged in, you can export the credentials file for use in containers with the following command:
  ```bash
  security find-generic-password -s "Claude Code-credentials" -w > ~/.claude/.credentials.json
  ```
- An OpenAI API key (Optional, only used for `patchright-cli` transcription functionality)

### Setup

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
# Optional: set Telegram gateway variables for notifications and task submission
# GATEWAY_TELEGRAM_BOT_TOKEN=your-bot-token
# GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS=["your-chat-id"]
```

The base `docker-compose.yml` defines all shared services but does **not** expose ports. Choose an overlay for your deployment scenario:

```bash
# Production, localhost-only (recommended) -- ports bound to 127.0.0.1
docker compose -f docker-compose.yml -f docker-compose.prod-local.yml up --build

# Development -- localhost ports + a desktop service for testing VNC
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

> [!CAUTION]
> The `docker-compose.prod.yml` overlay binds ports to `0.0.0.0`, making NATS and the orchestrator accessible from any network interface. Only use this if you understand the security implications and have appropriate firewall rules in place. Please read [Security](#security) to understand known attack surface.
>
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
> ```

Open `http://localhost:8000`.

This starts PostgreSQL, NATS (port 8443), the orchestrator (port 8000), 2 workers, 2 supervisors, and the gateway.

### Scaling

```bash
docker compose -f docker-compose.yml -f docker-compose.prod-local.yml up --build --scale worker=4 --scale supervisor=3
```

### Teardown

```bash
docker compose down       # Stop services
docker compose down -v    # Stop and remove all data
```

## Connecting External Desktops

Figaro is not limited to its own containerized workers. Any machine with a VNC server can be connected as a desktop.

### From the UI

Click "Add Desktop" in the dashboard header. Provide a worker ID, a desktop URL, and select the OS type. Supported URL schemes:

- `vnc://user:password@hostname:5901` -- direct TCP VNC connection
- `ws://hostname:6080` -- WebSocket (noVNC-compatible)
- `wss://hostname:6080` -- WebSocket over TLS

Credentials can be embedded in the URL or entered separately. Connected desktops appear in the live desktop grid and can be viewed, screenshotted, and interacted with by the supervisor agent's VNC tools.

### From Environment Variables

Pre-configure desktops at startup via the `FIGARO_DESKTOP_WORKERS` environment variable:

```bash
FIGARO_DESKTOP_WORKERS='[{"id": "mac-studio", "novnc_url": "vnc://user:pass@192.168.1.50:5900", "metadata": {"os": "macos"}}]'
```

### Agent Upgrade Path

Desktop-only entries act as placeholders. When a worker agent connects with a matching ID, the desktop is automatically upgraded to a full agent worker capable of receiving tasks. When the agent disconnects, the desktop reverts to view-only mode rather than disappearing. This means you can pre-register your desktops and have agents attach and detach dynamically.

This is useful when you want to connect existing physical machines or VMs to Figaro without running the full containerized worker stack. For example, you can point Figaro at your Mac Mini's VNC server, and the supervisor can already observe and interact with its screen. Later, run the `figaro-worker` agent on that machine to give it full task execution capabilities -- the desktop entry upgrades seamlessly without any reconfiguration. If you install `patchright-cli` on that machine it becomes particularly handy: it's a standalone browser automation CLI that speaks the same claude-agent-sdk protocol, so you can drop it onto any machine with a browser and instantly level up your browser automation tasks.

## Scheduled Tasks

<p align="center">
<img width="951" height="1318" alt="Image" src="https://github.com/user-attachments/assets/f508f535-9909-4942-8400-e4115b70b039" />
</p>

Figaro supports cron-like scheduling for recurring tasks. Scheduled tasks are managed through the UI or directly by chatting to Figaro via Telegram or whatever channel is configured in the Gateway.

Each scheduled task has:

- **Prompt** -- the task instruction sent to the agent
- **Cron expression** -- standard cron syntax for scheduling (e.g., `0 9 * * *` for daily at 9 AM)
- **Start URL** -- optional URL the worker's browser should navigate to before starting
- **Enabled/disabled toggle** -- pause and resume without deleting
- **Manual trigger** -- execute immediately regardless of schedule or enabled state
- **Notify on completion via Gateway** -- send a notification to configured gateway channels (e.g., Telegram) when the task completes or fails
- **Self-learning** -- optional automatic prompt optimization after each run

Scheduled tasks are assigned to supervisors, which delegate to workers. The scheduler checks for due tasks every 60 seconds and assigns them to idle supervisors (or queues them if none are available).

### NATS API

```
figaro.api.scheduled-tasks                # List all scheduled tasks
figaro.api.scheduled-tasks.get            # Get a specific scheduled task
figaro.api.scheduled-tasks.create         # Create a new scheduled task
figaro.api.scheduled-tasks.update         # Update an existing scheduled task
figaro.api.scheduled-tasks.delete         # Delete a scheduled task
figaro.api.scheduled-tasks.toggle         # Enable or disable a scheduled task
figaro.api.scheduled-tasks.trigger        # Trigger immediate execution
```

## Self-Healing

When a task fails, the orchestrator can automatically create a "healer" task that analyzes the failure and retries with an improved approach. This is designed for browser automation where failures are often transient -- an element didn't load in time, a page layout changed, or the agent navigated to the wrong place.

### How It Works

1. A worker publishes an error to `figaro.task.{id}.error`
2. The orchestrator evaluates whether to heal based on a priority chain:
   - **Task-level:** the `self_healing` flag on the specific failed task
   - **Scheduled task-level:** the `self_healing` field on the associated scheduled task (if any)
   - **System-level:** `FIGARO_SELF_HEALING_ENABLED` environment variable (default: `true`)
3. If healing is enabled and retries remain (`< FIGARO_SELF_HEALING_MAX_RETRIES`, default: 2), a healer task is created
4. The healer task contains the original prompt, the error message, and the conversation history (last 50 messages)
5. A supervisor analyzes the failure and decides:
   - **Recoverable** (element not found, timing issues, navigation errors): delegates to a worker with an improved prompt. May use VNC tools to inspect the desktop state first.
   - **Unrecoverable** (invalid credentials, service down, fundamental approach failure): explains why and does not retry.
6. If the retried task also fails and retries remain, another healer is created (up to `max_retries`)

### Loop Prevention

- Tasks with `source="healer"` or `source="optimizer"` are never healed -- only original tasks trigger healing
- The retry chain is tracked via `original_task_id` and `retry_number` to enforce the max retries limit

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FIGARO_SELF_HEALING_ENABLED` | `true` | Enable automatic retry of failed tasks |
| `FIGARO_SELF_HEALING_MAX_RETRIES` | `2` | Maximum healer retries per task chain |

## Self-Learning

Scheduled tasks with `self_learning` enabled automatically optimize their prompts after each completed run. The system analyzes how the task actually executed and rewrites the prompt to be more effective next time.

### How It Works

1. A worker completes a scheduled task
2. The orchestrator checks: does the task have a `scheduled_task_id`, `source="scheduler"`, and `self_learning=True`?
3. If so, it retrieves the conversation history, filters to key message types (assistant, tool_result, result), and caps at the last 50 messages
4. An optimization task is created with the current prompt and conversation history, then assigned to an idle supervisor
5. The supervisor analyzes what happened during execution and calls `update_scheduled_task` to save an improved prompt
6. The next scheduled run uses the improved prompt

### Design Details

- Optimization runs fire-and-forget as a background task -- failures are logged but don't affect the main task completion flow
- Optimization runs after every completed scheduled task run (no throttling)
- The supervisor is instructed to only update the prompt field, preserving schedule, enabled state, and start URL settings
- Self-learning is toggled per scheduled task via a checkbox in the UI

## Security

> [!CAUTION]
> Figaro has **no authentication, no TLS, and no authorization** by design. If you can reach NATS, you own the system. Do not expose any Figaro services to untrusted networks.

Figaro is designed for trusted, isolated environments -- private Docker networks, and in "production" over encrypted overlay networks like Tailscale, Headscale, or Nebula. See [SECURITY.md](SECURITY.md) for a full catalogue of known security trade-offs, attack vectors, and the reasoning behind them.

## Architecture

```
                     +--------------------+
                     |    NATS Server     |
                     |  (+ JetStream)     |
                     |  (+ WebSocket)     |
                     +---------+----------+
       +----------+-----------+-----------+--------------+
       |          |           |           |              |
  +----+----+ +---+----+ +---+-----+ +---+----------+ +-+----------+
  | Worker  | |Orchestr| |Supervis | |   Gateway    | |    UI      |
  |  (x N)  | |  ator  | |   or    | |  (channels)  | |   (SPA)    |
  +---------+ +--------+ +---------+ +--------------+ +------------+
```

All services communicate via NATS (pub/sub + JetStream for durable task events). The UI connects to NATS via WebSocket (`nats.ws`) for both real-time events and mutations (request/reply). The only HTTP endpoints are `GET /api/config` (NATS URL discovery) and `WS /vnc/{worker_id}` (VNC proxy).

## Services

### Orchestrator (`figaro/`)

FastAPI application that manages task lifecycle, worker registry, and scheduling. Serves the built UI as static files. Handles all NATS API request/reply operations (task CRUD, scheduled tasks, help requests, VNC proxy). Persists state to PostgreSQL with Alembic migrations.

**Stack:** Python 3.14, FastAPI, SQLAlchemy (async), asyncpg, asyncvnc, Pillow

### Worker (`figaro-worker/`)

A Claude computer use agent that executes browser automation tasks via the claude-agent-sdk. The agent sees and interacts with a desktop like a human would -- taking screenshots, moving the mouse, clicking elements, typing text, and navigating between applications. It has its own set of skills (custom tools) and can run shell commands. Task progress is streamed to JetStream.

The worker is a standalone service that can run on any machine with a desktop environment. In Docker, it runs inside a containerized Linux desktop (Fluxbox + TigerVNC + Chromium + noVNC) provided by the container image, but it can also run directly on a physical or virtual machine -- see [Connecting External Desktops](#connecting-external-desktops).

**Stack:** Bun (compiled native binary), `@anthropic-ai/claude-agent-sdk`, NATS

A legacy Python-based worker implementation exists in `figaro-worker-legacy/` for reference.

### Supervisor (`figaro-supervisor/`)

A Claude agent that receives complex tasks and delegates them to workers. Can directly observe and interact with any connected desktop via VNC tools -- taking screenshots, typing, clicking, and pressing keys -- without delegating a full task. Uses SDK-native custom tools backed by NATS request/reply for delegation and task management. Supports blocking delegation with inactivity-based timeouts.

**Stack:** Python 3.14, `claude-agent-sdk`, Claude Code CLI

### Gateway (`figaro-gateway/`)

Channel-agnostic messaging gateway that routes messages between external communication channels and the orchestration system. Currently supports Telegram. Implements a `Channel` protocol for adding new channels (WhatsApp, Slack, etc.) with minimal boilerplate.

**Stack:** Python 3.12+, `python-telegram-bot`, NATS

### UI (`figaro-ui/`)

React single-page application providing a dashboard with live desktop grid (noVNC viewers), event stream, chat input for task submission, scheduled task management, and help request handling. Connects directly to NATS via WebSocket for all communication.

**Stack:** React 18, TypeScript, Vite, Zustand, Tailwind CSS, noVNC, `nats.ws`

### Shared NATS Library (`figaro-nats/`)

Reusable Python package providing a typed NATS client wrapper (`NatsConnection`) with JSON serialization, auto-reconnect, and methods for Core NATS and JetStream operations. Also provides subject constants and stream configuration.

**Stack:** Python 3.12+, `nats-py`, Pydantic

### Patchright CLI (`patchright-cli/`)

Browser automation CLI tool built on [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (a Playwright fork for undetected browser automation). Uses a daemon-per-session architecture with Unix socket communication. Installed inside worker containers to provide browser automation capabilities.

**Stack:** Python 3.14, Patchright, OpenAI SDK (for audio transcription)

## Development Setup

### Dev Container (Recommended)

The repository includes a VS Code Dev Container configuration with all dependencies pre-installed:

- Python 3.14, Node.js, Bun, uv
- Desktop environment (VNC) for local testing
- Docker-outside-of-Docker for container builds
- Claude Code CLI

Open the repository in VS Code and select "Reopen in Container."

### Manual Setup

Each service uses [uv](https://docs.astral.sh/uv/) for Python dependency management:

```bash
# Shared NATS library (install first -- other services depend on it)
cd figaro-nats && uv sync --frozen

# Orchestrator
cd figaro && uv sync --frozen

# Worker (Bun)
cd figaro-worker && bun install

# Supervisor
cd figaro-supervisor && uv sync --frozen

# Gateway
cd figaro-gateway && uv sync --frozen

# UI
cd figaro-ui && npm install
```

### Running Services Individually

```bash
# Orchestrator (port 8000)
cd figaro && uv run figaro

# Worker
cd figaro-worker && bun run dev

# Supervisor
cd figaro-supervisor && uv run figaro-supervisor

# Gateway
cd figaro-gateway && uv run figaro-gateway

# UI dev server (port 3000)
cd figaro-ui && npm run dev
```

### Database Migrations

```bash
cd figaro
uv run alembic upgrade head                              # Apply migrations
uv run alembic revision --autogenerate -m "description"  # Create new migration
```

## Configuration

### Environment Variables

| Variable | Service | Description | Default |
|----------|---------|-------------|---------|
| `FIGARO_HOST` | Orchestrator | Bind address | `0.0.0.0` |
| `FIGARO_PORT` | Orchestrator | Listen port | `8000` |
| `FIGARO_DATABASE_URL` | Orchestrator | PostgreSQL connection string | -- |
| `FIGARO_NATS_URL` | Orchestrator | NATS server URL | `nats://localhost:4222` |
| `FIGARO_NATS_WS_URL` | Orchestrator | NATS WebSocket URL for UI | `ws://localhost:8443` |
| `FIGARO_STATIC_DIR` | Orchestrator | Path to built UI files | -- |
| `FIGARO_SELF_HEALING_ENABLED` | Orchestrator | Auto-retry failed tasks | `true` |
| `FIGARO_SELF_HEALING_MAX_RETRIES` | Orchestrator | Max healing retries per task chain | `2` |
| `FIGARO_VNC_PASSWORD` | Orchestrator | VNC password for worker desktops | -- |
| `FIGARO_VNC_PORT` | Orchestrator | VNC display port on workers | `5901` |
| `WORKER_NATS_URL` | Worker | NATS server URL | -- |
| `WORKER_ID` | Worker | Unique worker identifier | -- |
| `WORKER_NOVNC_URL` | Worker | External noVNC URL for UI | -- |
| `SUPERVISOR_NATS_URL` | Supervisor | NATS server URL | -- |
| `GATEWAY_NATS_URL` | Gateway | NATS server URL | -- |
| `GATEWAY_TELEGRAM_BOT_TOKEN` | Gateway | Telegram bot token | -- |
| `GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS` | Gateway | Allowed Telegram chat IDs (JSON array) | -- |
| `VITE_NATS_WS_URL` | UI | NATS WebSocket URL | `ws://localhost:8443` |

### NATS Configuration

The NATS server runs with JetStream enabled, WebSocket on port 8443 (no TLS), and HTTP monitoring on port 8222. See `nats.conf` for the full configuration.

## NATS Subject Design

### Registration and Presence (Core NATS)

```
figaro.register.worker                    # Worker registration
figaro.register.supervisor                # Supervisor registration
figaro.register.gateway                   # Gateway registration
figaro.deregister.{type}.{id}             # Graceful disconnect
figaro.heartbeat.{type}.{id}              # Periodic liveness
```

### Task Assignment (Core NATS, point-to-point)

```
figaro.worker.{worker_id}.task            # Assign task to specific worker
figaro.supervisor.{supervisor_id}.task    # Assign task to specific supervisor
```

### Task Events (JetStream, TASKS stream)

```
figaro.task.{task_id}.assigned            # Task assigned
figaro.task.{task_id}.message             # Streaming SDK output
figaro.task.{task_id}.complete            # Task completed
figaro.task.{task_id}.error               # Task failed
```

### Help Requests (Core NATS)

```
figaro.help.request                       # New help request
figaro.help.{request_id}.response         # Response to help request
```

### API (NATS request/reply)

```
figaro.api.delegate                       # Delegate task to worker
figaro.api.workers                        # List workers
figaro.api.tasks                          # List tasks
figaro.api.tasks.get                      # Get task
figaro.api.tasks.create                   # Create task
figaro.api.tasks.search                   # Search tasks
figaro.api.supervisor.status              # Supervisor status
figaro.api.scheduled-tasks                # List scheduled tasks
figaro.api.scheduled-tasks.{get,create,update,delete,toggle,trigger}
figaro.api.help-requests.respond          # Respond to help request
figaro.api.help-requests.dismiss          # Dismiss help request
figaro.api.vnc                            # VNC operations
```

### Gateway (Core NATS)

```
figaro.gateway.{channel}.send             # Send message via channel
figaro.gateway.{channel}.task             # Task from channel
figaro.gateway.{channel}.question         # Ask question via channel
```

## Message Flows

### Task Submission (UI to Worker)

1. UI sends NATS request to `figaro.api.tasks.create`
2. Orchestrator creates the task, claims an idle worker, publishes to `figaro.worker.{id}.task`
3. Worker executes the task with the Claude Agent SDK
4. Worker streams messages via JetStream (`figaro.task.{id}.message`)
5. Worker publishes completion via JetStream (`figaro.task.{id}.complete`)
6. Orchestrator updates the database and sets the worker idle

### Help Request Flow (Human-in-the-Loop)

1. Worker or supervisor publishes to `figaro.help.request`
2. Orchestrator creates the help request and broadcasts to the UI
3. Gateway routes the help request to a channel (e.g., Telegram)
4. First responder (UI or channel) replies
5. Response is routed back to the requesting agent

## Testing

### Python Services

```bash
cd figaro && uv run pytest              # Orchestrator
cd figaro-nats && uv run pytest         # Shared library
cd figaro-supervisor && uv run pytest   # Supervisor
cd figaro-gateway && uv run pytest      # Gateway
```

Linting and formatting:

```bash
uv run ruff check .
uv run ruff format .
```

### UI

```bash
cd figaro-ui
npm run test           # Run tests
npm run test:watch     # Watch mode
npm run build          # TypeScript check + production build
```

### Worker (Bun)

```bash
cd figaro-worker && bun test
```

## Contributing

Pull requests are welcome! Issues are disabled on this repository -- if you've found a bug or have a feature request, please start a thread in [Discussions](../../discussions) first. Once the approach is agreed upon, feel free to open a PR.
