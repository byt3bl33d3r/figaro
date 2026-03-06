import {
  query,
  type PermissionResult,
  type PermissionMode,
} from "@anthropic-ai/claude-agent-sdk";

import type { NatsClient } from "../nats/client";
import { LoopDetectionSession, buildLoopDetectionHooks, type LoopDetectionConfig } from "../shared/loop-detection";
import { serializeMessage } from "../shared/serialize";
import { HelpRequestHandler } from "../worker/help-request";
import {
  formatSupervisorPrompt,
  SUPERVISOR_SYSTEM_PROMPT,
} from "./prompt-formatter";
import { createPythonToolsServer } from "../python/tools";
import { createSupervisorToolsServer } from "./tools";

interface TaskSession {
  taskId: string;
  prompt: string;
  options: Record<string, unknown>;
  sourceMetadata?: Record<string, unknown> | null;
}

export class SupervisorExecutor {
  private client: NatsClient;
  private model: string;
  private maxTurns: number | undefined;
  private claudeCodePath: string | undefined;
  private loopDetection: LoopDetectionConfig | undefined;
  private helpHandler: HelpRequestHandler;
  private sessions: Map<string, TaskSession> = new Map();
  private abortControllers: Map<string, AbortController> = new Map();

  constructor(
    client: NatsClient,
    model: string = "claude-opus-4-6",
    maxTurns?: number,
    claudeCodePath?: string,
    loopDetection?: LoopDetectionConfig,
  ) {
    this.client = client;
    this.model = model;
    this.maxTurns = maxTurns;
    this.claudeCodePath = claudeCodePath;
    this.loopDetection = loopDetection;
    this.helpHandler = new HelpRequestHandler(client);
  }

  stopTask(taskId: string): boolean {
    const controller = this.abortControllers.get(taskId);
    if (controller) {
      console.log(`[supervisor] Stopping task ${taskId}`);
      controller.abort();
      return true;
    }
    return false;
  }

  async handleTask(payload: Record<string, unknown>): Promise<void> {
    const taskId = payload.task_id as string;
    const prompt = (payload.prompt as string) ?? "";
    const options = (payload.options ?? {}) as Record<string, unknown>;
    const sourceMetadata = payload.source_metadata as Record<string, unknown> | null | undefined;

    if (!taskId) {
      console.error("[supervisor] Received task without task_id");
      return;
    }

    console.log(`[supervisor] Processing task ${taskId}: ${prompt.slice(0, 50)}...`);

    const session: TaskSession = {
      taskId,
      prompt,
      options,
      sourceMetadata,
    };
    this.sessions.set(taskId, session);

    // Fire and forget — allows concurrent task processing
    this.runSession(session).catch((e) => {
      console.error(`[supervisor] Unhandled error in session ${taskId}: ${e}`);
    });
  }

  private async runSession(session: TaskSession): Promise<void> {
    const { taskId, prompt, options, sourceMetadata } = session;
    const { server: pythonTools, destroySession } = createPythonToolsServer();

    try {
      // Notify we're busy
      await this.client.sendStatus("busy");

      // Format the prompt with supervisor instructions
      const formattedPrompt = formatSupervisorPrompt(
        prompt,
        options,
        sourceMetadata,
        this.client.id,
      );

      // Create a fresh MCP server per session to avoid lifecycle issues
      const toolsServer = createSupervisorToolsServer(
        this.client,
        sourceMetadata,
      );

      // canUseTool callback: intercept AskUserQuestion, allow everything else
      const canUseTool = async (
        toolName: string,
        inputData: Record<string, unknown>,
      ): Promise<PermissionResult> => {
        if (toolName !== "AskUserQuestion") {
          return { behavior: "allow", updatedInput: inputData };
        }

        const questions = (inputData.questions ?? []) as Array<Record<string, unknown>>;
        console.log(
          `[supervisor] [${taskId.slice(0, 8)}] Intercepted AskUserQuestion with ${questions.length} question(s)`,
        );

        const answers = await this.helpHandler.requestHelp(
          taskId,
          questions,
          null,
          300,
        );

        if (answers) {
          console.log(`[supervisor] [${taskId.slice(0, 8)}] Received human response`);
          return {
            behavior: "allow",
            updatedInput: { questions, answers },
          };
        }

        console.warn(`[supervisor] [${taskId.slice(0, 8)}] Timeout waiting for response`);
        return {
          behavior: "deny",
          message: "Timeout waiting for human response to clarifying question",
        };
      };

      const permissionMode = (options.permission_mode as PermissionMode | undefined) ?? "bypassPermissions";

      const hooks = this.loopDetection?.enabled
        ? buildLoopDetectionHooks(
            new LoopDetectionSession(this.loopDetection),
            this.loopDetection,
          )
        : undefined;

      const abortController = new AbortController();
      this.abortControllers.set(taskId, abortController);

      const q = query({
        prompt: formattedPrompt,
        options: {
          systemPrompt: SUPERVISOR_SYSTEM_PROMPT,
          permissionMode,
          allowDangerouslySkipPermissions: permissionMode === "bypassPermissions",
          maxTurns: (options.max_turns as number | undefined) ?? this.maxTurns,
          model: this.model,
          canUseTool,
          mcpServers: { orchestrator: toolsServer, python: pythonTools },
          abortController,
          stderr: (data: string) => {
            console.error(`[supervisor] [${taskId.slice(0, 8)}] stderr: ${data.trimEnd()}`);
          },
          ...(this.claudeCodePath ? { pathToClaudeCodeExecutable: this.claudeCodePath } : {}),
          ...(hooks ? { hooks } : {}),
        },
      });

      let resultMessage: Record<string, unknown> | null = null;

      try {
        for await (const message of q) {
          const serialized = serializeMessage(message);
          serialized.task_id = taskId;

          try {
            await this.client.publishTaskMessage(taskId, serialized);
          } catch (e) {
            console.warn(`[supervisor] [${taskId.slice(0, 8)}] Failed to publish message: ${e}`);
          }

          if ((message as unknown as Record<string, unknown>).type === "result") {
            resultMessage = serialized;
          }
        }
      } finally {
        q.close();
        // Force-abort the subprocess if close() didn't terminate it within 5s
        if (!abortController.signal.aborted) {
          setTimeout(() => {
            if (!abortController.signal.aborted) {
              console.warn(`[supervisor] [${taskId.slice(0, 8)}] Force-aborting query subprocess`);
              abortController.abort();
            }
          }, 5_000);
        }
      }

      await this.client.publishTaskComplete(taskId, resultMessage);
      console.log(`[supervisor] [${taskId.slice(0, 8)}] Session completed successfully`);
    } catch (e) {
      const controller = this.abortControllers.get(taskId);
      if (controller?.signal.aborted) {
        console.log(`[supervisor] [${taskId.slice(0, 8)}] Task was stopped`);
      } else {
        const errMsg = e instanceof Error ? e.message : String(e);
        console.error(`[supervisor] [${taskId.slice(0, 8)}] Session failed: ${errMsg}`);
        await this.client.publishTaskError(taskId, errMsg);
      }
    } finally {
      this.sessions.delete(taskId);
      destroySession();
      this.abortControllers.delete(taskId);
      // Notify idle only when last session ends
      if (this.sessions.size === 0) {
        await this.client.sendStatus("idle");
      }
    }
  }
}
