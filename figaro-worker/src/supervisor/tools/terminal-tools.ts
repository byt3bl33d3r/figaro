import { tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod/v4";
import { Subjects } from "../../nats/subjects";
import { result, error, type JsonData } from "../tool-helpers";

export function createTerminalTools(
  natsRequest: (subject: string, data: JsonData, timeout?: number) => Promise<JsonData>,
) {
  const sshRunCommand = tool(
    "ssh_run_command",
    "Execute a shell command on a worker via SSH. Returns stdout, stderr, and exit code. " +
      "Only works for workers with ssh:// connection URLs.",
    {
      worker_id: z.string().describe("The worker ID to run the command on"),
      command: z.string().describe("The shell command to execute"),
      timeout: z.number().optional().describe("Command timeout in seconds (default: 30)"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_SSH,
        {
          action: "run_command",
          worker_id: args.worker_id,
          command: args.command,
          timeout: args.timeout,
        },
        Math.max(30_000, ((args.timeout ?? 30) + 5) * 1000),
      );
      if (response.error) {
        return error(response.error);
      }
      return result(response);
    },
  );

  const telnetRunCommand = tool(
    "telnet_run_command",
    "Execute a command on a worker via telnet. Returns the terminal output. " +
      "Only works for workers with telnet:// connection URLs. " +
      "Note: no exit code is available via telnet.",
    {
      worker_id: z.string().describe("The worker ID to run the command on"),
      command: z.string().describe("The command to execute"),
      timeout: z.number().optional().describe("Read timeout in seconds (default: 10)"),
    },
    async (args) => {
      const response = await natsRequest(
        Subjects.API_TELNET,
        {
          action: "run_command",
          worker_id: args.worker_id,
          command: args.command,
          timeout: args.timeout,
        },
        Math.max(30_000, ((args.timeout ?? 10) + 5) * 1000),
      );
      if (response.error) {
        return error(response.error);
      }
      return result(response);
    },
  );

  return { sshRunCommand, telnetRunCommand };
}
