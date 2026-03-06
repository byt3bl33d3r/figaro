import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { PyodideSession } from "./session";
import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";

export function createPythonExecTool(natsClient?: NatsClient) {
  let pySession: PyodideSession | null = null;

  const pythonExec = tool(
    "python_exec",
    "Execute Python code in a persistent sandboxed interpreter. " +
      "Variables and imports persist across calls. " +
      "Standard library available (json, re, math, collections, itertools, etc.). " +
      "No network or filesystem access (WASM sandbox)." +
      (natsClient
        ? " The `figaro` module is available for querying task history: " +
          "`import figaro; tasks = figaro.list_tasks(status='completed', limit=50)` " +
          "lists tasks with optional status/limit/worker_id filters. " +
          "`figaro.search_tasks('query', status='completed', limit=10)` " +
          "searches task prompts, results, and message content. " +
          "`figaro.get_task('task-id')` retrieves a specific task with full message history."
        : ""),
    { code: z.string().describe("Python code to execute") },
    async (args) => {
      if (!pySession) {
        pySession = new PyodideSession();
        await pySession.initialize();

        if (natsClient) {
          const nc = natsClient.conn;
          const encoder = new TextEncoder();
          const decoder = new TextDecoder();
          pySession.registerJsModule("figaro", {
            list_tasks: (
              status?: string | Record<string, unknown> | null,
              limit?: number,
              worker_id?: string,
            ) => {
              let opts = { status: null as string | null, limit: 50, worker_id: null as string | null };
              if (typeof status === "object" && status !== null) {
                opts = {
                  status: (status.status as string) ?? null,
                  limit: (status.limit as number) ?? 50,
                  worker_id: (status.worker_id as string) ?? null,
                };
              } else {
                opts.status = status ?? null;
                opts.limit = limit ?? 50;
                opts.worker_id = worker_id ?? null;
              }
              const payload = JSON.stringify({
                status: opts.status ?? undefined,
                limit: opts.limit,
                worker_id: opts.worker_id ?? undefined,
              });
              return nc
                .request(Subjects.API_TASKS, encoder.encode(payload), {
                  timeout: 10_000,
                })
                .then((msg: { data: Uint8Array }) => {
                  const resp = JSON.parse(decoder.decode(msg.data));
                  return resp.tasks ?? [];
                });
            },
            search_tasks: (
              query: string,
              status?: string | Record<string, unknown> | null,
              limit?: number,
              offset?: number,
            ) => {
              let opts = { status: null as string | null, limit: 20, offset: 0 };
              if (typeof status === "object" && status !== null) {
                opts = {
                  status: (status.status as string) ?? null,
                  limit: (status.limit as number) ?? 20,
                  offset: (status.offset as number) ?? 0,
                };
              } else {
                opts.status = status ?? null;
                opts.limit = limit ?? 20;
                opts.offset = offset ?? 0;
              }
              const payload = JSON.stringify({
                q: query,
                status: opts.status ?? undefined,
                limit: opts.limit,
                offset: opts.offset,
                include_messages: false,
              });
              return nc
                .request(Subjects.API_TASK_SEARCH, encoder.encode(payload), {
                  timeout: 10_000,
                })
                .then((msg: { data: Uint8Array }) => {
                  const resp = JSON.parse(decoder.decode(msg.data));
                  return resp.tasks ?? [];
                });
            },
            get_task: (task_id: string) => {
              const payload = JSON.stringify({ task_id });
              return nc
                .request(Subjects.API_TASK_GET, encoder.encode(payload), {
                  timeout: 10_000,
                })
                .then((msg: { data: Uint8Array }) => {
                  const resp = JSON.parse(decoder.decode(msg.data));
                  return resp;
                });
            },
          });
        }
      }
      const { stdout, stderr, result: execResult } = await pySession.execute(args.code);

      const parts: string[] = [];
      if (stdout) parts.push(stdout);
      if (stderr) parts.push(`stderr:\n${stderr}`);
      if (execResult !== null) parts.push(`=> ${execResult}`);
      const text = parts.length > 0 ? parts.join("\n\n") : "(no output)";

      return { content: [{ type: "text" as const, text }] };
    },
  );

  function destroySession(): void {
    pySession?.destroy();
    pySession = null;
  }

  return { pythonExec, destroySession };
}
