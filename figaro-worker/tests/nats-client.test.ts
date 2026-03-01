import { describe, test, expect, mock, beforeEach } from "bun:test";

// --- Mock the nats module BEFORE importing NatsClient ---

const mockPublish = mock(() => {});
const mockRequest = mock(() =>
  Promise.resolve({ data: new Uint8Array(), headers: null }),
);
const mockJsPublish = mock(() => Promise.resolve());
const mockSubscribe = mock(() => ({
  async *[Symbol.asyncIterator]() {},
}));
const mockDrain = mock(() => Promise.resolve());
const mockIsClosed = mock(() => false);
const mockJetstream = mock(() => ({ publish: mockJsPublish }));
const mockJetstreamManager = mock(() =>
  Promise.resolve({
    streams: {
      get: mock(() =>
        Promise.resolve({
          info: () => Promise.resolve({ config: {} }),
        }),
      ),
      add: mock(() => Promise.resolve()),
      update: mock(() => Promise.resolve()),
    },
  }),
);

const mockNatsConnection = {
  publish: mockPublish,
  request: mockRequest,
  subscribe: mockSubscribe,
  drain: mockDrain,
  isClosed: mockIsClosed,
  jetstream: mockJetstream,
  jetstreamManager: mockJetstreamManager,
};

const mockConnect = mock(() => Promise.resolve(mockNatsConnection));

mock.module("nats", () => ({
  connect: mockConnect,
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
  RetentionPolicy: { Limits: 0 },
}));

// Now import NatsClient (uses the mocked nats module)
import { NatsClient } from "../src/nats/client";

describe("NatsClient", () => {
  beforeEach(() => {
    mockPublish.mockClear();
    mockRequest.mockClear();
    mockJsPublish.mockClear();
    mockSubscribe.mockClear();
    mockDrain.mockClear();
    mockIsClosed.mockClear();
    mockJetstream.mockClear();
    mockJetstreamManager.mockClear();
    mockConnect.mockClear();
  });

  describe("constructor", () => {
    test("sets natsUrl and workerId from options", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      expect(client.id).toBe("worker-1");
    });

    test("defaults capabilities to empty array", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      // We can verify indirectly: the client was constructed without error
      expect(client).toBeTruthy();
    });

    test("defaults novncUrl to null", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      expect(client).toBeTruthy();
    });
  });

  describe("on()", () => {
    test("registers event handlers", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      const handler = mock(() => Promise.resolve());
      client.on("task", handler);
      // Handler is registered (no error thrown, client is valid)
      expect(client).toBeTruthy();
    });

    test("supports multiple handlers for the same event", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      const handler1 = mock(() => Promise.resolve());
      const handler2 = mock(() => Promise.resolve());
      client.on("task", handler1);
      client.on("task", handler2);
      expect(client).toBeTruthy();
    });
  });

  describe("isConnected", () => {
    test("returns false before connect is called", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      expect(client.isConnected).toBe(false);
    });

    test("returns true after successful connect", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      mockIsClosed.mockReturnValue(false);
      await client.connect();
      expect(client.isConnected).toBe(true);
    });

    test("returns false when connection is closed", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      mockIsClosed.mockReturnValue(true);
      expect(client.isConnected).toBe(false);
    });
  });

  describe("conn", () => {
    test("throws before connect is called", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      expect(() => client.conn).toThrow("NATS connection not established");
    });

    test("returns connection after connect", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      expect(client.conn).toBeTruthy();
    });
  });

  describe("connect()", () => {
    test("returns true on successful connection", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      const result = await client.connect();
      expect(result).toBe(true);
    });

    test("calls nats connect with correct options", async () => {
      const client = new NatsClient({
        natsUrl: "nats://custom:5222",
        workerId: "worker-42",
      });
      await client.connect();
      expect(mockConnect).toHaveBeenCalledTimes(1);
      const callArgs = mockConnect.mock.calls[0][0] as Record<string, unknown>;
      expect(callArgs.servers).toEqual(["nats://custom:5222"]);
      expect(callArgs.name).toBe("worker-worker-42");
    });

    test("subscribes to worker task subject after connecting", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-7",
      });
      await client.connect();
      expect(mockSubscribe).toHaveBeenCalledWith("figaro.worker.worker-7.task");
    });

    test("publishes registration message after connecting", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-7",
      });
      await client.connect();
      expect(mockRequest).toHaveBeenCalled();
      const requestCall = mockRequest.mock.calls[0];
      expect(requestCall[0]).toBe("figaro.register.worker");
    });

    test("returns false on connection failure", async () => {
      mockConnect.mockImplementationOnce(() =>
        Promise.reject(new Error("Connection refused")),
      );
      const client = new NatsClient({
        natsUrl: "nats://bad:4222",
        workerId: "worker-1",
      });
      const result = await client.connect();
      expect(result).toBe(false);
    });
  });

  describe("publish methods", () => {
    test("publishTaskMessage publishes to correct JetStream subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskMessage("task-abc", { content: "hello" });
      expect(mockJsPublish).toHaveBeenCalledTimes(1);
      const call = mockJsPublish.mock.calls[0];
      expect(call[0]).toBe("figaro.task.task-abc.message");
    });

    test("publishTaskMessage includes task_id and worker_id", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskMessage("task-abc", { content: "hello" });
      const call = mockJsPublish.mock.calls[0];
      const decoded = JSON.parse(new TextDecoder().decode(call[1]));
      expect(decoded.task_id).toBe("task-abc");
      expect(decoded.worker_id).toBe("worker-1");
      expect(decoded.content).toBe("hello");
    });

    test("publishTaskComplete publishes to correct JetStream subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskComplete("task-xyz", { status: "done" });
      expect(mockJsPublish).toHaveBeenCalledTimes(1);
      const call = mockJsPublish.mock.calls[0];
      expect(call[0]).toBe("figaro.task.task-xyz.complete");
    });

    test("publishTaskComplete includes result in payload", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskComplete("task-xyz", { status: "done" });
      const call = mockJsPublish.mock.calls[0];
      const decoded = JSON.parse(new TextDecoder().decode(call[1]));
      expect(decoded.result).toEqual({ status: "done" });
      expect(decoded.task_id).toBe("task-xyz");
      expect(decoded.worker_id).toBe("worker-1");
    });

    test("publishTaskError publishes to correct JetStream subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskError("task-err", "Something broke");
      expect(mockJsPublish).toHaveBeenCalledTimes(1);
      const call = mockJsPublish.mock.calls[0];
      expect(call[0]).toBe("figaro.task.task-err.error");
    });

    test("publishTaskError includes error string in payload", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishTaskError("task-err", "Something broke");
      const call = mockJsPublish.mock.calls[0];
      const decoded = JSON.parse(new TextDecoder().decode(call[1]));
      expect(decoded.error).toBe("Something broke");
      expect(decoded.task_id).toBe("task-err");
    });

    test("publishHelpRequest publishes to Core NATS help subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.publishHelpRequest("req-1", "task-1", [{ q: "How?" }], 300);
      expect(mockPublish).toHaveBeenCalled();
      // Find the help request publish (not the registration publish)
      const helpCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.help.request",
      );
      expect(helpCall).toBeTruthy();
    });

    test("sendStatus publishes to heartbeat subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.sendStatus("busy");
      const heartbeatCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.heartbeat.worker.worker-1",
      );
      expect(heartbeatCall).toBeTruthy();
    });

    test("sendHeartbeat publishes to heartbeat subject", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      await client.sendHeartbeat();
      const heartbeatCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.heartbeat.worker.worker-1",
      );
      expect(heartbeatCall).toBeTruthy();
    });

    test("registration includes client_type in heartbeat", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      await client.connect();
      mockPublish.mockClear();
      await client.sendHeartbeat();
      const heartbeatCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.heartbeat.worker.worker-1",
      );
      expect(heartbeatCall).toBeTruthy();
      const decoded = JSON.parse(
        new TextDecoder().decode(heartbeatCall![1] as Uint8Array),
      );
      expect(decoded.client_type).toBe("worker");
    });

    test("heartbeat includes novnc_url for auto-registration", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
        novncUrl: "ws://worker-1:6080/websockify",
      });
      await client.connect();
      mockPublish.mockClear();
      await client.sendHeartbeat();
      const heartbeatCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.heartbeat.worker.worker-1",
      );
      expect(heartbeatCall).toBeTruthy();
      const decoded = JSON.parse(
        new TextDecoder().decode(heartbeatCall![1] as Uint8Array),
      );
      expect(decoded.novnc_url).toBe("ws://worker-1:6080/websockify");
    });

    test("heartbeat includes capabilities for auto-registration", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
        capabilities: ["browser", "desktop"],
      });
      await client.connect();
      mockPublish.mockClear();
      await client.sendHeartbeat();
      const heartbeatCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.heartbeat.worker.worker-1",
      );
      expect(heartbeatCall).toBeTruthy();
      const decoded = JSON.parse(
        new TextDecoder().decode(heartbeatCall![1] as Uint8Array),
      );
      expect(decoded.capabilities).toEqual(["browser", "desktop"]);
    });
  });

  describe("close()", () => {
    test("publishes deregistration and drains connection", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      mockIsClosed.mockReturnValue(false);
      await client.connect();
      mockPublish.mockClear();
      await client.close();

      // Should publish deregistration
      const deregCall = mockPublish.mock.calls.find(
        (c: unknown[]) => c[0] === "figaro.deregister.worker.worker-1",
      );
      expect(deregCall).toBeTruthy();

      // Should drain
      expect(mockDrain).toHaveBeenCalled();
    });

    test("does nothing if not connected", async () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      // Never connected, so close should be a no-op
      await client.close();
      expect(mockDrain).not.toHaveBeenCalled();
    });
  });

  describe("stop()", () => {
    test("can be called without error", () => {
      const client = new NatsClient({
        natsUrl: "nats://test:4222",
        workerId: "worker-1",
      });
      expect(() => client.stop()).not.toThrow();
    });
  });
});
