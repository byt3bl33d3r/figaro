import type { SDKMessage } from "@anthropic-ai/claude-agent-sdk";

// Map TS SDK type names to Python SDK class names expected by the UI
export const TYPE_NAME_MAP: Record<string, string> = {
  assistant: "AssistantMessage",
  user: "UserMessage",
  result: "ResultMessage",
  system: "SystemMessage",
};

export function serializeMessage(msg: SDKMessage): Record<string, unknown> {
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
    if (apiMessage.usage) {
      result.usage = apiMessage.usage;
    }
    if (apiMessage.id) {
      result.message_id = apiMessage.id;
    }
  }

  return result;
}
