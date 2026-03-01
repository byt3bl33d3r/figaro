import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { hostname } from "os";

// Keys we manipulate in tests -- cleaned up in afterEach
const ENV_KEYS = [
  "WORKER_NATS_URL",
  "WORKER_ID",
  "WORKER_HEARTBEAT_INTERVAL",
  "WORKER_RECONNECT_DELAY",
  "WORKER_MAX_RECONNECT_DELAY",
  "WORKER_NOVNC_URL",
  "WORKER_NOVNC_PORT",
  "WORKER_MODEL",
] as const;

describe("loadConfig", () => {
  // Snapshot original env values so we can restore after each test
  const originals: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      originals[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (originals[key] !== undefined) {
        process.env[key] = originals[key];
      } else {
        delete process.env[key];
      }
    }
  });

  /** Fresh import each time so loadConfig reads the current env */
  async function freshLoadConfig() {
    // Dynamic import with cache busting so each call re-evaluates
    const mod = await import(`../src/config.ts?t=${Date.now()}-${Math.random()}`);
    return mod.loadConfig();
  }

  test("returns correct defaults when no env vars are set", async () => {
    const config = await freshLoadConfig();

    expect(config.natsUrl).toBe("nats://localhost:4222");
    expect(config.workerId).toBe(hostname());
    expect(config.heartbeatInterval).toBe(30);
    expect(config.reconnectDelay).toBe(1);
    expect(config.maxReconnectDelay).toBe(60);
    expect(config.novncUrl).toBe(`ws://${hostname()}:6080/websockify`);
    expect(config.novncPort).toBe(6080);
    expect(config.model).toBe("claude-opus-4-6");
  });

  test("WORKER_NATS_URL overrides default natsUrl", async () => {
    process.env.WORKER_NATS_URL = "nats://custom:5222";
    const config = await freshLoadConfig();
    expect(config.natsUrl).toBe("nats://custom:5222");
  });

  test("WORKER_ID overrides hostname-based workerId", async () => {
    process.env.WORKER_ID = "my-worker-42";
    const config = await freshLoadConfig();
    expect(config.workerId).toBe("my-worker-42");
  });

  test("workerId falls back to hostname when WORKER_ID is not set", async () => {
    const config = await freshLoadConfig();
    expect(config.workerId).toBe(hostname());
  });

  test("WORKER_HEARTBEAT_INTERVAL overrides default", async () => {
    process.env.WORKER_HEARTBEAT_INTERVAL = "15";
    const config = await freshLoadConfig();
    expect(config.heartbeatInterval).toBe(15);
  });

  test("WORKER_RECONNECT_DELAY overrides default", async () => {
    process.env.WORKER_RECONNECT_DELAY = "5";
    const config = await freshLoadConfig();
    expect(config.reconnectDelay).toBe(5);
  });

  test("WORKER_MAX_RECONNECT_DELAY overrides default", async () => {
    process.env.WORKER_MAX_RECONNECT_DELAY = "120";
    const config = await freshLoadConfig();
    expect(config.maxReconnectDelay).toBe(120);
  });

  test("WORKER_NOVNC_URL overrides auto-constructed novncUrl", async () => {
    process.env.WORKER_NOVNC_URL = "ws://custom-host:9999/ws";
    const config = await freshLoadConfig();
    expect(config.novncUrl).toBe("ws://custom-host:9999/ws");
  });

  test("novncUrl auto-constructs from hostname and port when not set", async () => {
    process.env.WORKER_NOVNC_PORT = "7070";
    const config = await freshLoadConfig();
    expect(config.novncUrl).toBe(`ws://${hostname()}:7070/websockify`);
  });

  test("WORKER_NOVNC_PORT overrides default port", async () => {
    process.env.WORKER_NOVNC_PORT = "7070";
    const config = await freshLoadConfig();
    expect(config.novncPort).toBe(7070);
  });

  test("WORKER_MODEL overrides default model", async () => {
    process.env.WORKER_MODEL = "claude-sonnet-4-20250514";
    const config = await freshLoadConfig();
    expect(config.model).toBe("claude-sonnet-4-20250514");
  });

  test("returned config is frozen", async () => {
    const config = await freshLoadConfig();
    expect(Object.isFrozen(config)).toBe(true);
  });
});
