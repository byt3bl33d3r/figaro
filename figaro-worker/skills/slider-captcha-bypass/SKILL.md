---
name: slider-captcha-bypass
description: Solves slider captchas by dragging, with audio challenge fallback
allowed-tools: Bash(patchright-cli:*)
---

## Primary Approach: Slider Drag

1. Take a screenshot of the desktop using `mcp__desktop__screenshot`
2. Look at the screenshot and identify the coordinates of the slider
3. Use the `mcp__desktop__mouse_drag` tool to drag the slider and solve the captcha
4. Take another screenshot using `mcp__desktop__screenshot` to verify the captcha was solved

If the captcha is still present after dragging and you have the `patchright-cli` skill available, fall back to the audio challenge approach below.

## Fallback: Audio Challenge (requires patchright-cli skill)

5. Take a snapshot of the page accessibility tree using `mcp__desktop__snapshot` to find the audio challenge button
6. Click the audio challenge button to switch to the audio captcha
7. Run `patchright-cli transcribe-audio` to transcribe the audio challenge using Whisper
8. Type the transcribed answer into the captcha input field
9. Submit the answer and verify the captcha is solved
