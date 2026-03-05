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
  "SUPERVISOR_NATS_URL",
  "SUPERVISOR_ID",
  "SUPERVISOR_MODEL",
  "SUPERVISOR_MAX_TURNS",
  "SUPERVISOR_DELEGATION_INACTIVITY_TIMEOUT",
  "SUPERVISOR_HEARTBEAT_INTERVAL",
  "WORKER_CLAUDE_CODE_PATH",
  "SUPERVISOR_CLAUDE_CODE_PATH",
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

  test("WORKER_CLAUDE_CODE_PATH sets claudeCodePath in worker mode", async () => {
    process.env.WORKER_CLAUDE_CODE_PATH = "/usr/local/bin/claude";
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBe("/usr/local/bin/claude");
  });

  test("claudeCodePath defaults to undefined in worker mode", async () => {
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBeUndefined();
  });

  test("SUPERVISOR_CLAUDE_CODE_PATH is ignored in worker mode", async () => {
    process.env.SUPERVISOR_CLAUDE_CODE_PATH = "/usr/local/bin/claude-supervisor";
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBeUndefined();
  });

  test("returned config is frozen", async () => {
    const config = await freshLoadConfig();
    expect(Object.isFrozen(config)).toBe(true);
  });

  test("without --supervisor flag, mode is worker", async () => {
    const config = await freshLoadConfig();
    expect(config.mode).toBe("worker");
  });

  test("worker mode config includes maxTurns and delegationInactivityTimeout", async () => {
    const config = await freshLoadConfig();
    expect("maxTurns" in config).toBe(true);
    expect("delegationInactivityTimeout" in config).toBe(true);
    expect(config.delegationInactivityTimeout).toBe(600);
  });
});

describe("loadConfig (supervisor mode)", () => {
  const originals: Record<string, string | undefined> = {};
  let originalArgv: string[];

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      originals[key] = process.env[key];
      delete process.env[key];
    }
    originalArgv = process.argv;
    process.argv = [...originalArgv, "--supervisor"];
  });

  afterEach(() => {
    process.argv = originalArgv;
    for (const key of ENV_KEYS) {
      if (originals[key] !== undefined) {
        process.env[key] = originals[key];
      } else {
        delete process.env[key];
      }
    }
  });

  async function freshLoadConfig() {
    const mod = await import(`../src/config.ts?t=${Date.now()}-${Math.random()}`);
    return mod.loadConfig();
  }

  test("--supervisor flag sets mode to supervisor", async () => {
    const config = await freshLoadConfig();
    expect(config.mode).toBe("supervisor");
  });

  test("supervisor mode reads SUPERVISOR_NATS_URL", async () => {
    process.env.SUPERVISOR_NATS_URL = "nats://supervisor:5222";
    const config = await freshLoadConfig();
    expect(config.natsUrl).toBe("nats://supervisor:5222");
  });

  test("supervisor mode reads SUPERVISOR_ID", async () => {
    process.env.SUPERVISOR_ID = "sup-42";
    const config = await freshLoadConfig();
    expect(config.workerId).toBe("sup-42");
  });

  test("supervisor mode falls back to hostname when SUPERVISOR_ID is not set", async () => {
    const config = await freshLoadConfig();
    expect(config.workerId).toBe(hostname());
  });

  test("supervisor mode reads SUPERVISOR_MODEL", async () => {
    process.env.SUPERVISOR_MODEL = "claude-sonnet-4-20250514";
    const config = await freshLoadConfig();
    expect(config.model).toBe("claude-sonnet-4-20250514");
  });

  test("supervisor mode sets novncUrl to empty string and novncPort to 0", async () => {
    const config = await freshLoadConfig();
    expect(config.novncUrl).toBe("");
    expect(config.novncPort).toBe(0);
  });

  test("supervisor mode reads SUPERVISOR_MAX_TURNS", async () => {
    process.env.SUPERVISOR_MAX_TURNS = "25";
    const config = await freshLoadConfig();
    expect(config.maxTurns).toBe(25);
  });

  test("supervisor mode defaults maxTurns to undefined", async () => {
    const config = await freshLoadConfig();
    expect(config.maxTurns).toBeUndefined();
  });

  test("supervisor mode defaults delegationInactivityTimeout to 600", async () => {
    const config = await freshLoadConfig();
    expect(config.delegationInactivityTimeout).toBe(600);
  });

  test("SUPERVISOR_CLAUDE_CODE_PATH sets claudeCodePath in supervisor mode", async () => {
    process.env.SUPERVISOR_CLAUDE_CODE_PATH = "/usr/local/bin/claude-supervisor";
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBe("/usr/local/bin/claude-supervisor");
  });

  test("claudeCodePath defaults to undefined in supervisor mode", async () => {
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBeUndefined();
  });

  test("WORKER_CLAUDE_CODE_PATH is ignored in supervisor mode", async () => {
    process.env.WORKER_CLAUDE_CODE_PATH = "/usr/local/bin/claude-worker";
    const config = await freshLoadConfig();
    expect(config.claudeCodePath).toBeUndefined();
  });

  test("returned config is frozen", async () => {
    const config = await freshLoadConfig();
    expect(Object.isFrozen(config)).toBe(true);
  });
});
