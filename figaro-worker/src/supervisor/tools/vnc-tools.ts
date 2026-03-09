import { tool } from "@anthropic-ai/claude-agent-sdk";
import { JSONCodec } from "nats";
import { z } from "zod/v4";
import type { NatsClient } from "../../nats/client";
import { Subjects } from "../../nats/subjects";
import { result, error, type JsonData } from "../tool-helpers";

const codec = JSONCodec<JsonData>();

export function createVncTools(
  client: NatsClient,
  natsRequest: (subject: string, data: JsonData, timeout?: number) => Promise<JsonData>,
  sourceMetadata?: JsonData | null,
) {
  const workerScale = new Map<string, [number, number]>();
  const takeScreenshot = tool(
    "take_screenshot",
    "Take a screenshot of a worker's desktop. The image is resized to fit within 1280x800. Use the coordinates from this image size when calling click.",
    {
      worker_id: z.string().describe("The worker ID to screenshot"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_VNC,
        {
          action: "screenshot",
          worker_id: args.worker_id,
          max_width: 1280,
          max_height: 800,
        },
        30_000,
      );
      if (response.error) {
        return error(response.error);
      }

      // Store scale factor for coordinate mapping
      const origW = response.original_width ?? 0;
      const origH = response.original_height ?? 0;
      const dispW = response.width ?? origW;
      const dispH = response.height ?? origH;
      if (dispW && dispH) {
        workerScale.set(args.worker_id, [origW / dispW, origH / dispH]);
      }

      return {
        content: [
          {
            type: "image",
            data: response.image,
            mimeType: response.mime_type,
          },
          {
            type: "text",
            text: `Screenshot dimensions: ${dispW}x${dispH} (original: ${origW}x${origH}). Use these dimensions for click coordinates.`,
          },
        ],
      };
    },
  );

  const typeText = tool(
    "type_text",
    "Type text on a worker's desktop.",
    {
      worker_id: z.string().describe("The worker ID to type text on"),
      text: z.string().describe("The text to type"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_VNC,
        { action: "type", worker_id: args.worker_id, text: args.text },
        30_000,
      );
      if (response.error) {
        return error(response.error);
      }
      return result({ ok: true });
    },
  );

  const pressKey = tool(
    "press_key",
    "Press a key combination on a worker's desktop. Optionally hold the key(s) down for a specified duration.",
    {
      worker_id: z.string().describe("The worker ID to press the key on"),
      key: z
        .string()
        .describe("The key to press (e.g. 'Enter', 'Tab', 'a')"),
      modifiers: z
        .array(z.string())
        .optional()
        .describe("Modifier keys to hold (e.g. ['ctrl', 'shift'])"),
      hold_seconds: z
        .number()
        .optional()
        .describe(
          "How long to hold the key(s) down in seconds. If omitted, the key is pressed and released immediately.",
        ),
    },
    async (args) => {
      const payload: JsonData = {
        action: "key",
        worker_id: args.worker_id,
        key: args.key,
        modifiers: args.modifiers ?? [],
      };
      if (args.hold_seconds) {
        payload.hold_seconds = args.hold_seconds;
      }
      const response = await natsRequest(Subjects.API_VNC, payload, 30_000);
      if (response.error) {
        return error(response.error);
      }
      return result({ ok: true });
    },
  );

  const clickTool = tool(
    "click",
    "Click at coordinates on a worker's desktop. Coordinates should match the screenshot dimensions (typically 1280x800).",
    {
      worker_id: z.string().describe("The worker ID to click on"),
      x: z.number().int().describe("X coordinate to click at"),
      y: z.number().int().describe("Y coordinate to click at"),
      button: z
        .string()
        .optional()
        .default("left")
        .describe("Mouse button to click (left, right, middle)"),
    },
    async (args) => {
      const workerId = args.worker_id;
      let x = args.x;
      let y = args.y;
      const scale = workerScale.get(workerId);
      if (scale) {
        x = Math.round(x * scale[0]);
        y = Math.round(y * scale[1]);
      }

      const response = await natsRequest(
        Subjects.API_VNC,
        {
          action: "click",
          worker_id: workerId,
          x,
          y,
          button: args.button ?? "left",
        },
        30_000,
      );
      if (response.error) {
        return error(response.error);
      }
      return result({ ok: true });
    },
  );

  const unlockScreen = tool(
    "unlock_screen",
    "Unlock a worker's desktop lock screen. Desktop credentials are handled " +
      "server-side and are not exposed to this conversation. Use click_screen=True " +
      "to wake the display first, and username=True if a username field is visible.",
    {
      worker_id: z.string().describe("The worker ID to unlock"),
      click_screen: z
        .boolean()
        .optional()
        .default(false)
        .describe("Click centre of screen first to wake the display"),
      username: z
        .boolean()
        .optional()
        .default(false)
        .describe("Type the desktop username before the password"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_VNC,
        {
          action: "unlock",
          worker_id: args.worker_id,
          click_screen: args.click_screen ?? false,
          username: args.username ?? false,
        },
        30_000,
      );
      if (response.error) {
        return error(response.error);
      }
      return result({ ok: true });
    },
  );

  const sendScreenshot = tool(
    "send_screenshot",
    "Take a screenshot of a worker's desktop and send it to the messaging channel " +
      "that originated this task. Only works for tasks received from a messaging channel.",
    {
      worker_id: z.string().describe("The worker ID to screenshot"),
    },
    async (args) => {
      if (
        !sourceMetadata ||
        !sourceMetadata.channel ||
        !sourceMetadata.chat_id
      ) {
        return error(
          "No channel context available — this tool only works for tasks received from a messaging channel",
        );
      }

      const channel = sourceMetadata.channel as string;
      const chatId = sourceMetadata.chat_id;
      const workerId = args.worker_id;

      const response = await natsRequest(
        Subjects.API_VNC,
        {
          action: "screenshot",
          worker_id: workerId,
          max_width: 1280,
          max_height: 800,
        },
        30_000,
      );
      if (response.error) {
        return error(response.error);
      }

      await client.conn.publish(
        Subjects.gatewaySend(channel),
        codec.encode({
          chat_id: chatId,
          image: response.image,
          caption: `Screenshot of ${workerId}`,
        }),
      );

      return result(`Screenshot of ${workerId} sent to ${channel}`);
    },
  );

  return {
    takeScreenshot,
    typeText,
    pressKey,
    clickTool,
    unlockScreen,
    sendScreenshot,
  };
}
