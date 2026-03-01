---
name: patchright-cli
description: Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from web pages.
allowed-tools: Bash(patchright-cli:*)
---

# Browser Automation with patchright-cli

## Quick start

```bash
# open new browser
patchright-cli open
# navigate to a page
patchright-cli goto https://playwright.dev
# interact with the page using refs from the snapshot
patchright-cli click e15
patchright-cli type "page.click"
patchright-cli press Enter
# take a screenshot (rarely used, as snapshot is more common)
patchright-cli screenshot
# close the browser
patchright-cli close
```

## Commands

### Core

```bash
patchright-cli open
# open and navigate right away
patchright-cli open https://example.com/
patchright-cli goto https://playwright.dev
patchright-cli type "search query"
patchright-cli click e3
patchright-cli dblclick e7
patchright-cli fill e5 "user@example.com"
patchright-cli drag e2 e8
patchright-cli hover e4
patchright-cli select e9 "option-value"
patchright-cli upload ./document.pdf
patchright-cli check e12
patchright-cli uncheck e12
patchright-cli snapshot
patchright-cli snapshot --filename=after-click.yaml
patchright-cli eval "document.title"
patchright-cli eval "el => el.textContent" e5
patchright-cli dialog-accept
patchright-cli dialog-accept "confirmation text"
patchright-cli dialog-dismiss
patchright-cli resize 1920 1080
patchright-cli close
```

### Navigation

```bash
patchright-cli go-back
patchright-cli go-forward
patchright-cli reload
```

### Keyboard

```bash
patchright-cli press Enter
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
patchright-cli mouseup right
patchright-cli mousewheel 0 100
```

### Save as

```bash
patchright-cli screenshot
patchright-cli screenshot e5
patchright-cli screenshot --filename=page.png
patchright-cli pdf --filename=page.pdf
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
patchright-cli state-save
patchright-cli state-save auth.json
patchright-cli state-load auth.json

# Cookies
patchright-cli cookie-list
patchright-cli cookie-list --domain=example.com
patchright-cli cookie-get session_id
patchright-cli cookie-set session_id abc123
patchright-cli cookie-set session_id abc123 --domain=example.com --httpOnly --secure
patchright-cli cookie-delete session_id
patchright-cli cookie-clear

# LocalStorage
patchright-cli localstorage-list
patchright-cli localstorage-get theme
patchright-cli localstorage-set theme dark
patchright-cli localstorage-delete theme
patchright-cli localstorage-clear

# SessionStorage
patchright-cli sessionstorage-list
patchright-cli sessionstorage-get step
patchright-cli sessionstorage-set step 3
patchright-cli sessionstorage-delete step
patchright-cli sessionstorage-clear
```

### Network

```bash
patchright-cli route "**/*.jpg" --status=404
patchright-cli route "https://api.example.com/**" --body='{"mock": true}'
patchright-cli route-list
patchright-cli unroute "**/*.jpg"
patchright-cli unroute
```

### DevTools

```bash
patchright-cli console
patchright-cli console warning
patchright-cli network
patchright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
patchright-cli tracing-start
patchright-cli tracing-stop
patchright-cli video-start
patchright-cli video-stop video.webm
```

## Open parameters
```bash
# Use specific browser when creating session
patchright-cli open --browser=chrome
patchright-cli open --browser=firefox
patchright-cli open --browser=webkit
patchright-cli open --browser=msedge
# Connect to browser via extension
patchright-cli open --extension

# Use persistent profile (by default profile is in-memory)
patchright-cli open --persistent
# Use persistent profile with custom directory
patchright-cli open --profile=/path/to/profile

# Start with config file
patchright-cli open --config=my-config.json

# Close the browser
patchright-cli close
# Delete user data for the default session
patchright-cli delete-data
```

## Snapshots

After each command, patchright-cli provides a snapshot of the current browser state.

```bash
> patchright-cli goto https://example.com
### Page
- Page URL: https://example.com/
- Page Title: Example Domain
### Snapshot
[Snapshot](.patchright-cli/page-2026-02-14T19-22-42-679Z.yml)
```

You can also take a snapshot on demand using `patchright-cli snapshot` command.

If `--filename` is not provided, a new snapshot file is created with a timestamp. Default to automatic file naming, use `--filename=` when artifact is a part of the workflow result.

## Browser Sessions

```bash
# create new browser session named "mysession" with persistent profile
patchright-cli -s=mysession open example.com --persistent
# same with manually specified profile directory (use when requested explicitly)
patchright-cli -s=mysession open example.com --profile=/path/to/profile
patchright-cli -s=mysession click e6
patchright-cli -s=mysession close  # stop a named browser
patchright-cli -s=mysession delete-data  # delete user data for persistent session

patchright-cli list
# Close all browsers
patchright-cli close-all
# Forcefully kill all browser processes
patchright-cli kill-all
```

## Local installation

In some cases user might want to install patchright-cli locally. If running globally available `patchright-cli` binary fails, use `npx patchright-cli` to run the commands. For example:

```bash
npx patchright-cli open https://example.com
npx patchright-cli click e1
```

## Example: Form submission

```bash
patchright-cli open https://example.com/form
patchright-cli snapshot

patchright-cli fill e1 "user@example.com"
patchright-cli fill e2 "password123"
patchright-cli click e3
patchright-cli snapshot
patchright-cli close
```

## Example: Multi-tab workflow

```bash
patchright-cli open https://example.com
patchright-cli tab-new https://example.com/other
patchright-cli tab-list
patchright-cli tab-select 0
patchright-cli snapshot
patchright-cli close
```

## Example: Debugging with DevTools

```bash
patchright-cli open https://example.com
patchright-cli click e4
patchright-cli fill e7 "test"
patchright-cli console
patchright-cli network
patchright-cli close
```

```bash
patchright-cli open https://example.com
patchright-cli tracing-start
patchright-cli click e4
patchright-cli fill e7 "test"
patchright-cli tracing-stop
patchright-cli close
```

## Specific tasks

* **Request mocking** [references/request-mocking.md](references/request-mocking.md)
* **Running Playwright code** [references/running-code.md](references/running-code.md)
* **Browser session management** [references/session-management.md](references/session-management.md)
* **Storage state (cookies, localStorage)** [references/storage-state.md](references/storage-state.md)
* **Test generation** [references/test-generation.md](references/test-generation.md)
* **Tracing** [references/tracing.md](references/tracing.md)
* **Video recording** [references/video-recording.md](references/video-recording.md)
