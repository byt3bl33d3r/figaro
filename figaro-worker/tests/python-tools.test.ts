import { describe, test, expect, mock } from "bun:test";

// Must mock claude-agent-sdk since it requires a real CLI binary
mock.module("@anthropic-ai/claude-agent-sdk", () => ({
  tool: (_name: string, _desc: string, _schema: unknown, handler: unknown) => ({
    name: _name,
    description: _desc,
    handler,
  }),
  createSdkMcpServer: (opts: { name: string; version: string; tools: unknown[] }) => ({
    name: opts.name,
    version: opts.version,
    tools: opts.tools,
  }),
}));

import { createDesktopToolsServer } from "../src/worker/tools";

type ToolDef = {
  name: string;
  description: string;
  handler: (args: { code: string }) => Promise<{ content: Array<{ type: string; text: string }> }>;
};

type ServerResult = {
  name: string;
  version: string;
  tools: ToolDef[];
};

function getServer() {
  const { server, destroySession } = createDesktopToolsServer();
  const s = server as unknown as ServerResult;
  const pyTool = s.tools.find((t) => t.name === "python_exec")!;
  return { server: s, destroySession, tool: pyTool };
}

describe("python_exec in desktop tools", () => {
  test("server includes python_exec tool", () => {
    const { server } = getServer();
    const names = server.tools.map((t) => t.name);
    expect(names).toContain("python_exec");
  });

  test("python_exec evaluates expressions", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({ code: "2 + 2" });
      expect(result.content[0].text).toBe("=> 4");
    } finally {
      destroySession();
    }
  });

  test("python_exec formats stdout output", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({ code: "print('hello world')" });
      expect(result.content[0].text).toContain("hello world");
    } finally {
      destroySession();
    }
  });

  test("python_exec formats stderr on error", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({ code: "undefined_var" });
      expect(result.content[0].text).toContain("stderr:");
      expect(result.content[0].text).toContain("NameError");
    } finally {
      destroySession();
    }
  });

  test("python_exec returns '(no output)' for silent statements", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({ code: "x = 1" });
      expect(result.content[0].text).toBe("(no output)");
    } finally {
      destroySession();
    }
  });

  test("python_exec preserves variables across calls", async () => {
    const { tool, destroySession } = getServer();
    try {
      await tool.handler({ code: "my_var = 99" });
      const result = await tool.handler({ code: "my_var + 1" });
      expect(result.content[0].text).toBe("=> 100");
    } finally {
      destroySession();
    }
  });

  test("python_exec shows both stdout and result", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({
        code: "print('side effect')\n42",
      });
      expect(result.content[0].text).toContain("side effect");
      expect(result.content[0].text).toContain("=> 42");
    } finally {
      destroySession();
    }
  });

  test("destroySession allows fresh session on next call", async () => {
    const { tool, destroySession } = getServer();
    try {
      await tool.handler({ code: "session_var = 'first'" });
      destroySession();

      // After destroy, session_var should not exist in the new session
      const result = await tool.handler({ code: "session_var" });
      expect(result.content[0].text).toContain("NameError");
    } finally {
      destroySession();
    }
  });
});

describe("figaro FFI bridge", () => {
  function createMockNatsClient(response: unknown) {
    const encoder = new TextEncoder();
    return {
      conn: {
        request: mock(() =>
          Promise.resolve({
            data: encoder.encode(JSON.stringify(response)),
          }),
        ),
      },
      id: "test-worker",
    } as unknown as import("../src/nats/client").NatsClient;
  }

  function getServerWithNats(natsClient: import("../src/nats/client").NatsClient) {
    const { server, destroySession } = createDesktopToolsServer(natsClient);
    const s = server as unknown as ServerResult;
    const pyTool = s.tools.find((t) => t.name === "python_exec")!;
    return { server: s, destroySession, tool: pyTool };
  }

  test("search_tasks returns results from NATS", async () => {
    const mockTasks = [
      { task_id: "t1", prompt: "test task", status: "completed", result: "done" },
    ];
    const natsClient = createMockNatsClient({ tasks: mockTasks });
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro
tasks = await figaro.search_tasks("test")
tasks_py = tasks.to_py()
import json
result = []
for t in tasks_py:
    result.append({"task_id": t["task_id"], "prompt": t["prompt"]})
json.dumps(result)`,
      });
      expect(result.content[0].text).toContain("t1");
      expect(result.content[0].text).toContain("test task");
      expect(natsClient.conn.request).toHaveBeenCalledTimes(1);
    } finally {
      destroySession();
    }
  });

  test("figaro module not available without NatsClient", async () => {
    const { tool, destroySession } = getServer();
    try {
      const result = await tool.handler({ code: "import figaro" });
      expect(result.content[0].text).toContain("ModuleNotFoundError");
    } finally {
      destroySession();
    }
  });

  test("search_tasks forwards pagination params", async () => {
    const natsClient = createMockNatsClient({ tasks: [] });
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      await tool.handler({
        code: `import figaro
await figaro.search_tasks("query", "completed", 5, 10)`,
      });
      // Verify the NATS request was called with correct payload
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      const decoder = new TextDecoder();
      const payload = JSON.parse(decoder.decode(call[1]));
      expect(payload.q).toBe("query");
      expect(payload.status).toBe("completed");
      expect(payload.limit).toBe(5);
      expect(payload.offset).toBe(10);
      expect(payload.include_messages).toBe(false);
    } finally {
      destroySession();
    }
  });

  test("get_task returns full task from NATS", async () => {
    const mockTask = {
      task_id: "t42",
      prompt: "do something",
      status: "completed",
      result: { summary: "done" },
      messages: [
        { __type__: "assistant", text: "working on it" },
        { __type__: "result", text: "finished" },
      ],
    };
    const natsClient = createMockNatsClient(mockTask);
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro, json
task = await figaro.get_task("t42")
task_py = task.to_py()
json.dumps({"task_id": task_py["task_id"], "message_count": len(task_py["messages"])})`,
      });
      expect(result.content[0].text).toContain("t42");
      expect(result.content[0].text).toContain("2");
      expect(natsClient.conn.request).toHaveBeenCalledTimes(1);
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      expect(call[0]).toBe("figaro.api.tasks.get");
    } finally {
      destroySession();
    }
  });

  test("save_memory sends correct payload", async () => {
    const mockMemory = {
      memory_id: "m1",
      content: "User likes mangos",
      collection: "user_preferences",
      metadata: { category: "food" },
      created_at: "2026-03-10T00:00:00Z",
      updated_at: "2026-03-10T00:00:00Z",
    };
    const natsClient = createMockNatsClient(mockMemory);
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro
mem = await figaro.save_memory("User likes mangos", {"category": "food"}, "user_preferences")
mem_py = mem.to_py()
mem_py["memory_id"]`,
      });
      expect(result.content[0].text).toContain("m1");
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      expect(call[0]).toBe("figaro.api.memories.save");
      const decoder = new TextDecoder();
      const payload = JSON.parse(decoder.decode(call[1]));
      expect(payload.content).toBe("User likes mangos");
      expect(payload.collection).toBe("user_preferences");
    } finally {
      destroySession();
    }
  });

  test("search_memories returns results", async () => {
    const mockResults = {
      results: [
        { memory_id: "m1", content: "User likes mangos", score: 0.95 },
        { memory_id: "m2", content: "User prefers dark mode", score: 0.42 },
      ],
    };
    const natsClient = createMockNatsClient(mockResults);
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro
results = await figaro.search_memories("food preferences", 5)
results_py = results.to_py()
len(results_py)`,
      });
      expect(result.content[0].text).toContain("2");
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      expect(call[0]).toBe("figaro.api.memories.search");
      const decoder = new TextDecoder();
      const payload = JSON.parse(decoder.decode(call[1]));
      expect(payload.query).toBe("food preferences");
      expect(payload.limit).toBe(5);
    } finally {
      destroySession();
    }
  });

  test("delete_memory sends correct payload", async () => {
    const natsClient = createMockNatsClient({ status: "ok", deleted: true });
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      await tool.handler({
        code: `import figaro
await figaro.delete_memory("m1")`,
      });
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      expect(call[0]).toBe("figaro.api.memories.delete");
      const decoder = new TextDecoder();
      const payload = JSON.parse(decoder.decode(call[1]));
      expect(payload.memory_id).toBe("m1");
    } finally {
      destroySession();
    }
  });

  test("list_memories returns memories", async () => {
    const mockMemories = {
      memories: [
        { memory_id: "m1", content: "User likes mangos", collection: "default" },
      ],
    };
    const natsClient = createMockNatsClient(mockMemories);
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro
mems = await figaro.list_memories("default", 10)
mems_py = mems.to_py()
mems_py[0]["content"]`,
      });
      expect(result.content[0].text).toContain("User likes mangos");
      const call = (natsClient.conn.request as ReturnType<typeof mock>).mock.calls[0];
      expect(call[0]).toBe("figaro.api.memories.list");
    } finally {
      destroySession();
    }
  });

  test("nats error response surfaces as Python exception", async () => {
    const natsClient = createMockNatsClient({ error: "Internal error" });
    const { tool, destroySession } = getServerWithNats(natsClient);
    try {
      const result = await tool.handler({
        code: `import figaro
await figaro.save_memory("test")`,
      });
      expect(result.content[0].text).toContain("stderr:");
      expect(result.content[0].text).toContain("Internal error");
    } finally {
      destroySession();
    }
  });
});
