import { describe, test, expect, mock, beforeEach } from "bun:test";

// --- Mock nats module ---
mock.module("nats", () => ({
  connect: mock(() => Promise.resolve({})),
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
  RetentionPolicy: { Limits: 0 },
}));

// --- Mock claude-agent-sdk ---

// Messages the mock query will yield
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
    // AsyncGenerator methods needed for type compatibility
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

import { TaskExecutor } from "../src/worker/executor";
import type { NatsClient } from "../src/nats/client";
import type { TaskPayload } from "../src/types";

function createMockNatsClient(): NatsClient {
  return {
    publishTaskMessage: mock(() => Promise.resolve()),
    publishTaskComplete: mock(() => Promise.resolve()),
    publishTaskError: mock(() => Promise.resolve()),
    publishHelpRequest: mock(() => Promise.resolve()),
    conn: {
      subscribe: mock(() => ({
        unsubscribe: mock(() => {}),
        async *[Symbol.asyncIterator]() {},
      })),
    },
    id: "test-worker",
  } as unknown as NatsClient;
}

describe("TaskExecutor", () => {
  let client: NatsClient;
  let executor: TaskExecutor;

  beforeEach(() => {
    client = createMockNatsClient();
    executor = new TaskExecutor(client, "claude-opus-4-6");

    mockQuery.mockClear();
    mockClose.mockClear();

    // Reset mock stream messages
    mockStreamMessages = [];
    mockQueryError = null;
  });

  test("constructor creates executor with client and model", () => {
    expect(executor).toBeTruthy();
  });

  test("handleTask returns early if no task_id", async () => {
    const payload = { prompt: "do stuff", options: {} } as unknown as TaskPayload;
    await executor.handleTask(payload);

    expect(client.publishTaskMessage).not.toHaveBeenCalled();
    expect(client.publishTaskComplete).not.toHaveBeenCalled();
    expect(client.publishTaskError).not.toHaveBeenCalled();
  });

  test("handleTask calls query and publishes completion", async () => {
    mockStreamMessages = [
      { type: "assistant", content: "Working on it..." },
      { type: "result", content: "Done!" },
    ];

    const payload: TaskPayload = {
      task_id: "task-123",
      prompt: "Navigate to example.com",
      options: {},
    };

    await executor.handleTask(payload);

    // Should have called query
    expect(mockQuery).toHaveBeenCalledTimes(1);

    // The prompt should contain the formatted task
    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.prompt).toContain("Navigate to example.com");
    expect(queryArgs.prompt).toContain("<task>");

    // Should have published messages for each stream message
    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    expect(publishMessageMock).toHaveBeenCalledTimes(2);

    // Should have published completion
    const publishCompleteMock = client.publishTaskComplete as ReturnType<typeof mock>;
    expect(publishCompleteMock).toHaveBeenCalledTimes(1);
    expect((publishCompleteMock.mock.calls[0] as any[])[0]).toBe("task-123");
  });

  test("handleTask publishes each stream message with task_id", async () => {
    mockStreamMessages = [
      { type: "assistant", content: "Step 1" },
      { type: "tool_use", name: "screenshot" },
      { type: "result", content: "Final" },
    ];

    const payload: TaskPayload = {
      task_id: "task-456",
      prompt: "Do something",
      options: {},
    };

    await executor.handleTask(payload);

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    expect(publishMessageMock).toHaveBeenCalledTimes(3);

    for (const call of publishMessageMock.mock.calls as any[][]) {
      expect(call[0]).toBe("task-456");
      expect(call[1].task_id).toBe("task-456");
    }
  });

  test("handleTask publishes result message as completion payload", async () => {
    mockStreamMessages = [
      { type: "assistant", content: "Working..." },
      { type: "result", content: "All done", summary: "Success" },
    ];

    const payload: TaskPayload = {
      task_id: "task-789",
      prompt: "Complete the task",
      options: {},
    };

    await executor.handleTask(payload);

    const publishCompleteMock = client.publishTaskComplete as ReturnType<typeof mock>;
    expect(publishCompleteMock).toHaveBeenCalledTimes(1);

    const completionResult = (publishCompleteMock.mock.calls[0] as any[])[1] as Record<string, unknown>;
    expect(completionResult.__type__).toBe("ResultMessage");
    expect(completionResult.content).toBe("All done");
  });

  test("handleTask publishes error when query throws", async () => {
    mockQuery.mockImplementationOnce(() => {
      throw new Error("SDK initialization failed");
    });

    const payload: TaskPayload = {
      task_id: "task-err",
      prompt: "This will fail",
      options: {},
    };

    await executor.handleTask(payload);

    const publishErrorMock = client.publishTaskError as ReturnType<typeof mock>;
    expect(publishErrorMock).toHaveBeenCalledTimes(1);
    expect((publishErrorMock.mock.calls[0] as any[])[0]).toBe("task-err");
    expect((publishErrorMock.mock.calls[0] as any[])[1]).toContain("SDK initialization failed");
  });

  test("handleTask publishes error when stream throws", async () => {
    mockStreamMessages = [{ type: "assistant", content: "Starting..." }];
    mockQueryError = new Error("Stream broke");

    const payload: TaskPayload = {
      task_id: "task-stream-err",
      prompt: "This will break mid-stream",
      options: {},
    };

    await executor.handleTask(payload);

    const publishErrorMock = client.publishTaskError as ReturnType<typeof mock>;
    expect(publishErrorMock).toHaveBeenCalledTimes(1);
    expect((publishErrorMock.mock.calls[0] as any[])[0]).toBe("task-stream-err");
    expect((publishErrorMock.mock.calls[0] as any[])[1]).toContain("Stream broke");
  });

  test("handleTask passes start_url option to prompt formatter", async () => {
    mockStreamMessages = [];

    const payload: TaskPayload = {
      task_id: "task-url",
      prompt: "Check the page",
      options: { start_url: "https://example.com" },
    };

    await executor.handleTask(payload);

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.prompt).toContain("<starting_url>https://example.com</starting_url>");
    expect(queryArgs.prompt).toContain("<context>");
  });

  test("handleTask creates query with correct model", async () => {
    mockStreamMessages = [];
    const customExecutor = new TaskExecutor(client, "claude-sonnet-4-20250514");

    const payload: TaskPayload = {
      task_id: "task-model",
      prompt: "Test",
      options: {},
    };

    await customExecutor.handleTask(payload);

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.model).toBe("claude-sonnet-4-20250514");
  });

  test("handleTask passes permission_mode from options", async () => {
    mockStreamMessages = [];

    const payload: TaskPayload = {
      task_id: "task-perm",
      prompt: "Test",
      options: { permission_mode: "acceptEdits" },
    };

    await executor.handleTask(payload);

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.permissionMode).toBe("acceptEdits");
  });

  test("handleTask defaults permissionMode to bypassPermissions", async () => {
    mockStreamMessages = [];

    const payload: TaskPayload = {
      task_id: "task-default-perm",
      prompt: "Test",
      options: {},
    };

    await executor.handleTask(payload);

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.permissionMode).toBe("bypassPermissions");
  });

  test("handleTask passes claudeCodePath as pathToClaudeCodeExecutable", async () => {
    mockStreamMessages = [];
    const execWithPath = new TaskExecutor(client, "claude-opus-4-6", "/usr/local/bin/claude");

    await execWithPath.handleTask({
      task_id: "task-path",
      prompt: "Test",
      options: {},
    });

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.pathToClaudeCodeExecutable).toBe("/usr/local/bin/claude");
  });

  test("handleTask omits pathToClaudeCodeExecutable when claudeCodePath is undefined", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-no-path",
      prompt: "Test",
      options: {},
    });

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.pathToClaudeCodeExecutable).toBeUndefined();
  });

  // --- canUseTool callback tests ---

  function getCapturedCanUseTool(): (toolName: string, inputData: Record<string, unknown>) => Promise<any> {
    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    return queryArgs.options.canUseTool;
  }

  test("canUseTool allows non-AskUserQuestion tools", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-tool-allow",
      prompt: "Test",
      options: {},
    });

    const canUseTool = getCapturedCanUseTool();
    const input = { command: "ls -la" };
    const result = await canUseTool("Bash", input);

    expect(result.behavior).toBe("allow");
    expect(result.updatedInput).toEqual(input);
  });

  test("canUseTool denies AskUserQuestion when no current task ID", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-ask-no-ctx",
      prompt: "Test",
      options: {},
    });

    // After handleTask completes, currentTaskId is reset to null in the finally block
    const canUseTool = getCapturedCanUseTool();
    const result = await canUseTool("AskUserQuestion", { questions: [{ question: "Help?" }] });

    expect(result.behavior).toBe("deny");
    expect(result.message).toContain("No active task context");
  });

  test("canUseTool with AskUserQuestion during execution - help response received", async () => {
    // Mock requestHelp at the prototype level to return answers
    const { HelpRequestHandler } = await import("../src/worker/help-request");
    const originalRequestHelp = HelpRequestHandler.prototype.requestHelp;
    HelpRequestHandler.prototype.requestHelp = mock(() =>
      Promise.resolve({ "What color?": "Blue" })
    );

    // Re-create executor so it picks up the mocked prototype
    const freshExecutor = new TaskExecutor(client, "claude-opus-4-6");

    let capturedCanUseTool: any = null;
    mockQuery.mockImplementationOnce((params: any) => {
      capturedCanUseTool = params.options.canUseTool;
      return {
        async *[Symbol.asyncIterator]() {
          const result = await capturedCanUseTool("AskUserQuestion", {
            questions: [{ question: "What color?" }],
          });
          yield { type: "assistant", content: "Got answer", _permResult: result };
        },
        close: mock(() => {}),
        next: () => Promise.resolve({ done: true, value: undefined }),
        return: () => Promise.resolve({ done: true, value: undefined }),
        throw: () => Promise.resolve({ done: true, value: undefined }),
      };
    });

    await freshExecutor.handleTask({
      task_id: "task-ask-mid",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    expect(publishMessageMock).toHaveBeenCalledTimes(1);
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];
    expect(msg._permResult.behavior).toBe("allow");
    expect(msg._permResult.updatedInput.answers).toEqual({ "What color?": "Blue" });
    expect(msg._permResult.updatedInput.questions).toEqual([{ question: "What color?" }]);

    // Restore
    HelpRequestHandler.prototype.requestHelp = originalRequestHelp;
  });

  test("canUseTool with AskUserQuestion during execution - help times out", async () => {
    const { HelpRequestHandler } = await import("../src/worker/help-request");
    const originalRequestHelp = HelpRequestHandler.prototype.requestHelp;
    HelpRequestHandler.prototype.requestHelp = mock(() => Promise.resolve(null));

    const freshExecutor = new TaskExecutor(client, "claude-opus-4-6");

    let capturedCanUseTool: any = null;
    mockQuery.mockImplementationOnce((params: any) => {
      capturedCanUseTool = params.options.canUseTool;
      return {
        async *[Symbol.asyncIterator]() {
          const result = await capturedCanUseTool("AskUserQuestion", {
            questions: [{ question: "Help me?" }],
          });
          yield { type: "assistant", content: "No answer", _permResult: result };
        },
        close: mock(() => {}),
        next: () => Promise.resolve({ done: true, value: undefined }),
        return: () => Promise.resolve({ done: true, value: undefined }),
        throw: () => Promise.resolve({ done: true, value: undefined }),
      };
    });

    await freshExecutor.handleTask({
      task_id: "task-ask-timeout",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    expect(publishMessageMock).toHaveBeenCalledTimes(1);
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];
    expect(msg._permResult.behavior).toBe("deny");
    expect(msg._permResult.message).toContain("Timeout waiting for human response");

    HelpRequestHandler.prototype.requestHelp = originalRequestHelp;
  });

  // --- serializeMessage tests (via published messages) ---

  test("serializeMessage flattens assistant message content from nested message field", async () => {
    mockStreamMessages = [
      {
        type: "assistant",
        message: {
          content: [{ type: "text", text: "Hello world" }],
          model: "claude-opus-4-6",
          role: "assistant",
        },
        uuid: "abc-123",
        session_id: "sess-1",
      },
    ];

    await executor.handleTask({
      task_id: "task-serialize-assistant",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];

    expect(msg.__type__).toBe("AssistantMessage");
    expect(msg.content).toEqual([{ type: "text", text: "Hello world" }]);
    expect(msg.model).toBe("claude-opus-4-6");
    expect(msg.task_id).toBe("task-serialize-assistant");
  });

  test("serializeMessage maps unknown type names through as-is", async () => {
    mockStreamMessages = [
      { type: "some_custom_type", data: "custom" },
    ];

    await executor.handleTask({
      task_id: "task-serialize-unknown",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];

    expect(msg.__type__).toBe("some_custom_type");
  });

  test("serializeMessage maps user type to UserMessage", async () => {
    mockStreamMessages = [
      { type: "user", content: "user input" },
    ];

    await executor.handleTask({
      task_id: "task-serialize-user",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];

    expect(msg.__type__).toBe("UserMessage");
  });

  test("serializeMessage maps system type to SystemMessage", async () => {
    mockStreamMessages = [
      { type: "system", subtype: "init", data: {} },
    ];

    await executor.handleTask({
      task_id: "task-serialize-system",
      prompt: "Test",
      options: {},
    });

    const publishMessageMock = client.publishTaskMessage as ReturnType<typeof mock>;
    const msg = (publishMessageMock.mock.calls[0] as any[])[1];

    expect(msg.__type__).toBe("SystemMessage");
  });

  test("handleTask passes max_turns from options", async () => {
    mockStreamMessages = [];

    await executor.handleTask({
      task_id: "task-max-turns",
      prompt: "Test",
      options: { max_turns: 5 },
    });

    const queryArgs = (mockQuery.mock.calls[0] as any[])[0];
    expect(queryArgs.options.maxTurns).toBe(5);
  });

  test("handleTask stringifies non-Error exceptions", async () => {
    mockQuery.mockImplementationOnce(() => {
      throw "string error";
    });

    await executor.handleTask({
      task_id: "task-string-err",
      prompt: "Test",
      options: {},
    });

    const publishErrorMock = client.publishTaskError as ReturnType<typeof mock>;
    expect(publishErrorMock).toHaveBeenCalledTimes(1);
    expect((publishErrorMock.mock.calls[0] as any[])[1]).toBe("string error");
  });

  test("handleTask calls q.close() even when stream throws", async () => {
    const closeTracker = mock(() => {});
    mockQuery.mockImplementationOnce((_params: any) => ({
      async *[Symbol.asyncIterator]() {
        throw new Error("mid-stream failure");
      },
      close: closeTracker,
      next: () => Promise.resolve({ done: true, value: undefined }),
      return: () => Promise.resolve({ done: true, value: undefined }),
      throw: () => Promise.resolve({ done: true, value: undefined }),
    }));

    await executor.handleTask({
      task_id: "task-close-on-error",
      prompt: "Test",
      options: {},
    });

    expect(closeTracker).toHaveBeenCalledTimes(1);
  });
});
