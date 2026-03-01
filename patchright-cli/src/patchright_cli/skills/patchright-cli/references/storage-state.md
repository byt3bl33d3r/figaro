# Storage Management

Manage cookies, localStorage, sessionStorage, and browser storage state.

## Storage State

Save and restore complete browser state including cookies and storage.

### Save Storage State

```bash
# Save to auto-generated filename (storage-state-{timestamp}.json)
patchright-cli state-save

# Save to specific filename
patchright-cli state-save my-auth-state.json
```

### Restore Storage State

```bash
# Load storage state from file
patchright-cli state-load my-auth-state.json

# Reload page to apply cookies
patchright-cli open https://example.com
```

### Storage State File Format

The saved file contains:

```json
{
  "cookies": [
    {
      "name": "session_id",
      "value": "abc123",
      "domain": "example.com",
      "path": "/",
      "expires": 1735689600,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax"
    }
  ],
  "origins": [
    {
      "origin": "https://example.com",
      "localStorage": [
        { "name": "theme", "value": "dark" },
        { "name": "user_id", "value": "12345" }
      ]
    }
  ]
}
```

## Cookies

### List All Cookies

```bash
patchright-cli cookie-list
```

### Filter Cookies by Domain

```bash
patchright-cli cookie-list --domain=example.com
```

### Filter Cookies by Path

```bash
patchright-cli cookie-list --path=/api
```

### Get Specific Cookie

```bash
patchright-cli cookie-get session_id
```

### Set a Cookie

```bash
# Basic cookie
patchright-cli cookie-set session abc123

# Cookie with options
patchright-cli cookie-set session abc123 --domain=example.com --path=/ --httpOnly --secure --sameSite=Lax

# Cookie with expiration (Unix timestamp)
patchright-cli cookie-set remember_me token123 --expires=1735689600
```

### Delete a Cookie

```bash
patchright-cli cookie-delete session_id
```

### Clear All Cookies

```bash
patchright-cli cookie-clear
```

### Advanced: Multiple Cookies or Custom Options

For complex scenarios like adding multiple cookies at once, use `run-code`:

```bash
patchright-cli run-code "async page => {
  await page.context().addCookies([
    { name: 'session_id', value: 'sess_abc123', domain: 'example.com', path: '/', httpOnly: true },
    { name: 'preferences', value: JSON.stringify({ theme: 'dark' }), domain: 'example.com', path: '/' }
  ]);
}"
```

## Local Storage

### List All localStorage Items

```bash
patchright-cli localstorage-list
```

### Get Single Value

```bash
patchright-cli localstorage-get token
```

### Set Value

```bash
patchright-cli localstorage-set theme dark
```

### Set JSON Value

```bash
patchright-cli localstorage-set user_settings '{"theme":"dark","language":"en"}'
```

### Delete Single Item

```bash
patchright-cli localstorage-delete token
```

### Clear All localStorage

```bash
patchright-cli localstorage-clear
```

### Advanced: Multiple Operations

For complex scenarios like setting multiple values at once, use `run-code`:

```bash
patchright-cli run-code "async page => {
  await page.evaluate(() => {
    localStorage.setItem('token', 'jwt_abc123');
    localStorage.setItem('user_id', '12345');
    localStorage.setItem('expires_at', Date.now() + 3600000);
  });
}"
```

## Session Storage

### List All sessionStorage Items

```bash
patchright-cli sessionstorage-list
```

### Get Single Value

```bash
patchright-cli sessionstorage-get form_data
```

### Set Value

```bash
patchright-cli sessionstorage-set step 3
```

### Delete Single Item

```bash
patchright-cli sessionstorage-delete step
```

### Clear sessionStorage

```bash
patchright-cli sessionstorage-clear
```

## IndexedDB

### List Databases

```bash
patchright-cli run-code "async page => {
  return await page.evaluate(async () => {
    const databases = await indexedDB.databases();
    return databases;
  });
}"
```

### Delete Database

```bash
patchright-cli run-code "async page => {
  await page.evaluate(() => {
    indexedDB.deleteDatabase('myDatabase');
  });
}"
```

## Common Patterns

### Authentication State Reuse

```bash
# Step 1: Login and save state
patchright-cli open https://app.example.com/login
patchright-cli snapshot
patchright-cli fill e1 "user@example.com"
patchright-cli fill e2 "password123"
patchright-cli click e3

# Save the authenticated state
patchright-cli state-save auth.json

# Step 2: Later, restore state and skip login
patchright-cli state-load auth.json
patchright-cli open https://app.example.com/dashboard
# Already logged in!
```

### Save and Restore Roundtrip

```bash
# Set up authentication state
patchright-cli open https://example.com
patchright-cli eval "() => { document.cookie = 'session=abc123'; localStorage.setItem('user', 'john'); }"

# Save state to file
patchright-cli state-save my-session.json

# ... later, in a new session ...

# Restore state
patchright-cli state-load my-session.json
patchright-cli open https://example.com
# Cookies and localStorage are restored!
```

## Security Notes

- Never commit storage state files containing auth tokens
- Add `*.auth-state.json` to `.gitignore`
- Delete state files after automation completes
- Use environment variables for sensitive data
- By default, sessions run in-memory mode which is safer for sensitive operations
