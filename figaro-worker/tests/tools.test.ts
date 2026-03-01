import { describe, test, expect, mock, beforeEach, afterEach } from "bun:test";

// Mock the claude-agent-sdk module since it may not be available in test env
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

import { createDesktopToolsServer, detectPlatform } from "../src/worker/tools";
import { createLinuxTools } from "../src/worker/tools-linux";
import { createMacosTools } from "../src/worker/tools-macos";

const EXPECTED_TOOL_NAMES = [
  "screenshot",
  "mouse_click",
  "mouse_move",
  "type_text",
  "press_key",
  "scroll",
  "mouse_drag",
];

describe("createDesktopToolsServer", () => {
  test("returns a truthy value", () => {
    const server = createDesktopToolsServer();
    expect(server).toBeTruthy();
  });

  test("returns a server with a name", () => {
    const server = createDesktopToolsServer() as { name: string };
    expect(server.name).toBe("desktop");
  });

  test("returns a server with a version", () => {
    const server = createDesktopToolsServer() as { version: string };
    expect(server.version).toBe("1.0.0");
  });

  test("returns a server with tools array", () => {
    const server = createDesktopToolsServer() as { tools: unknown[] };
    expect(Array.isArray(server.tools)).toBe(true);
    expect(server.tools.length).toBeGreaterThan(0);
  });

  test("includes expected tool names", () => {
    const server = createDesktopToolsServer() as {
      tools: Array<{ name: string }>;
    };
    const toolNames = server.tools.map((t) => t.name);
    for (const name of EXPECTED_TOOL_NAMES) {
      expect(toolNames).toContain(name);
    }
  });
});

describe("detectPlatform", () => {
  const originalPlatform = process.env.WORKER_PLATFORM;

  afterEach(() => {
    if (originalPlatform === undefined) {
      delete process.env.WORKER_PLATFORM;
    } else {
      process.env.WORKER_PLATFORM = originalPlatform;
    }
  });

  test("returns 'darwin' when WORKER_PLATFORM=darwin", () => {
    process.env.WORKER_PLATFORM = "darwin";
    expect(detectPlatform()).toBe("darwin");
  });

  test("returns 'linux' when WORKER_PLATFORM=linux", () => {
    process.env.WORKER_PLATFORM = "linux";
    expect(detectPlatform()).toBe("linux");
  });

  test("ignores invalid WORKER_PLATFORM values", () => {
    process.env.WORKER_PLATFORM = "windows";
    const result = detectPlatform();
    expect(result === "linux" || result === "darwin").toBe(true);
  });

  test("falls back to process.platform when WORKER_PLATFORM is unset", () => {
    delete process.env.WORKER_PLATFORM;
    const result = detectPlatform();
    expect(result === "linux" || result === "darwin").toBe(true);
  });
});

describe("tool parity", () => {
  test("Linux and macOS backends expose the same tool names", () => {
    const linuxTools = createLinuxTools() as Array<{ name: string }>;
    const macosTools = createMacosTools() as Array<{ name: string }>;

    const linuxNames = linuxTools.map((t) => t.name).sort();
    const macosNames = macosTools.map((t) => t.name).sort();

    expect(linuxNames).toEqual(macosNames);
  });

  test("both backends expose exactly the expected tools", () => {
    const linuxTools = createLinuxTools() as Array<{ name: string }>;
    const macosTools = createMacosTools() as Array<{ name: string }>;

    const expected = [...EXPECTED_TOOL_NAMES].sort();
    expect(linuxTools.map((t) => t.name).sort()).toEqual(expected);
    expect(macosTools.map((t) => t.name).sort()).toEqual(expected);
  });
});

describe("platform-based tool selection", () => {
  const originalPlatform = process.env.WORKER_PLATFORM;

  afterEach(() => {
    if (originalPlatform === undefined) {
      delete process.env.WORKER_PLATFORM;
    } else {
      process.env.WORKER_PLATFORM = originalPlatform;
    }
  });

  test("WORKER_PLATFORM=darwin selects macOS tools", () => {
    process.env.WORKER_PLATFORM = "darwin";
    const server = createDesktopToolsServer() as {
      tools: Array<{ name: string }>;
    };
    const toolNames = server.tools.map((t) => t.name);
    for (const name of EXPECTED_TOOL_NAMES) {
      expect(toolNames).toContain(name);
    }
  });

  test("WORKER_PLATFORM=linux selects Linux tools", () => {
    process.env.WORKER_PLATFORM = "linux";
    const server = createDesktopToolsServer() as {
      tools: Array<{ name: string }>;
    };
    const toolNames = server.tools.map((t) => t.name);
    for (const name of EXPECTED_TOOL_NAMES) {
      expect(toolNames).toContain(name);
    }
  });
});
