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
    expect(result).toContain("search memories");
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

  test("returns plain string when no attachments", () => {
    const result = formatSupervisorPrompt("Do something", { source: "ui" });
    expect(typeof result).toBe("string");
  });

  test("returns content blocks array when image attachments present", () => {
    const result = formatSupervisorPrompt("Check this image", {
      source: "gateway",
      attachments: [
        {
          type: "image",
          media_type: "image/jpeg",
          data: "abc123base64data",
          filename: "photo.jpg",
        },
      ],
    });
    expect(Array.isArray(result)).toBe(true);
    const blocks = result as Array<Record<string, unknown>>;
    // First block should be text with the formatted prompt
    expect(blocks[0]).toEqual(
      expect.objectContaining({ type: "text" }),
    );
    expect((blocks[0] as { type: "text"; text: string }).text).toContain("Check this image");
    // Second block should be the image
    expect(blocks[1]).toEqual({
      type: "image",
      source: {
        type: "base64",
        media_type: "image/jpeg",
        data: "abc123base64data",
      },
    });
  });

  test("handles document attachments as text notes in content blocks", () => {
    const result = formatSupervisorPrompt("Review this", {
      source: "gateway",
      attachments: [
        {
          type: "document",
          media_type: "application/pdf",
          data: "pdfdata",
          filename: "report.pdf",
        },
      ],
    });
    expect(Array.isArray(result)).toBe(true);
    const blocks = result as Array<Record<string, unknown>>;
    expect(blocks).toHaveLength(2); // text + document text note
    expect(blocks[0]).toEqual(expect.objectContaining({ type: "text" }));
    expect(blocks[1]).toEqual({
      type: "text",
      text: "[Attached file: report.pdf]",
    });
  });

  test("mixed image and document attachments returns content blocks", () => {
    const result = formatSupervisorPrompt("Check these", {
      source: "gateway",
      attachments: [
        {
          type: "image",
          media_type: "image/png",
          data: "imagedata",
        },
        {
          type: "document",
          media_type: "application/pdf",
          data: "pdfdata",
          filename: "doc.pdf",
        },
      ],
    });
    expect(Array.isArray(result)).toBe(true);
    const blocks = result as Array<Record<string, unknown>>;
    expect(blocks).toHaveLength(3); // text + image + document text note
    expect(blocks[0]).toEqual(expect.objectContaining({ type: "text" }));
    expect(blocks[1]).toEqual(expect.objectContaining({ type: "image" }));
    expect(blocks[2]).toEqual({
      type: "text",
      text: "[Attached file: doc.pdf]",
    });
  });
});
