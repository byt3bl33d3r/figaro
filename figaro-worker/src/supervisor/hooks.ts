import type { NatsClient } from "../nats/client";

export function preToolUseHook(input: Record<string, unknown>): Record<string, unknown> {
  const toolName = (input.tool_name as string) ?? "unknown";
  console.log(`[supervisor] PreToolUse: ${toolName}`);
  return {};
}

export function createPostToolUseHook(
  client: NatsClient,
  taskId: string,
): (input: Record<string, unknown>) => Promise<Record<string, unknown>> {
  return async (input: Record<string, unknown>): Promise<Record<string, unknown>> => {
    const toolName = (input.tool_name as string) ?? "unknown";
    const toolResponse = input.tool_response;

    console.log(`[supervisor] PostToolUse: ${toolName} completed`);

    try {
      await client.publishTaskMessage(taskId, {
        tool_name: toolName,
        result_summary: toolResponse
          ? String(toolResponse).slice(0, 500)
          : null,
      });
    } catch (e) {
      console.warn(`[supervisor] Failed to stream tool result: ${e}`);
    }

    return {};
  };
}

export function stopHook(): Record<string, unknown> {
  console.log("[supervisor] Stop hook triggered - cleaning up session...");
  return {};
}
