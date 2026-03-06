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

import { createPythonToolsServer } from "../src/python/tools";

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
  const { server, destroySession } = createPythonToolsServer();
  const s = server as unknown as ServerResult;
  return { server: s, destroySession, tool: s.tools[0] };
}

describe("createPythonToolsServer", () => {
  test("returns server and destroySession", () => {
    const { server, destroySession } = createPythonToolsServer();
    expect(server).toBeTruthy();
    expect(typeof destroySession).toBe("function");
  });

  test("server has correct name and version", () => {
    const { server } = getServer();
    expect(server.name).toBe("python");
    expect(server.version).toBe("1.0.0");
  });

  test("server exposes python_exec tool", () => {
    const { server } = getServer();
    expect(server.tools.length).toBe(1);
    expect(server.tools[0].name).toBe("python_exec");
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
