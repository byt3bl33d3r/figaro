import { describe, test, expect } from "bun:test";
import { formatSupervisorPrompt, SUPERVISOR_SYSTEM_PROMPT } from "../src/supervisor/prompt-formatter";

describe("SUPERVISOR_SYSTEM_PROMPT", () => {
  test("is a non-empty string", () => {
    expect(SUPERVISOR_SYSTEM_PROMPT.length).toBeGreaterThan(100);
  });

  test("contains key instructions", () => {
    expect(SUPERVISOR_SYSTEM_PROMPT).toContain("delegate_to_worker");
    expect(SUPERVISOR_SYSTEM_PROMPT).toContain("AskUserQuestion");
    expect(SUPERVISOR_SYSTEM_PROMPT).toContain("take_screenshot");
  });
});

describe("formatSupervisorPrompt", () => {
  test("normal task includes task_context and user_request blocks", () => {
    const result = formatSupervisorPrompt("Do something", { source: "ui" });
    expect(result).toContain("<task_context>");
    expect(result).toContain("Source: ui");
    expect(result).toContain("<user_request>");
    expect(result).toContain("Do something");
    expect(result).toContain("Analyze this request");
  });

  test("includes supervisor ID when provided", () => {
    const result = formatSupervisorPrompt("Test", { source: "ui" }, null, "sup-1");
    expect(result).toContain("Supervisor ID: sup-1");
  });

  test("omits supervisor ID when not provided", () => {
    const result = formatSupervisorPrompt("Test", { source: "ui" });
    expect(result).not.toContain("Supervisor ID:");
  });

  test("optimizer source gets minimal wrapping", () => {
    const result = formatSupervisorPrompt("Optimize this prompt", { source: "optimizer" });
    expect(result).toContain("<task_context>");
    expect(result).toContain("Source: optimizer");
    expect(result).toContain("Optimize this prompt");
    expect(result).not.toContain("<user_request>");
    expect(result).not.toContain("Analyze this request");
  });

  test("healer source gets minimal wrapping", () => {
    const result = formatSupervisorPrompt("Fix this task", { source: "healer" });
    expect(result).toContain("<task_context>");
    expect(result).toContain("Source: healer");
    expect(result).not.toContain("<user_request>");
    expect(result).not.toContain("Analyze this request");
  });

  test("gateway task includes channel instructions", () => {
    const result = formatSupervisorPrompt(
      "Do task",
      { source: "gateway" },
      { channel: "telegram", chat_id: "123" },
    );
    expect(result).toContain("Channel: telegram");
    expect(result).toContain("send_screenshot");
    expect(result).toContain("messaging channel");
  });

  test("defaults source to unknown", () => {
    const result = formatSupervisorPrompt("Test", {});
    expect(result).toContain("Source: unknown");
  });

  test("normal task without channel has no channel instructions", () => {
    const result = formatSupervisorPrompt("Test", { source: "ui" });
    expect(result).not.toContain("messaging channel");
    expect(result).not.toContain("send_screenshot");
  });
});
