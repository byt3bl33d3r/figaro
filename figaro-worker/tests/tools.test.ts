import { describe, test, expect, mock } from "bun:test";

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

import { createDesktopToolsServer } from "../src/worker/tools";

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
    expect(toolNames).toContain("screenshot");
    expect(toolNames).toContain("mouse_click");
    expect(toolNames).toContain("mouse_move");
    expect(toolNames).toContain("type_text");
    expect(toolNames).toContain("press_key");
    expect(toolNames).toContain("scroll");
    expect(toolNames).toContain("mouse_drag");
  });
});
