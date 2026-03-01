---
name: recaptcha-bypass
description: Solves reCAPTCHA by clicking the checkbox, with audio challenge fallback
allowed-tools: Bash(patchright-cli:*)
---

## Primary Approach: Click "I am not a robot"

1. Take a screenshot of the desktop using `mcp__desktop__screenshot`
2. Look at the screenshot and identify the reCAPTCHA "I am not a robot" checkbox
3. Click at the checkbox coordinates using `mcp__desktop__click`
4. Wait a moment, then take another screenshot using `mcp__desktop__screenshot` to verify the captcha was solved

If the captcha presents an image challenge after clicking or is still unsolved and you have the `patchright-cli` skill available, fall back to the audio challenge approach below.

## Fallback: Audio Challenge (requires patchright-cli skill)

5. Take a snapshot of the page accessibility tree using `mcp__desktop__snapshot` to find the audio challenge button
6. Click the audio challenge button to switch to the audio captcha
7. Run `patchright-cli transcribe-audio` to transcribe the audio challenge using Whisper
8. Type the transcribed answer into the captcha input field
9. Submit the answer and verify the captcha is solved
