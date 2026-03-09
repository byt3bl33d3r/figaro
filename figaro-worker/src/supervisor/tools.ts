/**
 * Custom SDK tools with NATS-backed orchestrator operations.
 *
 * Ported from figaro-supervisor/src/figaro_supervisor/supervisor/tools.py
 */

import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import { JSONCodec, type Subscription } from "nats";
import { z } from "zod/v4";
import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";
import { traced } from "../tracing/tracer";
import { createPythonExecTool } from "../python/tools";

// biome-ignore lint: JSON payloads are loosely typed
type JsonData = Record<string, any>;

const DELEGATION_INACTIVITY_TIMEOUT = 600;

const codec = JSONCodec<JsonData>();

function result(data: unknown): {
  content: Array<{ type: string; text: string }>;
} {
  const text =
    typeof data === "object" && data !== null
      ? JSON.stringify(data, null, 2)
      : String(data);
  return { content: [{ type: "text", text }] };
}

function error(msg: string): {
  content: Array<{ type: string; text: string }>;
} {
  return { content: [{ type: "text", text: `Error: ${msg}` }] };
}

/**
 * Wait for a delegated task to complete using Core NATS subscriptions.
 *
 * Uses Core NATS (not JetStream consumers) for reliability — JetStream
 * publishes also deliver to Core NATS subscribers on the same subject.
 * Subscriptions should be set up BEFORE the delegation request is sent
 * to prevent race conditions (see delegateToWorker).
 */
export function waitForDelegation(
  client: NatsClient,
  taskId: string,
  apiResult: JsonData,
  inactivityTimeout: number = DELEGATION_INACTIVITY_TIMEOUT,
): {
  promise: Promise<JsonData>;
  subs: Subscription[];
} {
  const subs: Subscription[] = [];
  let timer: ReturnType<typeof setTimeout>;
  let settled = false;

  function cleanup(): void {
    clearTimeout(timer);
    for (const sub of subs) {
      try {
        sub.unsubscribe();
      } catch {
        // ignore
      }
    }
  }

  let settle!: (value: JsonData) => void;
  const innerPromise = new Promise<JsonData>((res) => {
    settle = res;
  });

  // Wrap the inner promise with tracing
  const promise = traced("supervisor.wait_for_delegation", async (span) => {
    span.setAttribute("task.id", taskId);
    return innerPromise;
  });

  function resetTimer(): void {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      console.warn(
        `[supervisor-tools] Worker inactivity timeout for task ${taskId}`,
      );
      settle(
        result({
          ...apiResult,
          status: "timeout",
          message: `Worker had no activity for ${inactivityTimeout} seconds`,
        }),
      );
    }, inactivityTimeout * 1000);
  }

  resetTimer();

  // Subscribe via Core NATS. JetStream publishes also deliver to Core NATS
  // subscribers, so no JetStream consumer needed (same pattern as help-request).
  const nc = client.conn;

  const subComplete = nc.subscribe(Subjects.taskComplete(taskId));
  subs.push(subComplete);
  (async () => {
    for await (const msg of subComplete) {
      try {
        const data = codec.decode(msg.data);
        if (settled) return;
        settled = true;
        cleanup();
        settle(
          result({
            ...apiResult,
            status: "completed",
            worker_result: data.result,
          }),
        );
      } catch (err) {
        console.error(
          `[supervisor-tools] Error processing completion for task ${taskId}:`,
          err,
        );
      }
    }
  })();

  const subError = nc.subscribe(Subjects.taskError(taskId));
  subs.push(subError);
  (async () => {
    for await (const msg of subError) {
      try {
        const data = codec.decode(msg.data);
        if (settled) return;
        settled = true;
        cleanup();
        settle(
          result({
            ...apiResult,
            status: "failed",
            error: data.error ?? "Unknown error",
          }),
        );
      } catch (err) {
        console.error(
          `[supervisor-tools] Error processing error for task ${taskId}:`,
          err,
        );
      }
    }
  })();

  const subMessage = nc.subscribe(Subjects.taskMessage(taskId));
  subs.push(subMessage);
  (async () => {
    for await (const msg of subMessage) {
      try {
        resetTimer();
      } catch {
        // ignore
      }
    }
  })();

  return { promise, subs };
}

export function createSupervisorToolsServer(
  client: NatsClient,
  sourceMetadata?: JsonData | null,
) {
  // Track scale factors from screenshots for coordinate scaling
  const _workerScale = new Map<string, [number, number]>();

  const { pythonExec, destroySession: destroyPySession } = createPythonExecTool(client);

  async function natsRequest(
    subject: string,
    data: JsonData,
    timeout: number = 10_000,
  ): Promise<JsonData> {
    try {
      const resp = await client.request(subject, data, timeout);
      if (resp.error) {
        console.error(
          `[supervisor-tools] NATS request ${subject} returned error: ${resp.error}`,
        );
      }
      return resp;
    } catch (e) {
      console.error(
        `[supervisor-tools] NATS request ${subject} failed (timeout=${timeout}ms): ${e}`,
      );
      return { error: `Request failed: ${e}` };
    }
  }

  const delegateToWorker = tool(
    "delegate_to_worker",
    "Delegate an optimized task to a worker for execution. " +
      "This tool blocks until the worker completes the task, returning the full result. " +
      "Note: desktop-only workers (those with agent_connected=False) cannot receive " +
      "delegated tasks. To interact with desktop-only workers, use the VNC tools " +
      "instead (take_screenshot, type_text, press_key, click).",
    {
      prompt: z.string().describe("The optimized task prompt for the worker"),
      worker_id: z
        .string()
        .optional()
        .describe("Specific worker ID, or omit for auto-assignment"),
    },
    async (args) => {
      // First, send the delegation request to get a task_id
      const resp = await natsRequest(
        Subjects.API_DELEGATE,
        {
          prompt: args.prompt,
          worker_id: args.worker_id,
          supervisor_id: client.id,
        },
        30_000,
      );

      if (resp.error || resp.queued) {
        return result(resp);
      }

      const delegatedTaskId = resp.task_id;
      if (!delegatedTaskId) {
        return error("Failed to create delegation task");
      }

      console.log(
        `[supervisor-tools] Delegated task ${delegatedTaskId}, waiting for completion...`,
      );

      // Set up Core NATS subscriptions and wait for the worker to finish.
      // Uses Core NATS instead of JetStream consumers for reliability —
      // JetStream publishes also deliver to Core NATS subscribers.
      const { promise, subs } = waitForDelegation(
        client,
        delegatedTaskId,
        resp,
      );

      try {
        return await promise;
      } finally {
        for (const sub of subs) {
          try {
            sub.unsubscribe();
          } catch {
            // ignore
          }
        }
      }
    },
  );

  const listWorkers = tool(
    "list_workers",
    "Get list of connected workers and their status. " +
      "Use unlock_screen to unlock lock screens on worker desktops.",
    {},
    async () => {
      const resp = await natsRequest(Subjects.API_WORKERS, {});
      // Strip credentials -- unlock_screen handles them server-side
      const workers =
        typeof resp === "object" && resp !== null
          ? resp.workers ?? resp
          : resp;
      if (Array.isArray(workers)) {
        for (const worker of workers) {
          if (typeof worker === "object" && worker !== null) {
            delete worker.vnc_username;
            delete worker.vnc_password;
          }
        }
      }
      return result(resp);
    },
  );

  const getSupervisorStatus = tool(
    "get_supervisor_status",
    "Get status of all connected supervisors.",
    {},
    async () => {
      return result(await natsRequest(Subjects.API_SUPERVISOR_STATUS, {}));
    },
  );

  const listScheduledTasks = tool(
    "list_scheduled_tasks",
    "Get all scheduled tasks.",
    {},
    async () => {
      return result(await natsRequest(Subjects.API_SCHEDULED_TASKS, {}));
    },
  );

  const getScheduledTask = tool(
    "get_scheduled_task",
    "Get scheduled task details.",
    {
      id: z.string().describe("Scheduled task ID"),
    },
    async (args) => {
      return result(
        await natsRequest(Subjects.API_SCHEDULED_TASK_GET, {
          schedule_id: args.id,
        }),
      );
    },
  );

  const createScheduledTask = tool(
    "create_scheduled_task",
    "Create a new scheduled task. Extracts a short name, the starting URL, and interval from the user request. Use run_at for one-time or deferred tasks.",
    {
      name: z
        .string()
        .describe(
          "Short descriptive name for the task (e.g. 'Google search for Jerry Lewis birthday')",
        ),
      prompt: z.string().describe("Task prompt to execute on schedule"),
      start_url: z
        .string()
        .describe(
          "URL to navigate to before executing the task (e.g. 'https://google.com')",
        ),
      interval_seconds: z
        .number()
        .int()
        .optional()
        .describe(
          "How often to run the task, in seconds (e.g. 180 for every 3 minutes, 3600 for every hour). Use 0 for one-time tasks with run_at. Default: 0 when run_at is set, required otherwise.",
        ),
      run_at: z
        .string()
        .optional()
        .describe(
          "ISO 8601 datetime for when to run the task (e.g. '2026-03-15T10:00:00Z'). If set with interval_seconds=0, it's a one-time task. If set with interval_seconds>0, it's a recurring task starting at this time. If omitted, the task starts immediately.",
        ),
      enabled: z
        .boolean()
        .optional()
        .describe("Whether the task is enabled (default: true)"),
      parallel_workers: z
        .number()
        .int()
        .optional()
        .describe("Number of workers to run in parallel (default: 1)"),
      max_runs: z
        .number()
        .int()
        .optional()
        .describe(
          "Max total runs before the task auto-disables (default: unlimited)",
        ),
      self_learning_max_runs: z
        .number()
        .int()
        .optional()
        .describe("Max self-learning optimization runs (default: 4)"),
    },
    async (args) => {
      const data: JsonData = {
        name: args.name,
        prompt: args.prompt,
        start_url: args.start_url,
        interval_seconds:
          args.interval_seconds ?? (args.run_at !== undefined ? 0 : 3600),
        enabled: args.enabled ?? true,
        parallel_workers: args.parallel_workers ?? 1,
        max_runs: args.max_runs,
        notify_on_complete: true,
        self_learning: true,
        self_healing: true,
        self_learning_max_runs: args.self_learning_max_runs ?? 4,
      };
      if (args.run_at !== undefined) {
        data.run_at = args.run_at;
      }
      return result(
        await natsRequest(Subjects.API_SCHEDULED_TASK_CREATE, data),
      );
    },
  );

  const updateScheduledTask = tool(
    "update_scheduled_task",
    "Update a scheduled task. Only include fields that should change.",
    {
      id: z.string().describe("Scheduled task ID"),
      name: z.string().optional().describe("New name"),
      prompt: z.string().optional().describe("New prompt"),
      start_url: z.string().optional().describe("New starting URL"),
      interval_seconds: z
        .number()
        .int()
        .optional()
        .describe(
          "New interval in seconds (0 = one-time when used with run_at)",
        ),
      run_at: z
        .string()
        .optional()
        .describe(
          "ISO 8601 datetime for when to run the task, or null to clear it",
        ),
      enabled: z.boolean().optional().describe("New enabled state"),
    },
    async (args) => {
      const data: JsonData = { schedule_id: args.id };
      const optionalKeys = [
        "name",
        "prompt",
        "start_url",
        "interval_seconds",
        "run_at",
        "enabled",
      ] as const;
      for (const key of optionalKeys) {
        if (args[key] !== undefined) {
          data[key] = args[key];
        }
      }
      return result(
        await natsRequest(Subjects.API_SCHEDULED_TASK_UPDATE, data, 30_000),
      );
    },
  );

  const deleteScheduledTask = tool(
    "delete_scheduled_task",
    "Delete a scheduled task.",
    {
      id: z.string().describe("Scheduled task ID"),
    },
    async (args) => {
      return result(
        await natsRequest(Subjects.API_SCHEDULED_TASK_DELETE, {
          schedule_id: args.id,
        }),
      );
    },
  );

  const toggleScheduledTask = tool(
    "toggle_scheduled_task",
    "Toggle a scheduled task's enabled/disabled state.",
    {
      id: z.string().describe("Scheduled task ID"),
    },
    async (args) => {
      return result(
        await natsRequest(Subjects.API_SCHEDULED_TASK_TOGGLE, {
          schedule_id: args.id,
        }),
      );
    },
  );

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
        _workerScale.set(args.worker_id, [origW / dispW, origH / dispH]);
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
      const scale = _workerScale.get(workerId);
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

  const sshRunCommand = tool(
    "ssh_run_command",
    "Execute a shell command on a worker via SSH. Returns stdout, stderr, and exit code. " +
      "Only works for workers with ssh:// connection URLs.",
    {
      worker_id: z.string().describe("The worker ID to run the command on"),
      command: z.string().describe("The shell command to execute"),
      timeout: z.number().optional().describe("Command timeout in seconds (default: 30)"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_SSH,
        {
          action: "run_command",
          worker_id: args.worker_id,
          command: args.command,
          timeout: args.timeout,
        },
        Math.max(30_000, ((args.timeout ?? 30) + 5) * 1000),
      );
      if (response.error) {
        return error(response.error);
      }
      return result(response);
    },
  );

  const telnetRunCommand = tool(
    "telnet_run_command",
    "Execute a command on a worker via telnet. Returns the terminal output. " +
      "Only works for workers with telnet:// connection URLs. " +
      "Note: no exit code is available via telnet.",
    {
      worker_id: z.string().describe("The worker ID to run the command on"),
      command: z.string().describe("The command to execute"),
      timeout: z.number().optional().describe("Read timeout in seconds (default: 10)"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_TELNET,
        {
          action: "run_command",
          worker_id: args.worker_id,
          command: args.command,
          timeout: args.timeout,
        },
        Math.max(30_000, ((args.timeout ?? 10) + 5) * 1000),
      );
      if (response.error) {
        return error(response.error);
      }
      return result(response);
    },
  );

  function destroySession(): void {
    destroyPySession();
  }

  const server = createSdkMcpServer({
    name: "orchestrator",
    version: "1.0.0",
    tools: [
      delegateToWorker,
      listWorkers,
      getSupervisorStatus,
      listScheduledTasks,
      getScheduledTask,
      createScheduledTask,
      updateScheduledTask,
      deleteScheduledTask,
      toggleScheduledTask,
      takeScreenshot,
      typeText,
      pressKey,
      clickTool,
      unlockScreen,
      sendScreenshot,
      sshRunCommand,
      telnetRunCommand,
      pythonExec,
    ],
  });

  return { server, destroySession };
}
