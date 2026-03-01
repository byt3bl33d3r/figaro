# patchright-cli

A CLI tool for browser automation built on [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) (a [Playwright](https://playwright.dev/) fork). **Drop-in replacement for [`@playwright/cli`](https://github.com/microsoft/playwright-cli)** with enhanced stealth and anti-detection capabilities.

Every command should map 1:1 to its `playwright-cli` counterpart — same arguments, same output format, same environment variables (prefixed `PLAYWRIGHT_MCP_*`). Switch by replacing `playwright-cli` with `patchright-cli` in your scripts.

## Installation

Requires Python >= 3.14.

```bash
# Install with uv
uv add patchright-cli

# Install browser binaries
patchright-cli install-browser
```

## Quick Start

```bash
# Open a browser and navigate
patchright-cli open https://example.com

# Take an accessibility snapshot (returns element refs)
patchright-cli snapshot

# Interact using refs from the snapshot
patchright-cli click e15
patchright-cli fill e3 "search query"
patchright-cli press Enter

# Take a screenshot
patchright-cli screenshot

# Close the browser
patchright-cli close
```

After most commands, patchright-cli automatically returns an updated accessibility snapshot with element refs (`e0`, `e1`, ...) that you use to target elements in subsequent commands.

## Architecture

```
CLI (cli.py) --> Client (client.py) --> Unix Socket --> Daemon (server.py)
                                                            |
                                                   BrowserSession (Patchright)
```

Each browser session runs as an independent background daemon process. The CLI communicates with it over a Unix domain socket using line-delimited JSON. Sessions persist across CLI invocations — open a browser, run commands over time, then close it when done.

Session data is stored at `~/.patchright-cli/sessions/{name}/`:
```
server.sock       # Unix domain socket
pid               # Daemon process ID
config.json       # Session config snapshot
daemon.log        # Daemon log file
browser-data/     # Persistent browser profile (non-isolated mode)
```

Output files (snapshots, screenshots, traces, videos) are written to `.patchright-cli/` in the current working directory.

## Commands

### Global Flags

| Flag | Description |
|------|-------------|
| `-s`, `--session` | Session name (default: `"default"`) |
| `--config` | Path to JSON config file |
| `-v`, `--version` | Print version |

### Browser Lifecycle

```bash
# Open browser (default: headed, persistent profile, Chromium)
patchright-cli open
patchright-cli open https://example.com

# Open with specific browser
patchright-cli open --browser=chrome
patchright-cli open --browser=firefox
patchright-cli open --browser=webkit
patchright-cli open --browser=msedge

# Open with persistent profile
patchright-cli open --persistent
patchright-cli open --profile=/path/to/profile

# Open with WebGL renderer spoofing (for containers)
patchright-cli open --webgl-renderer "ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5)"

# Connect via browser extension
patchright-cli open --extension

# Navigate
patchright-cli goto https://example.com

# Close the browser
patchright-cli close
```

### Interaction

```bash
# Click, double-click, hover
patchright-cli click e5
patchright-cli click e5 right                    # Right-click
patchright-cli click e5 left --modifiers=Shift    # Shift+click
patchright-cli dblclick e7
patchright-cli hover e4

# Type and fill
patchright-cli type "search query"
patchright-cli type "search query" --submit       # Type + Enter
patchright-cli fill e3 "user@example.com"
patchright-cli fill e3 "user@example.com" --submit

# Drag and drop
patchright-cli drag e2 e8

# Form controls
patchright-cli select e9 "option-value"
patchright-cli check e12
patchright-cli uncheck e12
patchright-cli upload ./document.pdf

# Dialogs
patchright-cli dialog-accept
patchright-cli dialog-accept "confirmation text"
patchright-cli dialog-dismiss

# Viewport
patchright-cli resize 1920 1080
```

### Navigation

```bash
patchright-cli go-back
patchright-cli go-forward
patchright-cli reload
```

### Snapshots & Screenshots

```bash
# Accessibility snapshot (YAML-like tree with element refs)
patchright-cli snapshot
patchright-cli snapshot --filename=after-login.yaml

# Screenshot
patchright-cli screenshot
patchright-cli screenshot e5                      # Element screenshot
patchright-cli screenshot --filename=page.png
patchright-cli screenshot --full-page

# PDF
patchright-cli pdf
patchright-cli pdf --filename=page.pdf
```

### Keyboard

```bash
patchright-cli press Enter
patchright-cli press Control+c
patchright-cli press ArrowDown
patchright-cli keydown Shift
patchright-cli keyup Shift
```

### Mouse

```bash
patchright-cli mousemove 150 300
patchright-cli mousedown
patchright-cli mousedown right
patchright-cli mouseup
patchright-cli mousewheel 0 100                   # Scroll down
```

### Tabs

```bash
patchright-cli tab-list
patchright-cli tab-new
patchright-cli tab-new https://example.com/page
patchright-cli tab-close
patchright-cli tab-close 2
patchright-cli tab-select 0
```

### Storage

```bash
# Browser state (cookies + localStorage + sessionStorage)
patchright-cli state-save
patchright-cli state-save auth.json
patchright-cli state-load auth.json

# Cookies
patchright-cli cookie-list
patchright-cli cookie-list --domain=example.com
patchright-cli cookie-get session_id
patchright-cli cookie-set session_id abc123
patchright-cli cookie-set session_id abc123 --domain=example.com --httpOnly --secure --sameSite=Lax
patchright-cli cookie-delete session_id
patchright-cli cookie-clear

# localStorage
patchright-cli localstorage-list
patchright-cli localstorage-get theme
patchright-cli localstorage-set theme dark
patchright-cli localstorage-delete theme
patchright-cli localstorage-clear

# sessionStorage
patchright-cli sessionstorage-list
patchright-cli sessionstorage-get step
patchright-cli sessionstorage-set step 3
patchright-cli sessionstorage-delete step
patchright-cli sessionstorage-clear
```

### Network Interception

```bash
# Block requests
patchright-cli route "**/*.jpg" --status=404

# Mock API responses
patchright-cli route "https://api.example.com/**" --body='{"mock": true}' --content-type=application/json

# Modify headers
patchright-cli route "**/*" --header="X-Custom: value" --remove-header=X-Tracking

# List and remove routes
patchright-cli route-list
patchright-cli unroute "**/*.jpg"
patchright-cli unroute                            # Remove all routes
```

### DevTools

```bash
# Console messages
patchright-cli console                            # All messages (info+)
patchright-cli console warning                    # Warnings and errors only
patchright-cli console --clear                    # Clear captured messages

# Network log
patchright-cli network
patchright-cli network --static                   # Include static assets
patchright-cli network --clear

# Tracing
patchright-cli tracing-start
# ... perform actions ...
patchright-cli tracing-stop                       # Saves trace.zip

# Video recording
patchright-cli video-start
# ... perform actions ...
patchright-cli video-stop
patchright-cli video-stop --filename=recording.webm

# JavaScript evaluation
patchright-cli eval "document.title"
patchright-cli eval "el => el.textContent" e5     # Evaluate on element ref

# Run arbitrary Playwright code
patchright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
```

### Audio Transcription

```bash
# Transcribe audio from the current page (finds <audio> elements)
patchright-cli transcribe-audio

# Transcribe audio from a URL
patchright-cli transcribe-audio --url=https://example.com/audio.mp3
```

Requires the `OPENAI_API_KEY` environment variable (uses OpenAI Whisper).

### Session Management

```bash
# Named sessions
patchright-cli -s=work open https://example.com
patchright-cli -s=work click e6
patchright-cli -s=work close

# List all sessions
patchright-cli list
patchright-cli list --all                         # Include dead sessions

# Close all sessions gracefully
patchright-cli close-all

# Force-kill all daemon processes
patchright-cli kill-all

# Delete session data (browser profile, config, logs)
patchright-cli -s=work delete-data

# View daemon logs
patchright-cli logs
patchright-cli logs -n 50                         # Last 50 lines
patchright-cli logs -f                            # Follow (tail -f)
```

### Utility

```bash
# Install browser binaries
patchright-cli install-browser
patchright-cli install-browser --browser=firefox

# Print current configuration
patchright-cli config-print
```

## Configuration

Configuration is loaded with the following priority (highest to lowest):

1. `PLAYWRIGHT_MCP_*` environment variables
2. `--config` CLI flag (path to JSON file)
3. `.playwright/cli.config.json` in the current directory
4. Built-in defaults

### Config File Format

```json
{
  "browser": {
    "browser_name": "chromium",
    "isolated": false,
    "launch_options": {
      "headless": false,
      "chromium_sandbox": true,
      "executable_path": "/usr/bin/chromium"
    },
    "context_options": {
      "no_viewport": true,
      "viewport": { "width": 1920, "height": 1080 },
      "user_agent": "custom-ua"
    },
    "cdp_endpoint": null,
    "remote_endpoint": null,
    "init_page": ["https://example.com"],
    "webgl_renderer": null
  },
  "network": {
    "allowed_origins": [],
    "blocked_origins": ["ads.example.com"]
  },
  "console": {
    "level": "info"
  },
  "timeouts": {
    "action": 5000,
    "navigation": 60000
  },
  "output_dir": ".patchright-cli",
  "output_mode": "stdout"
}
```

### Environment Variables

All env vars use the `PLAYWRIGHT_MCP_` prefix for compatibility with `@playwright/cli`.

| Variable | Description | Example |
|----------|-------------|---------|
| `PLAYWRIGHT_MCP_BROWSER` | Browser channel | `chrome`, `msedge`, `firefox` |
| `PLAYWRIGHT_MCP_HEADLESS` | Run headless | `1`, `true`, `yes` |
| `PLAYWRIGHT_MCP_VIEWPORT_SIZE` | Viewport dimensions | `1920x1080` |
| `PLAYWRIGHT_MCP_EXECUTABLE_PATH` | Browser binary path | `/usr/bin/chromium` |
| `PLAYWRIGHT_MCP_CDP_ENDPOINT` | Chrome DevTools Protocol URL | `http://localhost:9222` |
| `PLAYWRIGHT_MCP_USER_AGENT` | Custom user agent string | `Mozilla/5.0 ...` |
| `PLAYWRIGHT_MCP_PROXY_SERVER` | Proxy server URL | `http://proxy:8080` |
| `PLAYWRIGHT_MCP_PROXY_BYPASS` | Proxy bypass list | `localhost,127.0.0.1` |
| `PLAYWRIGHT_MCP_NO_SANDBOX` | Disable Chromium sandbox | `1`, `true`, `yes` |
| `PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS` | Ignore HTTPS errors | `1`, `true`, `yes` |
| `PLAYWRIGHT_MCP_INIT_SCRIPT` | Scripts to inject at launch | `/path/a.js;/path/b.js` |
| `PLAYWRIGHT_MCP_INIT_PAGE` | URLs to navigate on launch | `https://a.com;https://b.com` |
| `PLAYWRIGHT_MCP_WEBGL_RENDERER` | WebGL renderer to spoof | `ANGLE (NVIDIA ...)` |
| `PLAYWRIGHT_MCP_TIMEOUT_ACTION` | Action timeout (ms) | `5000` |
| `PLAYWRIGHT_MCP_TIMEOUT_NAVIGATION` | Navigation timeout (ms) | `60000` |
| `PLAYWRIGHT_MCP_ALLOWED_ORIGINS` | Allowed network origins | `example.com;api.example.com` |
| `PLAYWRIGHT_MCP_BLOCKED_ORIGINS` | Blocked network origins | `ads.example.com;tracker.io` |
| `PLAYWRIGHT_MCP_GRANT_PERMISSIONS` | Browser permissions | `geolocation,notifications` |
| `PLAYWRIGHT_MCP_SAVE_VIDEO` | Record video at size | `1280x720` |
| `PLAYWRIGHT_CLI_SESSION` | Default session name | `my-session` |
| `OPENAI_API_KEY` | OpenAI API key (for `transcribe-audio`) | `sk-...` |

## Element Reference System

The snapshot command returns a YAML-like accessibility tree where each interactive element is assigned a ref (`e0`, `e1`, `e2`, ...):

```
- heading "Example Domain" [ref=e0]
- link "More information..." [ref=e1]
- textbox "Search" [ref=e2]
- button "Submit" [ref=e3]
```

Use these refs to target elements in commands:

```bash
patchright-cli click e1          # Click the link
patchright-cli fill e2 "query"   # Fill the search box
patchright-cli click e3          # Click submit
```

Refs are resolved via Patchright's built-in `aria-ref` selector engine — no DOM modification is performed. Refs reset on each new snapshot.

## Browser Launch Strategies

patchright-cli supports four launch strategies:

| Strategy | Trigger | Use Case |
|----------|---------|----------|
| **Persistent context** | Default (`isolated=false`) | Normal browsing with profile persistence |
| **Isolated** | `--isolated` or `isolated: true` | Clean in-memory context, no persistence |
| **CDP endpoint** | `cdp_endpoint` config | Connect to existing Chrome via DevTools Protocol |
| **Remote endpoint** | `remote_endpoint` config | Connect to a remote browser instance |

## Anti-Detection

patchright-cli applies stealth measures automatically on Chromium:

- **Removes `--enable-automation`** — Chromium flag that enables automation-detectable behavior
- **Disables `AutomationControlled` Blink feature** — Hides `navigator.webdriver` from page JavaScript
- **Suppresses automation infobars** — No "Chrome is being controlled by automated test software" banner
- **System Chromium auto-detection** — Uses system-installed Chromium (with h264/AAC codec support) when available
- **WebGL renderer spoofing** (opt-in) — Override the WebGL renderer string to avoid SwiftShader detection in containers

### WebGL Spoofing in Docker

When running in containers without GPU passthrough, Chrome uses SwiftShader which produces a detectable renderer string. Override it:

```bash
patchright-cli open --webgl-renderer "ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5)"
```

Or via environment variable:
```bash
export PLAYWRIGHT_MCP_WEBGL_RENDERER="ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5)"
patchright-cli open
```

## Examples

### Form Login

```bash
patchright-cli open https://example.com/login
patchright-cli snapshot
patchright-cli fill e1 "user@example.com"
patchright-cli fill e2 "password123"
patchright-cli click e3
patchright-cli snapshot
patchright-cli close
```

### Multi-Tab Research

```bash
patchright-cli open https://example.com
patchright-cli tab-new https://example.com/docs
patchright-cli tab-new https://example.com/api
patchright-cli tab-list
patchright-cli tab-select 1
patchright-cli snapshot
patchright-cli close
```

### Debugging a Page

```bash
patchright-cli open https://example.com
patchright-cli tracing-start
patchright-cli click e4
patchright-cli fill e7 "test"
patchright-cli tracing-stop
patchright-cli console
patchright-cli network
patchright-cli close
```

### API Mocking

```bash
patchright-cli open https://example.com
patchright-cli route "https://api.example.com/data" --body='{"items": []}' --content-type=application/json
patchright-cli reload
patchright-cli snapshot
patchright-cli unroute
patchright-cli close
```

### Persistent Sessions

```bash
# Session 1: Log in and save state
patchright-cli -s=myapp open https://app.example.com --persistent
patchright-cli -s=myapp snapshot
patchright-cli -s=myapp fill e1 "user@example.com"
patchright-cli -s=myapp fill e2 "password"
patchright-cli -s=myapp click e3
patchright-cli -s=myapp state-save auth.json
patchright-cli -s=myapp close

# Session 2: Restore state later
patchright-cli -s=myapp open https://app.example.com
patchright-cli -s=myapp state-load auth.json
patchright-cli -s=myapp snapshot
```

## Development

```bash
# Install dependencies
uv sync --frozen

# Run the CLI
uv run patchright-cli

# Run unit tests (367 tests, no browser needed)
uv run pytest

# Run integration tests (43 tests, requires real Chromium)
uv run pytest -m integration tests/integration/

# Run all tests
uv run pytest -m "" tests/

# Lint and format
uv run ruff check .
uv run ruff format .
```