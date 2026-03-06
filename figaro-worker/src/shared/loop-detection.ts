import { createHash } from "crypto";

export type LoopDetectionConfig = {
  enabled: boolean;
  windowSize: number;
  warningThreshold: number;
  criticalThreshold: number;
  pingPongWarning: number;
  pingPongCritical: number;
};

export type ToolCallRecord = {
  callHash: string;
  toolName: string;
  argsHash: string;
  toolUseId?: string;
  resultHash?: string;
  timestamp: number;
};

export type DetectionResult = {
  detected: boolean;
  severity: "warning" | "critical";
  detector: string;
  count: number;
  message: string;
};

export function stableStringify(value: unknown): string {
  const result = stableStringifyInner(value);
  return result.length > 10240 ? result.slice(0, 10240) : result;
}

function stableStringifyInner(value: unknown): string {
  if (value === null || value === undefined) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    const items = value.map((item) => stableStringifyInner(item));
    return `[${items.join(",")}]`;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    const pairs = keys.map(
      (key) => `${JSON.stringify(key)}:${stableStringifyInner(obj[key])}`
    );
    return `{${pairs.join(",")}}`;
  }
  return JSON.stringify(value);
}

export function hashValue(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

export function hashToolCall(toolName: string, toolInput: unknown): string {
  return `${toolName}:${hashValue(stableStringify(toolInput))}`;
}

export function hashToolResult(result: unknown): string {
  return hashValue(stableStringify(result));
}

export function detectGenericRepeat(
  history: ToolCallRecord[],
  currentHash: string,
  config: LoopDetectionConfig
): DetectionResult | null {
  const count = history.filter((r) => r.callHash === currentHash).length;
  const toolName = currentHash.split(":")[0];

  if (count >= config.criticalThreshold) {
    return {
      detected: true,
      severity: "critical",
      detector: "genericRepeat",
      count,
      message: `LOOP BLOCKED: '${toolName}' has been called with identical arguments ${count} times, exceeding the safety threshold. This call has been blocked. You must use a different approach.`,
    };
  }

  if (count >= config.warningThreshold) {
    return {
      detected: true,
      severity: "warning",
      detector: "genericRepeat",
      count,
      message: `LOOP DETECTED: You have called '${toolName}' with identical arguments ${count} times in the last ${config.windowSize} tool calls. This appears to be a repetitive loop. Change your approach — try different parameters, a different tool, or report that the task cannot be completed.`,
    };
  }

  return null;
}

export function detectPingPong(
  history: ToolCallRecord[],
  config: LoopDetectionConfig
): DetectionResult | null {
  if (history.length < 4) {
    return null;
  }

  const lastHash = history[history.length - 1].callHash;
  const secondLastHash = history[history.length - 2].callHash;

  if (lastHash === secondLastHash) {
    return null;
  }

  const hashA = secondLastHash;
  const hashB = lastHash;

  let count = 0;
  for (let i = history.length - 1; i >= 0; i--) {
    const expectedHash = (history.length - 1 - i) % 2 === 0 ? hashB : hashA;
    if (history[i].callHash !== expectedHash) {
      break;
    }
    count++;
  }

  const alternations = Math.floor(count / 2);

  if (alternations < config.pingPongWarning) {
    return null;
  }

  const toolA = hashA.split(":")[0];
  const toolB = hashB.split(":")[0];

  if (alternations >= config.pingPongCritical) {
    return {
      detected: true,
      severity: "critical",
      detector: "pingPong",
      count: alternations,
      message: `LOOP BLOCKED: Alternating pattern between '${toolA}' and '${toolB}' (${alternations} alternations) exceeds the safety threshold. This call has been blocked. You must use a different approach.`,
    };
  }

  return {
    detected: true,
    severity: "warning",
    detector: "pingPong",
    count: alternations,
    message: `LOOP DETECTED: You are alternating between '${toolA}' and '${toolB}' in a repetitive pattern (${alternations} alternations). Break this cycle — try a different strategy or report that the task cannot be completed.`,
  };
}

export class LoopDetectionSession {
  history: ToolCallRecord[];
  warnedKeys: Set<string>;
  config: LoopDetectionConfig;

  constructor(config: LoopDetectionConfig) {
    this.config = config;
    this.history = [];
    this.warnedKeys = new Set();
  }

  recordCall(
    toolName: string,
    toolInput: unknown,
    toolUseId?: string
  ): string {
    const argsHash = hashValue(stableStringify(toolInput));
    const callHash = hashToolCall(toolName, toolInput);
    const record: ToolCallRecord = {
      callHash,
      toolName,
      argsHash,
      toolUseId,
      timestamp: Date.now(),
    };
    this.history.push(record);
    if (this.history.length > this.config.windowSize) {
      this.history = this.history.slice(-this.config.windowSize);
    }
    return callHash;
  }

  recordResult(toolUseId: string, result: unknown): void {
    for (let i = this.history.length - 1; i >= 0; i--) {
      if (this.history[i].toolUseId === toolUseId) {
        this.history[i].resultHash = hashToolResult(result);
        break;
      }
    }
  }

  detect(): DetectionResult | null {
    if (this.history.length === 0) {
      return null;
    }

    const lastEntry = this.history[this.history.length - 1];

    const genericResult = detectGenericRepeat(
      this.history,
      lastEntry.callHash,
      this.config
    );
    if (genericResult) {
      if (genericResult.severity === "warning") {
        const key = `${genericResult.detector}:${lastEntry.callHash}`;
        if (this.hasWarned(key)) {
          // Skip warning if already warned for this key
        } else {
          this.markWarned(key);
          return genericResult;
        }
      } else {
        return genericResult;
      }
    }

    const pingPongResult = detectPingPong(this.history, this.config);
    if (pingPongResult) {
      if (pingPongResult.severity === "warning") {
        const key = `${pingPongResult.detector}:${lastEntry.callHash}`;
        if (this.hasWarned(key)) {
          // Skip warning if already warned for this key
        } else {
          this.markWarned(key);
          return pingPongResult;
        }
      } else {
        return pingPongResult;
      }
    }

    return null;
  }

  markWarned(key: string): void {
    this.warnedKeys.add(key);
  }

  hasWarned(key: string): boolean {
    return this.warnedKeys.has(key);
  }
}

export function createPreToolUseHook(
  session: LoopDetectionSession,
  config: LoopDetectionConfig
): (input: Record<string, unknown>) => Record<string, unknown> {
  return (input: Record<string, unknown>): Record<string, unknown> => {
    if (!config.enabled) {
      return {};
    }

    const toolName = input.tool_name as string;
    const toolInput = input.tool_input;
    const toolUseId = input.tool_use_id as string | undefined;

    session.recordCall(toolName, toolInput, toolUseId);
    const result = session.detect();

    if (!result) {
      return {};
    }

    if (result.severity === "critical") {
      return { decision: "block", reason: result.message };
    }

    return { systemMessage: result.message };
  };
}

export function createPostToolUseHook(
  session: LoopDetectionSession
): (input: Record<string, unknown>) => Record<string, unknown> {
  return (input: Record<string, unknown>): Record<string, unknown> => {
    const toolUseId = input.tool_use_id as string | undefined;
    const toolResponse = input.tool_response;

    if (toolUseId) {
      session.recordResult(toolUseId, toolResponse);
    }

    return {};
  };
}

export function buildLoopDetectionHooks(
  session: LoopDetectionSession,
  config: LoopDetectionConfig
): {
  preToolUse: Array<{
    matcher: () => boolean;
    callback: (input: Record<string, unknown>) => Record<string, unknown>;
  }>;
  postToolUse: Array<{
    matcher: () => boolean;
    callback: (input: Record<string, unknown>) => Record<string, unknown>;
  }>;
} {
  return {
    preToolUse: [
      {
        matcher: () => true,
        callback: createPreToolUseHook(session, config),
      },
    ],
    postToolUse: [
      {
        matcher: () => true,
        callback: createPostToolUseHook(session),
      },
    ],
  };
}
