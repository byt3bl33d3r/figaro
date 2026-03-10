import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { PyodideSession } from "./session";
import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";

/**
 * Resolve Pyodide kwargs: when Python calls `func(a, b=1, c=2)`, Pyodide may
 * pass either positional args or a single dict containing all keyword args.
 * This helper detects the dict case and merges with defaults.
 */
function resolveKwargs<T extends Record<string, unknown>>(
  firstOptional: unknown,
  defaults: T,
): T {
  if (typeof firstOptional === "object" && firstOptional !== null && !Array.isArray(firstOptional)) {
    const dict = firstOptional as Record<string, unknown>;
    const result = { ...defaults };
    for (const key of Object.keys(defaults)) {
      if (key in dict && dict[key] !== undefined) {
        (result as Record<string, unknown>)[key] = dict[key];
      }
    }
    return result;
  }
  return defaults;
}

export function createPythonExecTool(natsClient?: NatsClient) {
  let pySession: PyodideSession | null = null;

  const pythonExec = tool(
    "python_exec",
    "Execute Python code in a persistent sandboxed interpreter. " +
      "Variables and imports persist across calls. " +
      "Standard library available (json, re, math, collections, itertools, etc.). " +
      "No network or filesystem access (WASM sandbox)." +
      (natsClient
        ? " The `figaro` module is available for querying task history and managing memories: " +
          "`import figaro; tasks = figaro.list_tasks(status='completed', limit=50)` " +
          "lists tasks with optional status/limit/worker_id filters. " +
          "`figaro.search_tasks('query', status='completed', limit=10)` " +
          "searches task prompts, results, and message content. " +
          "`figaro.get_task('task-id')` retrieves a specific task with full message history. " +
          "`figaro.save_memory('content', metadata={'key': 'value'}, collection='default')` " +
          "saves a memory for future recall. " +
          "`figaro.search_memories('query', limit=10, collection=None)` " +
          "searches memories using hybrid BM25 + vector search. " +
          "`figaro.delete_memory('memory-id')` deletes a memory by ID. " +
          "`figaro.list_memories(collection=None, limit=50)` lists memories."
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

          /** Send a NATS request and parse the JSON response. */
          function natsRequest(
            subject: string,
            payload: Record<string, unknown>,
            extractKey?: string,
          ): Promise<unknown> {
            return nc
              .request(subject, encoder.encode(JSON.stringify(payload)), {
                timeout: 10_000,
              })
              .then((msg: { data: Uint8Array }) => {
                const resp = JSON.parse(decoder.decode(msg.data));
                if (resp.error) {
                  throw new Error(resp.error);
                }
                return extractKey ? (resp[extractKey] ?? []) : resp;
              });
          }

          pySession.registerJsModule("figaro", {
            list_tasks: (
              status?: string | Record<string, unknown> | null,
              limit?: number,
              worker_id?: string,
            ) => {
              const opts = resolveKwargs(status, {
                status: (typeof status === "string" ? status : null) as string | null,
                limit: limit ?? 50,
                worker_id: worker_id ?? (null as string | null),
              });
              return natsRequest(
                Subjects.API_TASKS,
                {
                  status: opts.status ?? undefined,
                  limit: opts.limit,
                  worker_id: opts.worker_id ?? undefined,
                },
                "tasks",
              );
            },
            search_tasks: (
              query: string,
              status?: string | Record<string, unknown> | null,
              limit?: number,
              offset?: number,
            ) => {
              const opts = resolveKwargs(status, {
                status: (typeof status === "string" ? status : null) as string | null,
                limit: limit ?? 20,
                offset: offset ?? 0,
              });
              return natsRequest(
                Subjects.API_TASK_SEARCH,
                {
                  q: query,
                  status: opts.status ?? undefined,
                  limit: opts.limit,
                  offset: opts.offset,
                  include_messages: false,
                },
                "tasks",
              );
            },
            get_task: (task_id: string) => {
              return natsRequest(Subjects.API_TASK_GET, { task_id });
            },
            save_memory: (
              content: string,
              metadata?: Record<string, unknown> | null,
              collection?: string | null,
            ) => {
              // Detect Pyodide kwargs dict: has both "content" and "collection" keys
              const isKwargsDict =
                typeof metadata === "object" && metadata !== null &&
                "content" in metadata && "collection" in metadata;
              const opts = isKwargsDict
                ? {
                    content: (metadata as Record<string, unknown>).content as string,
                    metadata: ((metadata as Record<string, unknown>).metadata ?? {}) as Record<string, unknown>,
                    collection: ((metadata as Record<string, unknown>).collection ?? "default") as string,
                  }
                : {
                    content,
                    metadata: (typeof metadata === "object" && metadata !== null ? metadata : {}) as Record<string, unknown>,
                    collection: collection ?? "default",
                  };
              return natsRequest(Subjects.API_MEMORY_SAVE, {
                content: opts.content,
                metadata: opts.metadata,
                collection: opts.collection,
              });
            },
            search_memories: (
              query: string,
              limit?: number | Record<string, unknown> | null,
              collection?: string | null,
            ) => {
              const opts = resolveKwargs(limit, {
                limit: (typeof limit === "number" ? limit : 10) as number,
                collection: collection ?? (null as string | null),
              });
              return natsRequest(
                Subjects.API_MEMORY_SEARCH,
                {
                  query,
                  limit: opts.limit,
                  collection: opts.collection ?? undefined,
                },
                "results",
              );
            },
            delete_memory: (memory_id: string) => {
              return natsRequest(Subjects.API_MEMORY_DELETE, { memory_id });
            },
            list_memories: (
              collection?: string | Record<string, unknown> | null,
              limit?: number,
            ) => {
              const opts = resolveKwargs(collection, {
                collection: (typeof collection === "string" ? collection : null) as string | null,
                limit: limit ?? 50,
              });
              return natsRequest(
                Subjects.API_MEMORY_LIST,
                {
                  collection: opts.collection ?? undefined,
                  limit: opts.limit,
                },
                "memories",
              );
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
