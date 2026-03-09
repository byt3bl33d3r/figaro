import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { Subjects } from "../../nats/subjects";
import { result, type JsonData } from "../tool-helpers";

export function createTaskTools(
  natsRequest: (subject: string, data: JsonData, timeout?: number) => Promise<JsonData>,
) {
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

  return {
    listScheduledTasks,
    getScheduledTask,
    createScheduledTask,
    updateScheduledTask,
    deleteScheduledTask,
    toggleScheduledTask,
  };
}
