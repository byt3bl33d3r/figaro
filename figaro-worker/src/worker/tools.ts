/**
 * Desktop control tools for the worker agent.
 *
 * Provides direct X11 desktop interaction via xdotool and scrot,
 * exposed as SDK MCP tools using the tool() + createSdkMcpServer pattern.
 * The worker runs inside a container with X11 desktop (DISPLAY=:1).
 */

import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";
import { unlink } from "fs/promises";

const BUTTON_MAP: Record<string, string> = {
  left: "1",
  middle: "2",
  right: "3",
};

interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

async function runCommand(...args: string[]): Promise<CommandResult> {
  const proc = Bun.spawn(args, {
    env: { ...process.env, DISPLAY: ":1" },
    stdout: "pipe",
    stderr: "pipe",
  });
  const stdout = await new Response(proc.stdout).text();
  const stderr = await new Response(proc.stderr).text();
  const exitCode = await proc.exited;
  return { stdout, stderr, exitCode };
}

function result(data: unknown): { content: Array<{ type: "text"; text: string }> } {
  const text =
    typeof data === "object" && data !== null
      ? JSON.stringify(data, null, 2)
      : String(data);
  return { content: [{ type: "text", text }] };
}

function error(msg: string): { content: Array<{ type: "text"; text: string }> } {
  return { content: [{ type: "text", text: `Error: ${msg}` }] };
}

export function createDesktopToolsServer() {
  // tool() expects raw Zod shapes (Record<string, ZodType>), not z.object() wrappers

  const screenshotTool = tool(
    "screenshot",
    "Capture a screenshot of the desktop. Returns the image as base64 PNG.",
    {},
    async () => {
      const tmpPath = `/tmp/screenshot-${Date.now()}.png`;

      try {
        const { stderr, exitCode } = await runCommand(
          "scrot",
          "--overwrite",
          tmpPath,
        );
        if (exitCode !== 0) {
          return error(`scrot failed (rc=${exitCode}): ${stderr}`);
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
      const x = String(args.x);
      const y = String(args.y);
      const button = BUTTON_MAP[args.button] ?? "1";

      const { stderr, exitCode } = await runCommand(
        "xdotool",
        "mousemove",
        "--sync",
        x,
        y,
        "click",
        button,
      );
      if (exitCode !== 0) {
        return error(`xdotool click failed (rc=${exitCode}): ${stderr}`);
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
      const x = String(args.x);
      const y = String(args.y);

      const { stderr, exitCode } = await runCommand(
        "xdotool",
        "mousemove",
        "--sync",
        x,
        y,
      );
      if (exitCode !== 0) {
        return error(`xdotool mousemove failed (rc=${exitCode}): ${stderr}`);
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
      const delay = String(args.delay);

      const { stderr, exitCode } = await runCommand(
        "xdotool",
        "type",
        "--delay",
        delay,
        "--",
        args.text,
      );
      if (exitCode !== 0) {
        return error(`xdotool type failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, length: args.text.length });
    },
  );

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
      const { stderr, exitCode } = await runCommand(
        "xdotool",
        "key",
        "--",
        args.keys,
      );
      if (exitCode !== 0) {
        return error(`xdotool key failed (rc=${exitCode}): ${stderr}`);
      }
      return result({ ok: true, keys: args.keys });
    },
  );

  const scrollTool = tool(
    "scroll",
    "Scroll the mouse wheel up or down.",
    {
      direction: z.string().describe("Scroll direction: 'up' or 'down'"),
      clicks: z.number().int().default(3).describe("Number of scroll clicks"),
    },
    async (args) => {
      const button = args.direction === "up" ? "4" : "5";

      const { stderr, exitCode } = await runCommand(
        "xdotool",
        "click",
        "--repeat",
        String(args.clicks),
        "--delay",
        "50",
        button,
      );
      if (exitCode !== 0) {
        return error(`xdotool scroll failed (rc=${exitCode}): ${stderr}`);
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
      const button = BUTTON_MAP[args.button] ?? "1";

      const dx = end_x - start_x;
      const dy = end_y - start_y;
      const distance = Math.sqrt(dx * dx + dy * dy);

      let steps = args.steps ?? Math.max(10, Math.min(50, Math.floor(distance / 5)));
      steps = Math.max(1, steps);

      const stepDelay = Math.max(0.001, duration_ms / steps / 1000.0);

      const lines: string[] = [
        `xdotool mousemove --sync ${start_x} ${start_y}`,
        `xdotool mousedown ${button}`,
      ];

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

        lines.push(`sleep ${stepDelay.toFixed(4)}`);
        lines.push(`xdotool mousemove ${x} ${y}`);
      }

      lines.push(`xdotool mouseup ${button}`);

      const { stderr, exitCode } = await runCommand(
        "bash",
        "-c",
        lines.join("\n"),
      );
      if (exitCode !== 0) {
        return error(`xdotool drag failed (rc=${exitCode}): ${stderr}`);
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

  return createSdkMcpServer({
    name: "desktop",
    version: "1.0.0",
    tools: [
      screenshotTool,
      mouseClickTool,
      mouseMoveTool,
      typeTextTool,
      pressKeyTool,
      scrollTool,
      mouseDragTool,
    ],
  });
}
