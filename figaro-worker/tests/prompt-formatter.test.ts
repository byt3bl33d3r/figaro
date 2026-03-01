import { describe, test, expect } from "bun:test";
import { formatTaskPrompt } from "../src/worker/prompt-formatter";

describe("formatTaskPrompt", () => {
  test("returns prompt with task and instructions blocks", () => {
    const result = formatTaskPrompt("Buy groceries");

    expect(result).toContain("<task>");
    expect(result).toContain("Buy groceries");
    expect(result).toContain("</task>");
    expect(result).toContain("<instructions>");
    expect(result).toContain("</instructions>");
  });

  test("includes context block when startUrl is provided", () => {
    const result = formatTaskPrompt("Search for items", "https://example.com");

    expect(result).toContain("<context>");
    expect(result).toContain("<starting_url>https://example.com</starting_url>");
    expect(result).toContain("</context>");
    expect(result).toContain("<task>");
    expect(result).toContain("Search for items");
    expect(result).toContain("</task>");
    expect(result).toContain("<instructions>");
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

  test("includes AskUserQuestion instruction", () => {
    const result = formatTaskPrompt("Any task");

    expect(result).toContain("AskUserQuestion");
    expect(result).toContain("CRITICAL");
  });

  test("context block appears before task block when startUrl is provided", () => {
    const result = formatTaskPrompt("My task", "https://example.com");

    const contextIndex = result.indexOf("<context>");
    const taskIndex = result.indexOf("<task>");
    expect(contextIndex).toBeLessThan(taskIndex);
  });

  test("instructions block appears after task block", () => {
    const result = formatTaskPrompt("My task");

    const taskEndIndex = result.indexOf("</task>");
    const instructionsIndex = result.indexOf("<instructions>");
    expect(taskEndIndex).toBeLessThan(instructionsIndex);
  });
});
