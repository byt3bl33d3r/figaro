import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import type { NatsClient } from "../../nats/client";
import { Subjects } from "../../nats/subjects";
import { result, error, type JsonData } from "../tool-helpers";
import { waitForDelegation } from "../delegation";

export function createDelegationTools(
  client: NatsClient,
  natsRequest: (subject: string, data: JsonData, timeout?: number) => Promise<JsonData>,
) {
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

  return { delegateToWorker, listWorkers, getSupervisorStatus };
}
