import { describe, test, expect } from "bun:test";
import { formatTaskPrompt, WORKER_SYSTEM_PROMPT } from "../src/worker/prompt-formatter";

describe("formatTaskPrompt", () => {
  test("returns prompt with task block", () => {
    const result = formatTaskPrompt("Buy groceries");

    expect(result).toContain("<task>");
    expect(result).toContain("Buy groceries");
    expect(result).toContain("</task>");
  });

  test("includes context block when startUrl is provided", () => {
    const result = formatTaskPrompt("Search for items", "https://example.com");

    expect(result).toContain("<context>");
    expect(result).toContain("<starting_url>https://example.com</starting_url>");
    expect(result).toContain("</context>");
    expect(result).toContain("<task>");
    expect(result).toContain("Search for items");
    expect(result).toContain("</task>");
  });

  test("does not include context block when startUrl is undefined", () => {
    const result = formatTaskPrompt("Do something");

    expect(result).not.toContain("<context>");
    expect(result).not.toContain("<starting_url>");
    expect(result).not.toContain("</context>");
  });

  test("does not include context block when startUrl is not provided", () => {
    const result = formatTaskPrompt("Task without URL");

    expect(result).not.toContain("<context>");
    expect(result).not.toContain("</context>");
  });

  test("context block appears before task block when startUrl is provided", () => {
    const result = formatTaskPrompt("My task", "https://example.com");

    const contextIndex = result.indexOf("<context>");
    const taskIndex = result.indexOf("<task>");
    expect(contextIndex).toBeLessThan(taskIndex);
  });
});

describe("WORKER_SYSTEM_PROMPT", () => {
  test("includes AskUserQuestion instruction", () => {
    expect(WORKER_SYSTEM_PROMPT).toContain("AskUserQuestion");
  });

  test("includes task query instructions", () => {
    expect(WORKER_SYSTEM_PROMPT).toContain("figaro.list_tasks()");
    expect(WORKER_SYSTEM_PROMPT).toContain("figaro.search_tasks");
    expect(WORKER_SYSTEM_PROMPT).toContain("figaro.get_task");
    expect(WORKER_SYSTEM_PROMPT).toContain("python_exec");
  });

  test("includes browser automation instructions", () => {
    expect(WORKER_SYSTEM_PROMPT).toContain("patchright-cli");
  });
});
