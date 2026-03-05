import { describe, test, expect, mock, beforeEach } from "bun:test";

// --- Mock nats module ---
mock.module("nats", () => ({
  connect: mock(() => Promise.resolve({})),
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
  RetentionPolicy: { Limits: 0 },
  DeliverPolicy: { New: "new" },
}));

// --- Mock claude-agent-sdk ---
let mockStreamMessages: Array<Record<string, unknown>> = [];
let mockQueryError: Error | null = null;

const mockClose = mock(() => {});

const mockQuery = mock((_params: any) => {
  const messages = [...mockStreamMessages];
  const error = mockQueryError;
  const gen = {
    async *[Symbol.asyncIterator]() {
      for (const msg of messages) {
        yield msg;
      }
      if (error) {
        throw error;
      }
    },
    close: mockClose,
    next: () => Promise.resolve({ done: true, value: undefined }),
    return: () => Promise.resolve({ done: true, value: undefined }),
    throw: () => Promise.resolve({ done: true, value: undefined }),
  };
  return gen;
});

mock.module("@anthropic-ai/claude-agent-sdk", () => ({
  query: mockQuery,
  tool: (_name: string, _desc: string, _schema: unknown, handler: unknown) => ({
    name: _name,
    handler,
  }),
  createSdkMcpServer: (opts: { name: string; tools: unknown[] }) => ({
    name: opts.name,
    tools: opts.tools,
  }),
}));

import { SupervisorExecutor } from "../src/supervisor/executor";
import type { NatsClient } from "../src/nats/client";

function createMockNatsClient(): NatsClient {
  return {
    publishTaskMessage: mock(() => Promise.resolve()),
    publishTaskComplete: mock(() => Promise.resolve()),
    publishTaskError: mock(() => Promise.resolve()),
    publishHelpRequest: mock(() => Promise.resolve()),
    sendStatus: mock(() => Promise.resolve()),
    conn: {
      subscribe: mock(() => ({
        unsubscribe: mock(() => {}),
        async *[Symbol.asyncIterator]() {},
      })),
      publish: mock(() => {}),
    },
    id: "test-supervisor",
    clientType: "supervisor",
    request: mock(() => Promise.resolve({})),
    subscribeJetStream: mock(() => Promise.resolve({ unsubscribe: mock(() => {}) })),
  } as unknown as NatsClient;
}

describe("SupervisorExecutor", () => {
  let client: NatsClient;
  let executor: SupervisorExecutor;

  beforeEach(() => {
    client = createMockNatsClient();
    executor = new SupervisorExecutor(client, "claude-opus-4-6");

    mockQuery.mockClear();
    mockClose.mockClear();
    mockStreamMessages = [];
    mockQueryError = null;
  });

  test("constructor creates executor", () => {
    expect(executor).toBeTruthy();
  });

  test("handleTask returns early if no task_id", async () => {
    await executor.handleTask({ prompt: "do stuff", options: {} });
    expect(client.publishTaskMessage).not.toHaveBeenCalled();
  });

  test("handleTask calls query and publishes completion", async () => {
    mockStreamMessages = [
      { type: "assistant", content: "Working..." },
      { type: "result", content: "Done!" },
    ];

    await executor.handleTask({
      task_id: "task-123",
      prompt: "Delegate something",
      options: {},
    });

    // Allow the fire-and-forget runSession to complete
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(mockQuery).toHaveBeenCalledTimes(1);

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    expect(publishMessageMock).toHaveBeenCalledTimes(2);

    const publishCompleteMock = client.publishTaskComplete as ReturnType<typeof mock>;
    expect(publishCompleteMock).toHaveBeenCalledTimes(1);
  });

  test("handleTask sends busy status then idle when done", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-status",
      prompt: "Test",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const sendStatusMock = client.sendStatus as ReturnType<typeof mock>;
    const calls = sendStatusMock.mock.calls as any[][];
    expect(calls[0][0]).toBe("busy");
    expect(calls[calls.length - 1][0]).toBe("idle");
  });

  test("handleTask publishes error when query throws", async () => {
    mockQuery.mockImplementationOnce(() => {
      throw new Error("SDK init failed");
    });

    await executor.handleTask({
      task_id: "task-err",
      prompt: "Fail",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const publishErrorMock = client.publishTaskError as ReturnType<typeof mock>;
    expect(publishErrorMock).toHaveBeenCalledTimes(1);
    expect((publishErrorMock.mock.calls[0] as any[])[1]).toContain("SDK init failed");
  });

  test("handleTask passes systemPrompt in query options", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-sys",
      prompt: "Test",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.systemPrompt).toBeTruthy();
    expect(queryArgs.options.systemPrompt).toContain("task supervisor");
  });

  test("handleTask formats prompt with supervisor context", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-fmt",
      prompt: "Do something for me",
      options: { source: "ui" },
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.prompt).toContain("<task_context>");
    expect(queryArgs.prompt).toContain("Do something for me");
  });

  test("handleTask includes mcpServers with orchestrator tools", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-mcp",
      prompt: "Test",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.mcpServers.orchestrator).toBeTruthy();
    expect(queryArgs.options.mcpServers.orchestrator.name).toBe("orchestrator");
  });

  test("handleTask defaults permissionMode to bypassPermissions", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-perm",
      prompt: "Test",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.permissionMode).toBe("bypassPermissions");
  });

  test("stopTask aborts running task and skips error publishing", async () => {
    // Create a query that hangs until aborted
    mockQuery.mockImplementationOnce((params: any) => {
      const abortController = params.options.abortController as AbortController;
      return {
        async *[Symbol.asyncIterator]() {
          yield { type: "assistant", content: "Working..." };
          await new Promise<void>((resolve) => {
            abortController.signal.addEventListener("abort", () => resolve());
          });
          throw new Error("The operation was aborted");
        },
        close: mock(() => {}),
        next: () => Promise.resolve({ done: true, value: undefined }),
        return: () => Promise.resolve({ done: true, value: undefined }),
        throw: () => Promise.resolve({ done: true, value: undefined }),
      };
    });

    await executor.handleTask({
      task_id: "task-stop",
      prompt: "Long running task",
      options: {},
    });

    // Give the session time to start
    await new Promise((resolve) => setTimeout(resolve, 20));

    const stopped = executor.stopTask("task-stop");
    expect(stopped).toBe(true);

    // Wait for the session to finish
    await new Promise((resolve) => setTimeout(resolve, 100));

    // Should NOT have published an error
    const publishErrorMock = client.publishTaskError as ReturnType<typeof mock>;
    expect(publishErrorMock).not.toHaveBeenCalled();
  });

  test("stopTask returns false for unknown task", () => {
    const result = executor.stopTask("nonexistent-task");
    expect(result).toBe(false);
  });

  test("concurrent sessions: idle only sent when last session ends", async () => {
    mockStreamMessages = [];

    // Start two tasks
    await executor.handleTask({
      task_id: "task-a",
      prompt: "First",
      options: {},
    });
    await executor.handleTask({
      task_id: "task-b",
      prompt: "Second",
      options: {},
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    const sendStatusMock = client.sendStatus as ReturnType<typeof mock>;
    const calls = sendStatusMock.mock.calls as any[][];
    // Last call should be "idle"
    expect(calls[calls.length - 1][0]).toBe("idle");
    // Should have multiple "busy" calls
    const busyCalls = calls.filter((c) => c[0] === "busy");
    expect(busyCalls.length).toBeGreaterThanOrEqual(2);
  });
});
