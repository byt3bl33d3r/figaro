import {
  query,
  type PermissionResult,
  type PermissionMode,
} from "@anthropic-ai/claude-agent-sdk";

import type { NatsClient } from "../nats/client";
import type { TaskPayload } from "../types";
import { serializeMessage } from "../shared/serialize";
import { LoopDetectionSession, buildLoopDetectionHooks, type LoopDetectionConfig } from "../shared/loop-detection";
import { traced } from "../tracing/tracer";
import { HelpRequestHandler } from "./help-request";
import { formatTaskPrompt, WORKER_SYSTEM_PROMPT } from "./prompt-formatter";
import { createDesktopToolsServer } from "./tools";

export class TaskExecutor {
  private client: NatsClient;
  private model: string;
  private claudeCodePath: string | undefined;
  private loopDetection: LoopDetectionConfig | undefined;
  private helpHandler: HelpRequestHandler;
  private currentTaskId: string | null = null;
  private abortController: AbortController | null = null;

  constructor(
    client: NatsClient,
    model: string = "claude-opus-4-6",
    claudeCodePath?: string,
    loopDetection?: LoopDetectionConfig,
  ) {
    this.client = client;
    this.model = model;
    this.claudeCodePath = claudeCodePath;
    this.loopDetection = loopDetection;
    this.helpHandler = new HelpRequestHandler(client);
  }

  async handleTask(payload: TaskPayload): Promise<void> {
    await traced("worker.handle_task", async (span) => {
      const taskId = payload.task_id;
      const prompt = payload.prompt ?? "";
      const optionsDict = (payload.options ?? {}) as Record<string, unknown>;

      if (!taskId) {
        console.error("[executor] Received task without task_id");
        return;
      }

      span.setAttribute("task.id", taskId);
      console.log(`[executor] Executing task ${taskId}: ${prompt.slice(0, 50)}...`);

      try {
        await this.executeTask(taskId, prompt, optionsDict);
      } catch (e) {
        if (this.abortController?.signal.aborted) {
          console.log(`[executor] Task ${taskId} was stopped`);
          return;
        }
        const errMsg = e instanceof Error ? e.message : String(e);
        console.error(`[executor] Task ${taskId} failed: ${errMsg}`);
        await this.client.publishTaskError(taskId, errMsg);
      } finally {
        this.currentTaskId = null;
        this.abortController = null;
      }
    });
  }

  stopTask(taskId: string): boolean {
    if (this.currentTaskId === taskId && this.abortController) {
      console.log(`[executor] Stopping task ${taskId}`);
      this.abortController.abort();
      return true;
    }
    return false;
  }

  private async executeTask(
    taskId: string,
    prompt: string,
    optionsDict: Record<string, unknown>,
  ): Promise<void> {
    await traced("worker.execute_task", async (span) => {
    this.currentTaskId = taskId;
    span.setAttribute("task.id", taskId);

    const startUrl = optionsDict.start_url as string | undefined;
    const formattedPrompt = await traced("worker.format_task_prompt", async () => {
      return formatTaskPrompt(prompt, startUrl);
    });

    const { server: desktopTools, destroySession } = createDesktopToolsServer(this.client);

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

    const hooks = this.loopDetection?.enabled
      ? buildLoopDetectionHooks(
          new LoopDetectionSession(this.loopDetection),
          this.loopDetection,
        )
      : undefined;

    this.abortController = new AbortController();
    const abortController = this.abortController;

    const q = query({
      prompt: formattedPrompt,
      options: {
        systemPrompt: {
          type: "preset" as const,
          preset: "claude_code" as const,
          append: WORKER_SYSTEM_PROMPT,
        },
        permissionMode,
        allowDangerouslySkipPermissions: permissionMode === "bypassPermissions",
        maxTurns: optionsDict.max_turns as number | undefined,
        model: this.model,
        settings: {
          autoMemoryEnabled: false
        },
        settingSources: ["user", "project"],
        canUseTool,
        disallowedTools: ["Memory"],
        mcpServers: { desktop: desktopTools },
        abortController,
        ...(this.claudeCodePath ? { pathToClaudeCodeExecutable: this.claudeCodePath } : {}),
        ...(hooks ? { hooks } : {}),
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
      destroySession();
      if (!abortController.signal.aborted) {
        setTimeout(() => {
          if (!abortController.signal.aborted) {
            console.warn(`[executor] [${taskId.slice(0, 8)}] Force-aborting query subprocess`);
            abortController.abort();
          }
        }, 5_000);
      }
    }

    await this.client.publishTaskComplete(taskId, resultMessage);
    console.log(`[executor] Task ${taskId} completed`);
    });
  }
}
