# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

patchright-cli is a CLI tool for browser automation built on Patchright (a Playwright fork). It uses a **daemon-per-session architecture**: each browser session runs as an independent asyncio background process, and the CLI communicates with it over Unix domain sockets using line-delimited JSON.

## Commands

```bash
uv sync --frozen          # Install dependencies
uv run patchright-cli     # Run CLI
uv run pytest             # Run unit tests (integration tests excluded by default)
uv run pytest -m integration tests/integration/  # Run integration tests (requires real browser)
uv run pytest tests/test_foo.py -k "test_name"  # Single test
uv run ruff check .       # Lint
uv run ruff format .      # Format
```

**After every code change, always run both:**
```bash
uv run ruff check .       # Linting (required, must pass)
uv run pytest             # Tests with coverage (required, must pass)
```

## Testing

410 tests total (367 unit + 43 integration) with pytest + pytest-asyncio + pytest-cov. Coverage is configured in `pyproject.toml` and reports automatically on every `uv run pytest` invocation.

### Unit tests (367 tests)

Unit tests run by default with `uv run pytest`. All Playwright objects are mocked — no real browser needed.

```
tests/
    conftest.py          # Shared fixtures (sessions_dir, output_dir, mock_page, browser_session, etc.)
    test_config.py       # 61 tests — Pydantic models, validators, env overrides, load_config
    test_session.py      # 42 tests — paths, PIDs, alive checks, session listing, cleanup
    test_snapshot.py     # 45 tests — selectors, tree formatting, ref assignment, async snapshot
    test_client.py       # 22 tests — socket I/O, daemon lifecycle, session management
    test_server.py       # 171 tests — all ~60 cmd_* handlers, dispatch, init, logging
    test_cli.py          # 26 tests — arg parsing, main() dispatch for all command types
```

**Mocking strategy:** Playwright objects are mocked via `MagicMock`/`AsyncMock` (no real browser needed). Session paths use `tmp_path` with patched `Path.home()`/`Path.cwd()`. Env vars use `monkeypatch.setenv`. Client socket/subprocess calls are patched at the module level.

### Integration tests (43 tests)

Integration tests launch **real headless Chromium** via Patchright. They are excluded from the default test run via `addopts = ["-m", "not integration"]` in `pyproject.toml`.

```bash
uv run pytest -m integration tests/integration/          # Run all integration tests
uv run pytest -m integration tests/integration/test_snapshot_real.py  # Single file
```

```
tests/integration/
    conftest.py              # Fixtures: browser_session_real, browser_session_persistent, html_page, integration_config
    test_browser_launch.py   # 8 tests — isolated/persistent launch, cmd_open, cmd_close, init_page
    test_daemon_lifecycle.py # 6 tests — subprocess daemon start, Unix socket communication, close/cleanup (synchronous)
    test_network_filtering.py # 5 tests — allowed_origins/blocked_origins with real route interception
    test_page_events.py      # 7 tests — console capture, network logging, dialog queue, popup tracking
    test_snapshot_real.py    # 6 tests — take_snapshot on real DOM, ref injection, click-by-ref
    test_socket_server.py   # 7 tests — in-process run_server() over asyncio Unix sockets
    test_state_load.py       # 4 tests — state save/load with real browser storage
```

**Key design decisions:**
- Every test is marked `@pytest.mark.integration` (registered in `pyproject.toml`)
- No external HTTP server — tests use `data:text/html,...` URLs for deterministic DOM
- Unix socket path length: `test_daemon_lifecycle.py` and `test_socket_server.py` use a local `short_home` fixture with `tempfile.mkdtemp(prefix="prt-")` to stay under the 108-char socket path limit
- `test_daemon_lifecycle.py` is fully synchronous (tests the client API which is sync); all other integration tests are async
- Integration conftest provides `browser_session_real` (isolated, headless, no sandbox) and `html_page` (navigates to a test page with heading, link, form inputs, checkbox, button, select)

### Running tests

```bash
uv run pytest                                             # Unit tests only (default)
uv run pytest -m integration tests/integration/           # Integration tests only
uv run pytest -m "" tests/                                # All tests (override marker filter)
uv run pytest tests/test_server.py -k "test_click"        # Single test by name
uv run pytest --no-cov tests/test_snapshot.py             # Skip coverage for speed
```

## Architecture

```
CLI (cli.py) → Client (client.py) → Unix Socket → Server/Daemon (server.py)
                                                        ↓
                                              BrowserSession (Patchright)
```

**Flow:** The CLI parses commands via argparse, the client either handles them locally (list, close-all, kill-all, logs) or forwards them as JSON to the daemon over a Unix socket. The daemon runs a `BrowserSession` that manages Playwright objects and executes ~60 command handlers (navigation, interaction, snapshots, storage, network, devtools).

### Key modules

- **cli.py** — Argparse command routing. Global flags: `-s/--session`, `--config`. Some commands (list, close-all, kill-all, delete-data, logs) run client-side; all others are forwarded to the daemon.
- **client.py** — Unix socket client + daemon launcher. `start_daemon()` spawns a detached subprocess via `subprocess.Popen(start_new_session=True)`. `send_command()` sends JSON and reads the response with a 120s default timeout.
- **server.py** — Asyncio daemon with `BrowserSession` class. Holds all browser state: Playwright objects, element refs, captured events (console, network, dialogs), active routes, tracing state. Four browser launch strategies: normal launch, persistent context, CDP endpoint, remote endpoint.
- **config.py** — Pydantic settings with priority: `PLAYWRIGHT_MCP_*` env vars > explicit JSON config > `.playwright/cli.config.json` > defaults. `apply_env_overrides()` handles env vars that don't fit pydantic-settings' nested delimiter pattern.
- **session.py** — Manages `~/.patchright-cli/sessions/{name}/` directories containing `server.sock`, `pid`, `daemon.log`, `config.json`. Session name resolves from: CLI arg → `PLAYWRIGHT_CLI_SESSION` env var → "default".
- **snapshot.py** — Generates YAML-like accessibility snapshots via `snapshotForAI`. Elements are assigned `ref=eN` identifiers and resolved at action time using the built-in `aria-ref=eN` selector engine. No DOM injection is performed.

### Element reference system

After a `snapshot` command, elements are assigned refs (e0, e1, ...) by the `snapshotForAI` channel call. Commands like `click`, `fill`, `type` accept a `ref` parameter that resolves to an `aria-ref=eN` selector — a built-in Playwright/Patchright selector engine that maps refs to DOM elements internally. Refs are session-scoped and reset on each snapshot.

**IMPORTANT: Never inject DOM attributes for ref resolution.** A previous implementation injected `data-patchright-ref` attributes on every ref'd element via sequential `locator.evaluate()` calls. This caused ~20s+ hangs on heavy pages (e.g. GitHub with 400+ refs). The `aria-ref=eN` selector engine resolves refs instantly at action time with zero DOM modification. Do not reintroduce DOM injection for element refs.

### Browser defaults

- Headed mode (`headless: False`)
- Chromium sandbox enabled (`chromium_sandbox: True`)
- Non-isolated persistent context by default (`isolated: False`)
- Output written to `.patchright-cli/` in cwd (snapshots, screenshots, traces, videos)

### Anti-detection / stealth

The official `playwright-cli` (@playwright/cli) passes `assistantMode: true` to the Playwright driver protocol at launch time (see `browserContextFactory.js`). This driver-level flag does two things:
1. Adds `AutomationControlled` to `--disable-features` (hides `navigator.webdriver`)
2. Skips adding `--enable-automation`

**Patchright's Python API does not expose `assistantMode`.** It's not in the `launch()` or `launch_persistent_context()` method signatures, and params are built from `locals()`, so there's no way to pass it through the public API. The driver protocol *does* accept it (validated in `protocol.yml`), but it's unreachable from Python without monkey-patching.

**Our workaround** in `server.py` `launch_browser()` achieves the same result via CLI args:
- `ignore_default_args` removes `--enable-automation` (same as `assistantMode` skipping it)
- `--disable-blink-features=AutomationControlled` disables the Blink-level detection (does the actual hiding)
- `--test-type` suppresses the "unsupported command-line flag" infobar triggered by `--disable-blink-features`

Note: `--disable-features=AutomationControlled` alone does NOT hide `navigator.webdriver` — only `--disable-blink-features` works.

**IMPORTANT: Do not use `context.add_init_script()` for ANY purpose.** Any call to `add_init_script()` in patchright breaks Chromium DNS resolution entirely (`ERR_NAME_NOT_RESOLVED` on all domains). Even `add_init_script('void 0;')` triggers this. This is a patchright-specific bug in how it injects scripts via route interception. The CLI arg approach works reliably for automation detection hiding.

**IMPORTANT: `Page.addScriptToEvaluateOnNewDocument` via CDP is silently neutered by patchright.** The CDP command returns success but the script never actually executes. Patchright blocks this to prevent anti-bot detection of CDP domain activation. Do not rely on CDP script injection.

**Codec support (h264):** Playwright's bundled Chromium is compiled without proprietary codecs (h264, AAC). This is a compile-time setting with no runtime flag to override. The default `executable_path` in `config.py` auto-detects system chromium (Debian's `chromium` package), which links against `libopenh264` and has full h264 support. This makes the `VIDEO_CODECS` fingerprint test pass. The `PLAYWRIGHT_MCP_EXECUTABLE_PATH` env var can override this.

**WebGL renderer spoofing in containers:** Running in Docker without GPU passthrough causes Chrome to use SwiftShader (software renderer), producing a detectable `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device ...))` renderer string. The `--webgl-renderer` flag (or `browser.webgl_renderer` config / `PLAYWRIGHT_MCP_WEBGL_RENDERER` env var) spoofs this via route-based HTML injection — intercepting HTML responses and prepending a `<script>` that overrides `WebGLRenderingContext.prototype.getParameter` for params 37445 (vendor) and 37446 (renderer). The vendor is auto-derived from the renderer string. `Function.prototype.toString` is also patched so overridden methods report `[native code]`. This is opt-in (off by default). Example:
```bash
patchright-cli open --webgl-renderer "ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5)"
```
**Why route injection, not CDP or init_script:** `add_init_script` breaks DNS (see above). CDP `addScriptToEvaluateOnNewDocument` is neutered by patchright (see above). Route-based injection (`context.route("**/*", ...)`) intercepts HTML responses and injects the script before the first `<script>` tag, which runs before page JavaScript in practice. Detection vectors: OffscreenCanvas in Web Workers (script doesn't run there), and WebGL rendering output mismatch vs claimed GPU.

## Python Version

Requires Python >= 3.14.
