import { createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import type { NatsClient } from "../nats/client";
import { createPythonExecTool } from "../python/tools";
import { createNatsRequest, type JsonData } from "./tool-helpers";
import { createDelegationTools } from "./tools/delegation-tools";
import { createTaskTools } from "./tools/task-tools";
import { createVncTools } from "./tools/vnc-tools";
import { createTerminalTools } from "./tools/terminal-tools";

export function createSupervisorToolsServer(
  client: NatsClient,
  sourceMetadata?: JsonData | null,
) {
  const { pythonExec, destroySession: destroyPySession } = createPythonExecTool(client);

  const natsRequest = createNatsRequest(client);

  const { delegateToWorker, listWorkers, getSupervisorStatus } =
    createDelegationTools(client, natsRequest);

  const {
    listScheduledTasks,
    getScheduledTask,
    createScheduledTask,
    updateScheduledTask,
    deleteScheduledTask,
    toggleScheduledTask,
  } = createTaskTools(natsRequest);

  const {
    takeScreenshot,
    typeText,
    pressKey,
    clickTool,
    unlockScreen,
    sendScreenshot,
  } = createVncTools(client, natsRequest, sourceMetadata);

  const { sshRunCommand, telnetRunCommand } = createTerminalTools(natsRequest);

  function destroySession(): void {
    destroyPySession();
  }

  const server = createSdkMcpServer({
    name: "orchestrator",
    version: "1.0.0",
    tools: [
      delegateToWorker,
      listWorkers,
      getSupervisorStatus,
      listScheduledTasks,
      getScheduledTask,
      createScheduledTask,
      updateScheduledTask,
      deleteScheduledTask,
      toggleScheduledTask,
      takeScreenshot,
      typeText,
      pressKey,
      clickTool,
      unlockScreen,
      sendScreenshot,
      sshRunCommand,
      telnetRunCommand,
      pythonExec,
    ],
  });

  return { server, destroySession };
}
