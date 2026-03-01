# Browser Session Management

Run multiple isolated browser sessions concurrently with state persistence.

## Named Browser Sessions

Use `-s` flag to isolate browser contexts:

```bash
# Browser 1: Authentication flow
patchright-cli -s=auth open https://app.example.com/login

# Browser 2: Public browsing (separate cookies, storage)
patchright-cli -s=public open https://example.com

# Commands are isolated by browser session
patchright-cli -s=auth fill e1 "user@example.com"
patchright-cli -s=public snapshot
```

## Browser Session Isolation Properties

Each browser session has independent:
- Cookies
- LocalStorage / SessionStorage
- IndexedDB
- Cache
- Browsing history
- Open tabs

## Browser Session Commands

```bash
# List all browser sessions
patchright-cli list

# Stop a browser session (close the browser)
patchright-cli close                # stop the default browser
patchright-cli -s=mysession close   # stop a named browser

# Stop all browser sessions
patchright-cli close-all

# Forcefully kill all daemon processes (for stale/zombie processes)
patchright-cli kill-all

# Delete browser session user data (profile directory)
patchright-cli delete-data                # delete default browser data
patchright-cli -s=mysession delete-data   # delete named browser data
```

## Environment Variable

Set a default browser session name via environment variable:

```bash
export PLAYWRIGHT_CLI_SESSION="mysession"
patchright-cli open example.com  # Uses "mysession" automatically
```

## Common Patterns

### Concurrent Scraping

```bash
#!/bin/bash
# Scrape multiple sites concurrently

# Start all browsers
patchright-cli -s=site1 open https://site1.com &
patchright-cli -s=site2 open https://site2.com &
patchright-cli -s=site3 open https://site3.com &
wait

# Take snapshots from each
patchright-cli -s=site1 snapshot
patchright-cli -s=site2 snapshot
patchright-cli -s=site3 snapshot

# Cleanup
patchright-cli close-all
```

### A/B Testing Sessions

```bash
# Test different user experiences
patchright-cli -s=variant-a open "https://app.com?variant=a"
patchright-cli -s=variant-b open "https://app.com?variant=b"

# Compare
patchright-cli -s=variant-a screenshot
patchright-cli -s=variant-b screenshot
```

### Persistent Profile

By default, browser profile is kept in memory only. Use `--persistent` flag on `open` to persist the browser profile to disk:

```bash
# Use persistent profile (auto-generated location)
patchright-cli open https://example.com --persistent

# Use persistent profile with custom directory
patchright-cli open https://example.com --profile=/path/to/profile
```

## Default Browser Session

When `-s` is omitted, commands use the default browser session:

```bash
# These use the same default browser session
patchright-cli open https://example.com
patchright-cli snapshot
patchright-cli close  # Stops default browser
```

## Browser Session Configuration

Configure a browser session with specific settings when opening:

```bash
# Open with config file
patchright-cli open https://example.com --config=.playwright/my-cli.json

# Open with specific browser
patchright-cli open https://example.com --browser=firefox

# Open in headed mode
patchright-cli open https://example.com --headed

# Open with persistent profile
patchright-cli open https://example.com --persistent
```

## Best Practices

### 1. Name Browser Sessions Semantically

```bash
# GOOD: Clear purpose
patchright-cli -s=github-auth open https://github.com
patchright-cli -s=docs-scrape open https://docs.example.com

# AVOID: Generic names
patchright-cli -s=s1 open https://github.com
```

### 2. Always Clean Up

```bash
# Stop browsers when done
patchright-cli -s=auth close
patchright-cli -s=scrape close

# Or stop all at once
patchright-cli close-all

# If browsers become unresponsive or zombie processes remain
patchright-cli kill-all
```

### 3. Delete Stale Browser Data

```bash
# Remove old browser data to free disk space
patchright-cli -s=oldsession delete-data
```
