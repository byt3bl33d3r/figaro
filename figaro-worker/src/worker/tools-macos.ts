/**
 * macOS-native desktop control tools.
 *
 * Uses screencapture, osascript (JXA/AppleScript), and CoreGraphics
 * for desktop interaction on macOS without any third-party dependencies.
 * Requires Accessibility permissions (System Settings > Privacy & Security > Accessibility).
 */

import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";
import { unlink } from "fs/promises";
import type { CommandResult } from "./tools";
import { BUTTON_MAP, result, error } from "./tools";

async function runCommand(...args: string[]): Promise<CommandResult> {
  const proc = Bun.spawn(args, {
    stdout: "pipe",
    stderr: "pipe",
  });
  const stdout = await new Response(proc.stdout).text();
  const stderr = await new Response(proc.stderr).text();
  const exitCode = await proc.exited;
  return { stdout, stderr, exitCode };
}

async function runJxa(script: string): Promise<CommandResult> {
  return runCommand("osascript", "-l", "JavaScript", "-e", script);
}

async function runAppleScript(script: string): Promise<CommandResult> {
  return runCommand("osascript", "-e", script);
}

export function createMacosTools() {
  const screenshotTool = tool(
    "screenshot",
    "Capture a screenshot of the desktop. Returns the image as base64 PNG.",
    {},
    async () => {
      const tmpPath = `/tmp/screenshot-${Date.now()}.png`;
      try {
        const { stderr, exitCode } = await runCommand(
          "screencapture",
          "-x",
          tmpPath,
        );
        if (exitCode !== 0) {
          return error(`screencapture failed (rc=${exitCode}): ${stderr}`);
        }
        const file = Bun.file(tmpPath);
        const bytes = await file.arrayBuffer();
        if (bytes.byteLength === 0) {
          return error("Screenshot file is empty");
        }
        const b64 = Buffer.from(bytes).toString("base64");
        return {
          content: [
            {
              type: "image" as const,
              data: b64,
              mimeType: "image/png" as const,
            },
          ],
        };
      } finally {
        await unlink(tmpPath).catch(() => {});
      }
    },
  );

  const mouseClickTool = tool(
    "mouse_click",
    "Click the mouse at the specified coordinates.",
    {
      x: z.number().int().describe("X coordinate to click at"),
      y: z.number().int().describe("Y coordinate to click at"),
      button: z
        .string()
        .default("left")
        .describe("Mouse button: left, middle, or right"),
    },
    async (args) => {
      const buttonTypes: Record<string, { down: string; up: string }> = {
        left: {
          down: "$.kCGEventLeftMouseDown",
          up: "$.kCGEventLeftMouseUp",
        },
        middle: {
          down: "$.kCGEventOtherMouseDown",
          up: "$.kCGEventOtherMouseUp",
        },
        right: {
          down: "$.kCGEventRightMouseDown",
          up: "$.kCGEventRightMouseUp",
        },
      };
      const bt = buttonTypes[args.button] ?? buttonTypes.left;
      const script = `
ObjC.import('CoreGraphics');
var point = $.CGPointMake(${args.x}, ${args.y});
var move = $.CGEventCreateMouseEvent(null, $.kCGEventMouseMoved, point, 0);
$.CGEventPost($.kCGHIDEventTap, move);
var down = $.CGEventCreateMouseEvent(null, ${bt.down}, point, 0);
$.CGEventPost($.kCGHIDEventTap, down);
delay(0.05);
var up = $.CGEventCreateMouseEvent(null, ${bt.up}, point, 0);
$.CGEventPost($.kCGHIDEventTap, up);
"ok"`;
      const { stderr, exitCode } = await runJxa(script);
      if (exitCode !== 0) {
        return error(`mouse click failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, x: args.x, y: args.y });
    },
  );

  const mouseMoveTool = tool(
    "mouse_move",
    "Move the mouse to the specified coordinates.",
    {
      x: z.number().int().describe("X coordinate to move to"),
      y: z.number().int().describe("Y coordinate to move to"),
    },
    async (args) => {
      const script = `
ObjC.import('CoreGraphics');
var point = $.CGPointMake(${args.x}, ${args.y});
var event = $.CGEventCreateMouseEvent(null, $.kCGEventMouseMoved, point, 0);
$.CGEventPost($.kCGHIDEventTap, event);
"ok"`;
      const { stderr, exitCode } = await runJxa(script);
      if (exitCode !== 0) {
        return error(`mouse move failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, x: args.x, y: args.y });
    },
  );

  const typeTextTool = tool(
    "type_text",
    "Type text on the desktop keyboard.",
    {
      text: z.string().describe("The text to type"),
      delay: z
        .number()
        .int()
        .default(50)
        .describe("Delay in milliseconds between keystrokes"),
    },
    async (args) => {
      const escaped = args.text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      const delaySec = args.delay / 1000;
      const script = `tell application "System Events" to keystroke "${escaped}" with key delay ${delaySec}`;
      const { stderr, exitCode } = await runAppleScript(script);
      if (exitCode !== 0) {
        return error(`type text failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, length: args.text.length });
    },
  );

  const MODIFIER_MAP: Record<string, string> = {
    ctrl: "control down",
    control: "control down",
    alt: "option down",
    option: "option down",
    shift: "shift down",
    super: "command down",
    command: "command down",
    cmd: "command down",
    meta: "command down",
  };

  const KEY_CODE_MAP: Record<string, number> = {
    Return: 36,
    Enter: 36,
    Tab: 48,
    Escape: 53,
    BackSpace: 51,
    Delete: 117,
    Up: 126,
    Down: 125,
    Left: 123,
    Right: 124,
    space: 49,
    Home: 115,
    End: 119,
    Page_Up: 116,
    Page_Down: 121,
    F1: 122,
    F2: 120,
    F3: 99,
    F4: 118,
    F5: 96,
    F6: 97,
    F7: 98,
    F8: 100,
    F9: 101,
    F10: 109,
    F11: 103,
    F12: 111,
  };

  const pressKeyTool = tool(
    "press_key",
    "Press a key or key combination (e.g. 'ctrl+c', 'Return', 'alt+F4').",
    {
      keys: z
        .string()
        .describe(
          "Key combination to press (e.g. 'ctrl+c', 'Return', 'alt+Tab')",
        ),
    },
    async (args) => {
      const parts = args.keys.split("+");
      const modifiers: string[] = [];
      let key = "";

      for (const part of parts) {
        const mod = MODIFIER_MAP[part.toLowerCase()];
        if (mod) {
          modifiers.push(mod);
        } else {
          key = part;
        }
      }

      const modClause =
        modifiers.length > 0 ? ` using {${modifiers.join(", ")}}` : "";
      const keyCode = KEY_CODE_MAP[key];

      let script: string;
      if (keyCode !== undefined) {
        script = `tell application "System Events" to key code ${keyCode}${modClause}`;
      } else {
        const escaped = key.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        script = `tell application "System Events" to keystroke "${escaped}"${modClause}`;
      }

      const { stderr, exitCode } = await runAppleScript(script);
      if (exitCode !== 0) {
        return error(`press key failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, keys: args.keys });
    },
  );

  const scrollTool = tool(
    "scroll",
    "Scroll the mouse wheel up or down.",
    {
      direction: z.string().describe("Scroll direction: 'up' or 'down'"),
      clicks: z
        .number()
        .int()
        .default(3)
        .describe("Number of scroll clicks"),
    },
    async (args) => {
      const delta = args.direction === "up" ? args.clicks : -args.clicks;
      const script = `
ObjC.import('CoreGraphics');
var event = $.CGEventCreateScrollWheelEvent(null, 0, 1, ${delta});
$.CGEventPost($.kCGHIDEventTap, event);
"ok"`;
      const { stderr, exitCode } = await runJxa(script);
      if (exitCode !== 0) {
        return error(`scroll failed (rc=${exitCode}): ${stderr}`);
      }
      return result({
        ok: true,
        direction: args.direction,
        clicks: args.clicks,
      });
    },
  );

  const mouseDragTool = tool(
    "mouse_drag",
    "Drag the mouse from one position to another with smooth, human-like movement. " +
      "The drag uses eased interpolation so the cursor accelerates and decelerates naturally.",
    {
      start_x: z.number().int().describe("Starting X coordinate"),
      start_y: z.number().int().describe("Starting Y coordinate"),
      end_x: z.number().int().describe("Ending X coordinate"),
      end_y: z.number().int().describe("Ending Y coordinate"),
      button: z
        .string()
        .default("left")
        .describe("Mouse button: left, middle, or right"),
      duration_ms: z
        .number()
        .int()
        .default(600)
        .describe("Total duration of the drag in milliseconds"),
      steps: z
        .number()
        .int()
        .optional()
        .describe(
          "Number of intermediate movement steps (auto-calculated from distance if omitted)",
        ),
    },
    async (args) => {
      const { start_x, start_y, end_x, end_y, duration_ms } = args;

      const buttonTypes: Record<
        string,
        { down: string; drag: string; up: string }
      > = {
        left: {
          down: "$.kCGEventLeftMouseDown",
          drag: "$.kCGEventLeftMouseDragged",
          up: "$.kCGEventLeftMouseUp",
        },
        middle: {
          down: "$.kCGEventOtherMouseDown",
          drag: "$.kCGEventOtherMouseDragged",
          up: "$.kCGEventOtherMouseUp",
        },
        right: {
          down: "$.kCGEventRightMouseDown",
          drag: "$.kCGEventRightMouseDragged",
          up: "$.kCGEventRightMouseUp",
        },
      };
      const bt = buttonTypes[args.button] ?? buttonTypes.left;

      const dx = end_x - start_x;
      const dy = end_y - start_y;
      const distance = Math.sqrt(dx * dx + dy * dy);

      let steps =
        args.steps ?? Math.max(10, Math.min(50, Math.floor(distance / 5)));
      steps = Math.max(1, steps);

      const stepDelay = Math.max(0.001, duration_ms / steps / 1000.0);

      const moveLines: string[] = [];
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        let eased: number;
        if (t < 0.5) {
          eased = 4 * t * t * t;
        } else {
          eased = 1 - Math.pow(-2 * t + 2, 3) / 2;
        }
        const x = Math.floor(start_x + dx * eased);
        const y = Math.floor(start_y + dy * eased);
        moveLines.push(`  var p = $.CGPointMake(${x}, ${y});`);
        moveLines.push(
          `  var drag = $.CGEventCreateMouseEvent(null, ${bt.drag}, p, 0);`,
        );
        moveLines.push(`  $.CGEventPost($.kCGHIDEventTap, drag);`);
        moveLines.push(`  delay(${stepDelay.toFixed(4)});`);
      }

      const script = `
ObjC.import('CoreGraphics');
var startPt = $.CGPointMake(${start_x}, ${start_y});
var endPt = $.CGPointMake(${end_x}, ${end_y});
var move = $.CGEventCreateMouseEvent(null, $.kCGEventMouseMoved, startPt, 0);
$.CGEventPost($.kCGHIDEventTap, move);
delay(0.05);
var down = $.CGEventCreateMouseEvent(null, ${bt.down}, startPt, 0);
$.CGEventPost($.kCGHIDEventTap, down);
delay(0.05);
${moveLines.join("\n")}
var up = $.CGEventCreateMouseEvent(null, ${bt.up}, endPt, 0);
$.CGEventPost($.kCGHIDEventTap, up);
"ok"`;

      const { stderr, exitCode } = await runJxa(script);
      if (exitCode !== 0) {
        return error(`mouse drag failed (rc=${exitCode}): ${stderr}`);
      }
      return result({
        ok: true,
        from: { x: start_x, y: start_y },
        to: { x: end_x, y: end_y },
        steps,
        duration_ms,
      });
    },
  );

  return [
    screenshotTool,
    mouseClickTool,
    mouseMoveTool,
    typeTextTool,
    pressKeyTool,
    scrollTool,
    mouseDragTool,
  ];
}
