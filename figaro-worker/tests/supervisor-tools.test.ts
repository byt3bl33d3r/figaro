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
mock.module("@anthropic-ai/claude-agent-sdk", () => ({
  query: mock(() => ({})),
  tool: (name: string, desc: string, schema: unknown, handler: Function) => ({
    name,
    description: desc,
    schema,
    handler,
  }),
  createSdkMcpServer: (opts: { name: string; tools: unknown[] }) => ({
    name: opts.name,
    tools: opts.tools,
  }),
}));

import { waitForDelegation, createSupervisorToolsServer } from "../src/supervisor/tools";
import type { NatsClient } from "../src/nats/client";

function getServer(client: NatsClient, sourceMetadata?: Record<string, any> | null) {
  const { server, destroySession } = createSupervisorToolsServer(client, sourceMetadata);
  return { server: server as any, destroySession };
}

function createMockClient(overrides: Record<string, any> = {}): NatsClient {
  return {
    id: "test-supervisor",
    clientType: "supervisor",
    request: mock(() => Promise.resolve({})),
    subscribeJetStream: mock(() =>
      Promise.resolve({ unsubscribe: mock(() => {}) }),
    ),
    publishTaskMessage: mock(() => Promise.resolve()),
    publishTaskComplete: mock(() => Promise.resolve()),
    publishTaskError: mock(() => Promise.resolve()),
    publishHelpRequest: mock(() => Promise.resolve()),
    sendStatus: mock(() => Promise.resolve()),
    conn: {
      publish: mock(() => {}),
      subscribe: mock(() => ({
        unsubscribe: mock(() => {}),
        async *[Symbol.asyncIterator]() {},
      })),
    },
    ...overrides,
  } as unknown as NatsClient;
}

/**
 * Creates a mock Core NATS subscription that exposes a push(msg) function
 * to simulate incoming messages on the async iterator.
 */
function createMockCoreSubscription() {
  const unsubscribe = mock(() => {});
  let resolve: ((value: IteratorResult<any>) => void) | null = null;
  const pending: any[] = [];

  const sub = {
    unsubscribe,
    async *[Symbol.asyncIterator]() {
      while (true) {
        if (pending.length > 0) {
          yield pending.shift();
        } else {
          const msg = await new Promise<any>((r) => {
            resolve = (val) => r(val.value);
          });
          if (!msg) return;
          yield msg;
        }
      }
    },
  };

  function push(data: Record<string, any>) {
    const encoded = new TextEncoder().encode(JSON.stringify(data));
    const msg = { data: encoded };
    if (resolve) {
      const r = resolve;
      resolve = null;
      r({ value: msg, done: false });
    } else {
      pending.push(msg);
    }
  }

  return { sub, push, unsubscribe };
}

describe("waitForDelegation", () => {
  test("resolves with completion when task completes", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { promise } = waitForDelegation(client, "task-1", { task_id: "task-1" }, 5);

    // Simulate completion
    await new Promise((r) => setTimeout(r, 10));
    completeSub.push({ result: { summary: "Done" } });

    const res = await promise;
    expect(res.content[0].text).toContain("completed");
    expect(res.content[0].text).toContain("Done");
  });

  test("resolves with error when task fails", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { promise } = waitForDelegation(client, "task-2", { task_id: "task-2" }, 5);

    await new Promise((r) => setTimeout(r, 10));
    errorSub.push({ error: "Something broke" });

    const res = await promise;
    expect(res.content[0].text).toContain("failed");
    expect(res.content[0].text).toContain("Something broke");
  });

  test("resolves with timeout when no activity", async () => {
    const client = createMockClient();

    const { promise } = waitForDelegation(
      client,
      "task-3",
      { task_id: "task-3" },
      0.1, // 100ms timeout
    );

    const res = await promise;
    expect(res.content[0].text).toContain("timeout");
    expect(res.content[0].text).toContain("no activity");
  });

  test("resets timer on activity", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { promise } = waitForDelegation(client, "task-4", { task_id: "task-4" }, 0.2);

    // Send activity at 100ms to reset the 200ms timer
    setTimeout(() => messageSub.push({}), 100);
    // Complete at 250ms (would have timed out without the reset)
    setTimeout(() => completeSub.push({ result: "OK" }), 250);

    const res = await promise;
    expect(res.content[0].text).toContain("completed");
  });

  test("unsubscribes all on completion", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { promise, subs } = waitForDelegation(client, "task-5", { task_id: "task-5" }, 5);

    await new Promise((r) => setTimeout(r, 10));
    completeSub.push({ result: "Done" });

    await promise;

    // Verify subs were returned (caller is responsible for cleanup)
    expect(subs.length).toBe(3);
    for (const sub of subs) {
      sub.unsubscribe();
    }
    expect(completeSub.unsubscribe).toHaveBeenCalled();
    expect(errorSub.unsubscribe).toHaveBeenCalled();
    expect(messageSub.unsubscribe).toHaveBeenCalled();
  });
});

describe("createSupervisorToolsServer", () => {
  test("returns server with name 'orchestrator'", () => {
    const client = createMockClient();
    const { server } = getServer(client);
    expect(server.name).toBe("orchestrator");
  });

  test("creates all expected tools", () => {
    const client = createMockClient();
    const { server } = getServer(client);
    expect(server.tools.length).toBe(18);
  });

  test("tool names match expected set", () => {
    const client = createMockClient();
    const { server } = getServer(client);
    const names = server.tools.map((t: any) => t.name).sort();
    expect(names).toEqual([
      "click",
      "create_scheduled_task",
      "delegate_to_worker",
      "delete_scheduled_task",
      "get_scheduled_task",
      "get_supervisor_status",
      "list_scheduled_tasks",
      "list_workers",
      "press_key",
      "python_exec",
      "send_screenshot",
      "ssh_run_command",
      "take_screenshot",
      "telnet_run_command",
      "toggle_scheduled_task",
      "type_text",
      "unlock_screen",
      "update_scheduled_task",
    ]);
  });

  test("VNC click applies scale factors from take_screenshot", async () => {
    const client = createMockClient({
      request: mock((subject: string, data: any) => {
        if (data.action === "screenshot") {
          return Promise.resolve({
            image: "base64data",
            mime_type: "image/jpeg",
            original_width: 1920,
            original_height: 1080,
            width: 1280,
            height: 720,
          });
        }
        if (data.action === "click") {
          // Return the x,y that were sent to verify scaling
          return Promise.resolve({ ok: true, x: data.x, y: data.y });
        }
        return Promise.resolve({});
      }),
    });

    const { server } = getServer(client);
    const screenshotTool = server.tools.find((t: any) => t.name === "take_screenshot");
    const clickTool = server.tools.find((t: any) => t.name === "click");

    // Take screenshot to record scale factor
    await screenshotTool.handler({ worker_id: "w1" });

    // Click at (640, 360) — should scale to (960, 540) with 1.5x factor
    await clickTool.handler({ worker_id: "w1", x: 640, y: 360 });

    const requestMock = client.request as ReturnType<typeof mock>;
    const clickCall = requestMock.mock.calls.find(
      (c: any[]) => c[1]?.action === "click",
    );
    expect(clickCall).toBeTruthy();
    expect(clickCall![1].x).toBe(960); // 640 * (1920/1280) = 960
    expect(clickCall![1].y).toBe(540); // 360 * (1080/720) = 540
  });

  test("send_screenshot returns error without sourceMetadata", async () => {
    const client = createMockClient();
    const { server } = getServer(client);
    const sendScreenshotTool = server.tools.find(
      (t: any) => t.name === "send_screenshot",
    );

    const res = await sendScreenshotTool.handler({ worker_id: "w1" });
    expect(res.content[0].text).toContain("Error");
    expect(res.content[0].text).toContain("No channel context");
  });

  test("ssh_run_command sends correct NATS request", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          stdout: "file1.txt\nfile2.txt\n",
          stderr: "",
          exit_code: 0,
        }),
      ),
    });

    const { server } = getServer(client);
    const sshTool = server.tools.find((t: any) => t.name === "ssh_run_command");

    const res = await sshTool.handler({
      worker_id: "w1",
      command: "ls /",
      timeout: 60,
    });

    const requestMock = client.request as ReturnType<typeof mock>;
    expect(requestMock).toHaveBeenCalledWith(
      "figaro.api.ssh",
      {
        action: "run_command",
        worker_id: "w1",
        command: "ls /",
        timeout: 60,
      },
      65000, // max(30000, (60+5)*1000)
    );
    expect(res.content[0].text).toContain("file1.txt");
    expect(res.content[0].text).toContain("exit_code");
  });

  test("ssh_run_command returns error on failure", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({ error: "Connection refused" }),
      ),
    });

    const { server } = getServer(client);
    const sshTool = server.tools.find((t: any) => t.name === "ssh_run_command");

    const res = await sshTool.handler({ worker_id: "w1", command: "ls" });
    expect(res.content[0].text).toContain("Error");
    expect(res.content[0].text).toContain("Connection refused");
  });

  test("telnet_run_command sends correct NATS request", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({ output: "hello world" }),
      ),
    });

    const { server } = getServer(client);
    const telnetTool = server.tools.find(
      (t: any) => t.name === "telnet_run_command",
    );

    const res = await telnetTool.handler({
      worker_id: "w1",
      command: "echo hello",
    });

    const requestMock = client.request as ReturnType<typeof mock>;
    expect(requestMock).toHaveBeenCalledWith(
      "figaro.api.telnet",
      {
        action: "run_command",
        worker_id: "w1",
        command: "echo hello",
        timeout: undefined,
      },
      30000, // max(30000, (10+5)*1000) = 30000
    );
    expect(res.content[0].text).toContain("hello world");
  });

  test("telnet_run_command returns error on failure", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({ error: "Connection timed out" }),
      ),
    });

    const { server } = getServer(client);
    const telnetTool = server.tools.find(
      (t: any) => t.name === "telnet_run_command",
    );

    const res = await telnetTool.handler({ worker_id: "w1", command: "ls" });
    expect(res.content[0].text).toContain("Error");
    expect(res.content[0].text).toContain("Connection timed out");
  });

  test("send_screenshot works with sourceMetadata", async () => {
    const publishMock = mock(() => {});
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          image: "base64data",
          mime_type: "image/jpeg",
          width: 1280,
          height: 800,
        }),
      ),
      conn: {
        publish: publishMock,
        subscribe: mock(() => ({
          unsubscribe: mock(() => {}),
          async *[Symbol.asyncIterator]() {},
        })),
      },
    });

    const { server } = getServer(client, {
      channel: "telegram",
      chat_id: "123",
    });
    const sendScreenshotTool = server.tools.find(
      (t: any) => t.name === "send_screenshot",
    );

    const res = await sendScreenshotTool.handler({ worker_id: "w1" });
    expect(res.content[0].text).toContain("sent to telegram");
    expect(publishMock).toHaveBeenCalled();
  });
});

/**
 * Regression tests for delegate_to_worker blocking behavior.
 *
 * Previously, delegate_to_worker used JetStream ephemeral push consumers
 * (js.subscribe()) which could fail silently in nats.js v2, causing the
 * tool to return immediately instead of blocking until the worker finished.
 * The fix switched to Core NATS subscriptions (nc.subscribe()), which
 * JetStream publishes also deliver to. These tests verify the tool
 * actually blocks and waits for the worker result.
 */
describe("delegate_to_worker regression: blocks until worker completes", () => {
  test("blocks until worker publishes completion, not returning immediately", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          task_id: "delegated-1",
          worker_id: "w1",
          queued: false,
          message: "Task delegated.",
        }),
      ),
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    // Start the delegation — it should NOT resolve immediately
    let resolved = false;
    const resultPromise = delegateTool
      .handler({ prompt: "Do something", worker_id: "w1" })
      .then((res: any) => {
        resolved = true;
        return res;
      });

    // Wait a tick — the tool must still be blocking
    await new Promise((r) => setTimeout(r, 50));
    expect(resolved).toBe(false);

    // Simulate worker completing after 100ms
    completeSub.push({ result: "Task done successfully" });

    const res = await resultPromise;
    expect(resolved).toBe(true);
    expect(res.content[0].text).toContain("completed");
    expect(res.content[0].text).toContain("Task done successfully");
  });

  test("blocks and returns error when worker fails", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          task_id: "delegated-2",
          worker_id: "w1",
          queued: false,
          message: "Task delegated.",
        }),
      ),
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    let resolved = false;
    const resultPromise = delegateTool
      .handler({ prompt: "Do something", worker_id: "w1" })
      .then((res: any) => {
        resolved = true;
        return res;
      });

    await new Promise((r) => setTimeout(r, 50));
    expect(resolved).toBe(false);

    errorSub.push({ error: "Browser crashed" });

    const res = await resultPromise;
    expect(resolved).toBe(true);
    expect(res.content[0].text).toContain("failed");
    expect(res.content[0].text).toContain("Browser crashed");
  });

  test("returns immediately when orchestrator returns queued", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          task_id: "delegated-3",
          worker_id: null,
          queued: true,
          message: "No workers available. Task queued.",
        }),
      ),
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    const res = await delegateTool.handler({ prompt: "Do something" });
    expect(res.content[0].text).toContain("queued");
    expect(res.content[0].text).toContain("No workers available");
  });

  test("returns immediately when orchestrator returns error", async () => {
    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          error: "Worker w1 is busy",
          task_id: "delegated-4",
          queued: true,
        }),
      ),
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    const res = await delegateTool.handler({
      prompt: "Do something",
      worker_id: "w1",
    });
    expect(res.content[0].text).toContain("Worker w1 is busy");
  });

  test("stays blocked while worker sends activity messages", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          task_id: "delegated-5",
          worker_id: "w1",
          queued: false,
          message: "Task delegated.",
        }),
      ),
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    let resolved = false;
    const resultPromise = delegateTool
      .handler({ prompt: "Do something", worker_id: "w1" })
      .then((res: any) => {
        resolved = true;
        return res;
      });

    // Simulate worker sending multiple activity messages
    for (let i = 0; i < 5; i++) {
      await new Promise((r) => setTimeout(r, 20));
      messageSub.push({ type: "assistant", message: `Working step ${i}...` });
      expect(resolved).toBe(false);
    }

    // Finally complete
    completeSub.push({ result: "All steps done" });

    const res = await resultPromise;
    expect(resolved).toBe(true);
    expect(res.content[0].text).toContain("completed");
    expect(res.content[0].text).toContain("All steps done");
  });

  test("cleans up subscriptions after completion", async () => {
    const completeSub = createMockCoreSubscription();
    const errorSub = createMockCoreSubscription();
    const messageSub = createMockCoreSubscription();
    let subIdx = 0;

    const client = createMockClient({
      request: mock(() =>
        Promise.resolve({
          task_id: "delegated-6",
          worker_id: "w1",
          queued: false,
          message: "Task delegated.",
        }),
      ),
      conn: {
        publish: mock(() => {}),
        subscribe: mock(() => {
          const subs = [completeSub.sub, errorSub.sub, messageSub.sub];
          return subs[subIdx++];
        }),
      },
    });

    const { server } = getServer(client);
    const delegateTool = server.tools.find(
      (t: any) => t.name === "delegate_to_worker",
    );

    const resultPromise = delegateTool.handler({
      prompt: "Do something",
      worker_id: "w1",
    });

    await new Promise((r) => setTimeout(r, 10));
    completeSub.push({ result: "Done" });

    await resultPromise;

    // Verify all three Core NATS subscriptions were cleaned up
    expect(completeSub.unsubscribe).toHaveBeenCalled();
    expect(errorSub.unsubscribe).toHaveBeenCalled();
    expect(messageSub.unsubscribe).toHaveBeenCalled();
  });
});
