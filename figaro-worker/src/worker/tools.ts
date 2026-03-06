/**
 * Desktop control tools for the worker agent.
 *
 * Platform-aware dispatcher that delegates to Linux (X11/xdotool)
 * or macOS (CoreGraphics/osascript) implementations based on runtime
 * detection. Platform can be overridden via WORKER_PLATFORM env var.
 */

import { createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import { createLinuxTools } from "./tools-linux";
import { createMacosTools } from "./tools-macos";
import { createPythonExecTool } from "../python/tools";
import type { NatsClient } from "../nats/client";

export const BUTTON_MAP: Record<string, string> = {
  left: "1",
  middle: "2",
  right: "3",
};

export interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

export function result(data: unknown): { content: Array<{ type: "text"; text: string }> } {
  const text =
    typeof data === "object" && data !== null
      ? JSON.stringify(data, null, 2)
      : String(data);
  return { content: [{ type: "text", text }] };
}

export function error(msg: string): { content: Array<{ type: "text"; text: string }> } {
  return { content: [{ type: "text", text: `Error: ${msg}` }] };
}

export function detectPlatform(): "linux" | "darwin" {
  const override = process.env.WORKER_PLATFORM;
  if (override === "darwin" || override === "linux") {
    return override;
  }
  return process.platform === "darwin" ? "darwin" : "linux";
}

export function createDesktopToolsServer(natsClient?: NatsClient) {
  const platform = detectPlatform();
  const desktopTools = platform === "darwin" ? createMacosTools() : createLinuxTools();

  const { pythonExec, destroySession } = createPythonExecTool(natsClient);

  const server = createSdkMcpServer({
    name: "desktop",
    version: "1.0.0",
    tools: [...desktopTools, pythonExec],
  });

  return { server, destroySession };
}
