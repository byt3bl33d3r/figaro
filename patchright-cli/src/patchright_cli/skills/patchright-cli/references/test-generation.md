# Test Generation

Generate Playwright test code automatically as you interact with the browser.

## How It Works

Every action you perform with `patchright-cli` generates corresponding Playwright TypeScript code.
This code appears in the output and can be copied directly into your test files.

## Example Workflow

```bash
# Start a session
patchright-cli open https://example.com/login

# Take a snapshot to see elements
patchright-cli snapshot
# Output shows: e1 [textbox "Email"], e2 [textbox "Password"], e3 [button "Sign In"]

# Fill form fields - generates code automatically
patchright-cli fill e1 "user@example.com"
# Ran Playwright code:
# await page.getByRole('textbox', { name: 'Email' }).fill('user@example.com');

patchright-cli fill e2 "password123"
# Ran Playwright code:
# await page.getByRole('textbox', { name: 'Password' }).fill('password123');

patchright-cli click e3
# Ran Playwright code:
# await page.getByRole('button', { name: 'Sign In' }).click();
```

## Building a Test File

Collect the generated code into a Playwright test:

```typescript
import { test, expect } from '@playwright/test';

test('login flow', async ({ page }) => {
  // Generated code from patchright-cli session:
  await page.goto('https://example.com/login');
  await page.getByRole('textbox', { name: 'Email' }).fill('user@example.com');
  await page.getByRole('textbox', { name: 'Password' }).fill('password123');
  await page.getByRole('button', { name: 'Sign In' }).click();

  // Add assertions
  await expect(page).toHaveURL(/.*dashboard/);
});
```

## Best Practices

### 1. Use Semantic Locators

The generated code uses role-based locators when possible, which are more resilient:

```typescript
// Generated (good - semantic)
await page.getByRole('button', { name: 'Submit' }).click();

// Avoid (fragile - CSS selectors)
await page.locator('#submit-btn').click();
```

### 2. Explore Before Recording

Take snapshots to understand the page structure before recording actions:

```bash
patchright-cli open https://example.com
patchright-cli snapshot
# Review the element structure
patchright-cli click e5
```

### 3. Add Assertions Manually

Generated code captures actions but not assertions. Add expectations in your test:

```typescript
// Generated action
await page.getByRole('button', { name: 'Submit' }).click();

// Manual assertion
await expect(page.getByText('Success')).toBeVisible();
```
