import {
  query,
  type PermissionResult,
  type PermissionMode,
  type SDKMessage,
} from "@anthropic-ai/claude-agent-sdk";

import type { NatsClient } from "../nats/client";
import type { TaskPayload } from "../types";
import { HelpRequestHandler } from "./help-request";
import { formatTaskPrompt } from "./prompt-formatter";
import { createDesktopToolsServer } from "./tools";

// Map TS SDK type names to Python SDK class names expected by the UI
const TYPE_NAME_MAP: Record<string, string> = {
  assistant: "AssistantMessage",
  user: "UserMessage",
  result: "ResultMessage",
  system: "SystemMessage",
};

function serializeMessage(msg: SDKMessage): Record<string, unknown> {
  const record = msg as unknown as Record<string, unknown>;
  const sdkType = (record.type as string) ?? "unknown";
  const result: Record<string, unknown> = {
    ...record,
    __type__: TYPE_NAME_MAP[sdkType] ?? sdkType,
  };

  // TS SDK nests content in message.content for assistant messages,
  // but the UI expects content at the top level (matching Python SDK)
  if (sdkType === "assistant" && record.message && typeof record.message === "object") {
    const apiMessage = record.message as Record<string, unknown>;
    if (apiMessage.content) {
      result.content = apiMessage.content;
    }
    if (apiMessage.model) {
      result.model = apiMessage.model;
    }
  }

  return result;
}

export class TaskExecutor {
  private client: NatsClient;
  private model: string;
  private claudeCodePath: string | undefined;
  private helpHandler: HelpRequestHandler;
  private currentTaskId: string | null = null;

  constructor(client: NatsClient, model: string = "claude-opus-4-6", claudeCodePath?: string) {
    this.client = client;
    this.model = model;
    this.claudeCodePath = claudeCodePath;
    this.helpHandler = new HelpRequestHandler(client);
  }

  async handleTask(payload: TaskPayload): Promise<void> {
    const taskId = payload.task_id;
    const prompt = payload.prompt ?? "";
    const optionsDict = (payload.options ?? {}) as Record<string, unknown>;

    if (!taskId) {
      console.error("[executor] Received task without task_id");
      return;
    }

    console.log(`[executor] Executing task ${taskId}: ${prompt.slice(0, 50)}...`);

    try {
      await this.executeTask(taskId, prompt, optionsDict);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      console.error(`[executor] Task ${taskId} failed: ${errMsg}`);
      await this.client.publishTaskError(taskId, errMsg);
    } finally {
      this.currentTaskId = null;
    }
  }

  private async executeTask(
    taskId: string,
    prompt: string,
    optionsDict: Record<string, unknown>,
  ): Promise<void> {
    this.currentTaskId = taskId;

    const startUrl = optionsDict.start_url as string | undefined;
    const formattedPrompt = formatTaskPrompt(prompt, startUrl);

    const desktopTools = createDesktopToolsServer();

    const canUseTool = async (
      toolName: string,
      inputData: Record<string, unknown>,
    ): Promise<PermissionResult> => {
      if (toolName !== "AskUserQuestion") {
        return { behavior: "allow", updatedInput: inputData };
      }

      const questions = (inputData.questions ?? []) as Array<Record<string, unknown>>;

      if (!this.currentTaskId) {
        console.warn("[executor] AskUserQuestion: no current task ID");
        return { behavior: "deny", message: "No active task context" };
      }

      console.log(`[executor] AskUserQuestion: ${questions.length} question(s)`);

      const answers = await this.helpHandler.requestHelp(
        this.currentTaskId,
        questions,
        null,
        1800,
      );

      if (answers) {
        console.log("[executor] Received human response for AskUserQuestion");
        return {
          behavior: "allow",
          updatedInput: {
            questions,
            answers,
          },
        };
      } else {
        console.warn("[executor] Timeout or error waiting for human response");
        return {
          behavior: "deny",
          message: "Timeout waiting for human response. Proceed with your best judgment.",
        };
      }
    };

    const permissionMode = (optionsDict.permission_mode as PermissionMode | undefined) ?? "bypassPermissions";

    const q = query({
      prompt: formattedPrompt,
      options: {
        permissionMode,
        allowDangerouslySkipPermissions: permissionMode === "bypassPermissions",
        maxTurns: optionsDict.max_turns as number | undefined,
        model: this.model,
        settingSources: ["user", "project"],
        canUseTool,
        mcpServers: { desktop: desktopTools },
        ...(this.claudeCodePath ? { pathToClaudeCodeExecutable: this.claudeCodePath } : {}),
      },
    });

    let resultMessage: Record<string, unknown> | null = null;

    try {
      for await (const message of q) {
        const serialized = serializeMessage(message);
        serialized.task_id = taskId;

        await this.client.publishTaskMessage(taskId, serialized);

        if ((message as unknown as Record<string, unknown>).type === "result") {
          resultMessage = serialized;
        }
      }
    } finally {
      q.close();
    }

    await this.client.publishTaskComplete(taskId, resultMessage);
    console.log(`[executor] Task ${taskId} completed`);
  }
}
