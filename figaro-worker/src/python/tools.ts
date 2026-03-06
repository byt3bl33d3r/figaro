import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { PyodideSession } from "./session";

export function createPythonToolsServer() {
  let session: PyodideSession | null = null;

  const pythonExec = tool(
    "python_exec",
    "Execute Python code in a persistent sandboxed interpreter. " +
      "Variables and imports persist across calls. " +
      "Standard library available (json, re, math, collections, itertools, etc.). " +
      "No network or filesystem access (WASM sandbox).",
    { code: z.string().describe("Python code to execute") },
    async (args) => {
      if (!session) {
        session = new PyodideSession();
        await session.initialize();
      }
      const { stdout, stderr, result } = await session.execute(args.code);

      const parts: string[] = [];
      if (stdout) parts.push(stdout);
      if (stderr) parts.push(`stderr:\n${stderr}`);
      if (result !== null) parts.push(`=> ${result}`);
      const text = parts.length > 0 ? parts.join("\n\n") : "(no output)";

      return { content: [{ type: "text" as const, text }] };
    },
  );

  function destroySession(): void {
    session?.destroy();
    session = null;
  }

  const server = createSdkMcpServer({
    name: "python",
    version: "1.0.0",
    tools: [pythonExec],
  });

  return { server, destroySession };
}
