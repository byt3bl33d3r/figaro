import { describe, test, expect } from "bun:test";
import {
  stableStringify,
  hashToolCall,
  hashToolResult,
  detectGenericRepeat,
  detectPingPong,
  createPreToolUseHook,
  createPostToolUseHook,
  buildLoopDetectionHooks,
  LoopDetectionSession,
  LoopDetectionConfig,
  ToolCallRecord,
} from "../src/shared/loop-detection";

function makeConfig(
  overrides: Partial<LoopDetectionConfig> = {}
): LoopDetectionConfig {
  return {
    enabled: true,
    windowSize: 30,
    warningThreshold: 3,
    criticalThreshold: 5,
    pingPongWarning: 3,
    pingPongCritical: 5,
    ...overrides,
  };
}

describe("stableStringify", () => {
  test("key order independence", () => {
    const a = stableStringify({ b: 1, a: 2 });
    const b = stableStringify({ a: 2, b: 1 });
    expect(a).toBe(b);
  });

  test("nested objects sorted recursively", () => {
    const a = stableStringify({ x: { b: 1, a: 2 }, y: 3 });
    const b = stableStringify({ y: 3, x: { a: 2, b: 1 } });
    expect(a).toBe(b);
  });

  test("arrays preserve order", () => {
    const a = stableStringify([1, 2, 3]);
    const b = stableStringify([3, 2, 1]);
    expect(a).not.toBe(b);
  });

  test("truncation at 10240 chars", () => {
    const longStr = "a".repeat(20000);
    const result = stableStringify(longStr);
    expect(result.length).toBeLessThanOrEqual(10240);
  });

  test("handles null", () => {
    expect(stableStringify(null)).toBe("null");
  });

  test("handles undefined by throwing", () => {
    expect(() => stableStringify(undefined)).toThrow();
  });
});

describe("hashToolCall", () => {
  test("deterministic: same inputs produce same hash", () => {
    const a = hashToolCall("myTool", { key: "value" });
    const b = hashToolCall("myTool", { key: "value" });
    expect(a).toBe(b);
  });

  test("different inputs produce different hashes", () => {
    const a = hashToolCall("myTool", { key: "value1" });
    const b = hashToolCall("myTool", { key: "value2" });
    expect(a).not.toBe(b);
  });

  test("hash format is toolName:hexstring", () => {
    const hash = hashToolCall("readFile", { path: "/tmp" });
    expect(hash).toMatch(/^readFile:[0-9a-f]+$/);
  });
});

describe("LoopDetectionSession", () => {
  test("window trimming: history trimmed to windowSize", () => {
    const config = makeConfig({ windowSize: 10 });
    const session = new LoopDetectionSession(config);
    for (let i = 0; i < 15; i++) {
      session.recordCall("tool", { i });
    }
    expect(session.history.length).toBe(10);
  });

  test("recordResult sets resultHash on matching record", () => {
    const config = makeConfig();
    const session = new LoopDetectionSession(config);
    session.recordCall("tool", { a: 1 }, "id-1");
    session.recordResult("id-1", { output: "hello" });
    expect(session.history[0].resultHash).toBeDefined();
    expect(session.history[0].resultHash).toBe(hashToolResult({ output: "hello" }));
  });

  test("recordResult does nothing for unknown toolUseId", () => {
    const config = makeConfig();
    const session = new LoopDetectionSession(config);
    session.recordCall("tool", { a: 1 }, "id-1");
    session.recordResult("unknown-id", { output: "hello" });
    expect(session.history[0].resultHash).toBeUndefined();
  });
});

describe("detectGenericRepeat", () => {
  test("below warningThreshold returns null", () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const hash = hashToolCall("tool", { x: 1 });
    const history: ToolCallRecord[] = [
      { callHash: hash, toolName: "tool", argsHash: "a", timestamp: 1 },
      { callHash: hash, toolName: "tool", argsHash: "a", timestamp: 2 },
    ];
    expect(detectGenericRepeat(history, hash, config)).toBeNull();
  });

  test("at warningThreshold returns warning", () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const hash = hashToolCall("tool", { x: 1 });
    const history: ToolCallRecord[] = Array.from({ length: 3 }, (_, i) => ({
      callHash: hash,
      toolName: "tool",
      argsHash: "a",
      timestamp: i,
    }));
    const result = detectGenericRepeat(history, hash, config);
    expect(result).not.toBeNull();
    expect(result!.severity).toBe("warning");
    expect(result!.detector).toBe("genericRepeat");
  });

  test("at criticalThreshold returns critical", () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const hash = hashToolCall("tool", { x: 1 });
    const history: ToolCallRecord[] = Array.from({ length: 5 }, (_, i) => ({
      callHash: hash,
      toolName: "tool",
      argsHash: "a",
      timestamp: i,
    }));
    const result = detectGenericRepeat(history, hash, config);
    expect(result).not.toBeNull();
    expect(result!.severity).toBe("critical");
  });

  test("count matches actual occurrences", () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const hash = hashToolCall("tool", { x: 1 });
    const otherHash = hashToolCall("other", { y: 2 });
    const history: ToolCallRecord[] = [
      { callHash: hash, toolName: "tool", argsHash: "a", timestamp: 1 },
      { callHash: otherHash, toolName: "other", argsHash: "b", timestamp: 2 },
      { callHash: hash, toolName: "tool", argsHash: "a", timestamp: 3 },
      { callHash: hash, toolName: "tool", argsHash: "a", timestamp: 4 },
    ];
    const result = detectGenericRepeat(history, hash, config);
    expect(result).not.toBeNull();
    expect(result!.count).toBe(3);
  });
});

describe("detectPingPong", () => {
  test("no pattern (all same) returns null", () => {
    const config = makeConfig({ pingPongWarning: 3, pingPongCritical: 5 });
    const hash = hashToolCall("tool", { x: 1 });
    const history: ToolCallRecord[] = Array.from({ length: 6 }, (_, i) => ({
      callHash: hash,
      toolName: "tool",
      argsHash: "a",
      timestamp: i,
    }));
    expect(detectPingPong(history, config)).toBeNull();
  });

  test("fewer than 4 entries returns null", () => {
    const config = makeConfig({ pingPongWarning: 3, pingPongCritical: 5 });
    const hashA = hashToolCall("toolA", { x: 1 });
    const hashB = hashToolCall("toolB", { x: 2 });
    const history: ToolCallRecord[] = [
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 1 },
      { callHash: hashB, toolName: "toolB", argsHash: "b", timestamp: 2 },
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 3 },
    ];
    expect(detectPingPong(history, config)).toBeNull();
  });

  test("A-B-A-B pattern at pingPongWarning returns warning", () => {
    const config = makeConfig({ pingPongWarning: 3, pingPongCritical: 5 });
    const hashA = hashToolCall("toolA", { x: 1 });
    const hashB = hashToolCall("toolB", { x: 2 });
    // 3 alternations = 6 entries: A B A B A B
    const history: ToolCallRecord[] = [
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 1 },
      { callHash: hashB, toolName: "toolB", argsHash: "b", timestamp: 2 },
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 3 },
      { callHash: hashB, toolName: "toolB", argsHash: "b", timestamp: 4 },
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 5 },
      { callHash: hashB, toolName: "toolB", argsHash: "b", timestamp: 6 },
    ];
    const result = detectPingPong(history, config);
    expect(result).not.toBeNull();
    expect(result!.severity).toBe("warning");
    expect(result!.detector).toBe("pingPong");
  });

  test("A-B-A-B pattern at pingPongCritical returns critical", () => {
    const config = makeConfig({ pingPongWarning: 3, pingPongCritical: 5 });
    const hashA = hashToolCall("toolA", { x: 1 });
    const hashB = hashToolCall("toolB", { x: 2 });
    // 5 alternations = 10 entries: A B A B A B A B A B
    const history: ToolCallRecord[] = Array.from({ length: 10 }, (_, i) => ({
      callHash: i % 2 === 0 ? hashA : hashB,
      toolName: i % 2 === 0 ? "toolA" : "toolB",
      argsHash: i % 2 === 0 ? "a" : "b",
      timestamp: i,
    }));
    const result = detectPingPong(history, config);
    expect(result).not.toBeNull();
    expect(result!.severity).toBe("critical");
  });

  test("non-alternating sequence returns null", () => {
    const config = makeConfig({ pingPongWarning: 3, pingPongCritical: 5 });
    const hashA = hashToolCall("toolA", { x: 1 });
    const hashB = hashToolCall("toolB", { x: 2 });
    const hashC = hashToolCall("toolC", { x: 3 });
    const history: ToolCallRecord[] = [
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 1 },
      { callHash: hashB, toolName: "toolB", argsHash: "b", timestamp: 2 },
      { callHash: hashC, toolName: "toolC", argsHash: "c", timestamp: 3 },
      { callHash: hashA, toolName: "toolA", argsHash: "a", timestamp: 4 },
    ];
    expect(detectPingPong(history, config)).toBeNull();
  });
});

describe("Hook factories", () => {
  test("createPreToolUseHook returns {} for normal tool call", () => {
    const config = makeConfig();
    const session = new LoopDetectionSession(config);
    const hook = createPreToolUseHook(session, config);
    const result = hook({ tool_name: "toolA", tool_input: { a: 1 }, tool_use_id: "id-1" });
    expect(result).toEqual({});
  });

  test("createPreToolUseHook returns { systemMessage } at warning threshold", async () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const session = new LoopDetectionSession(config);
    const hook = createPreToolUseHook(session, config);
    const signal = new AbortController().signal;
    const input = { tool_name: "toolA", tool_input: { a: 1 }, tool_use_id: "id-1" };
    await hook(input, undefined, { signal }); // call 1
    await hook({ ...input, tool_use_id: "id-2" }, undefined, { signal }); // call 2
    const result = await hook({ ...input, tool_use_id: "id-3" }, undefined, { signal }); // call 3 = warning
    expect(result).toHaveProperty("systemMessage");
    expect(result).not.toHaveProperty("decision");
  });

  test("createPreToolUseHook returns { decision: 'block' } at critical threshold", async () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 5 });
    const session = new LoopDetectionSession(config);
    const hook = createPreToolUseHook(session, config);
    const signal = new AbortController().signal;
    const input = { tool_name: "toolA", tool_input: { a: 1 }, tool_use_id: "id-1" };
    for (let i = 0; i < 4; i++) {
      await hook({ ...input, tool_use_id: `id-${i}` }, undefined, { signal });
    }
    const result = await hook({ ...input, tool_use_id: "id-4" }, undefined, { signal }); // call 5 = critical
    expect(result).toHaveProperty("decision", "block");
  });

  test("createPreToolUseHook warning dedup: second warning returns {}", async () => {
    const config = makeConfig({ warningThreshold: 3, criticalThreshold: 10 });
    const session = new LoopDetectionSession(config);
    const hook = createPreToolUseHook(session, config);
    const signal = new AbortController().signal;
    const input = { tool_name: "toolA", tool_input: { a: 1 } };
    await hook({ ...input, tool_use_id: "id-1" }, undefined, { signal });
    await hook({ ...input, tool_use_id: "id-2" }, undefined, { signal });
    const first = await hook({ ...input, tool_use_id: "id-3" }, undefined, { signal }); // warning
    expect(first).toHaveProperty("systemMessage");
    const second = await hook({ ...input, tool_use_id: "id-4" }, undefined, { signal }); // deduped
    expect(second).toEqual({});
  });

  test("createPostToolUseHook records result and returns {}", async () => {
    const config = makeConfig();
    const session = new LoopDetectionSession(config);
    session.recordCall("toolA", { a: 1 }, "id-1");
    const hook = createPostToolUseHook(session);
    const signal = new AbortController().signal;
    const result = await hook({ tool_use_id: "id-1", tool_response: { out: "ok" } }, undefined, { signal });
    expect(result).toEqual({});
    expect(session.history[0].resultHash).toBeDefined();
  });

  test("buildLoopDetectionHooks returns PreToolUse and PostToolUse arrays", () => {
    const config = makeConfig();
    const session = new LoopDetectionSession(config);
    const hooks = buildLoopDetectionHooks(session, config);
    expect(Array.isArray(hooks.PreToolUse)).toBe(true);
    expect(Array.isArray(hooks.PostToolUse)).toBe(true);
    expect(hooks.PreToolUse.length).toBe(1);
    expect(hooks.PostToolUse.length).toBe(1);
    expect(Array.isArray(hooks.PreToolUse[0].hooks)).toBe(true);
    expect(typeof hooks.PreToolUse[0].hooks[0]).toBe("function");
  });
});
