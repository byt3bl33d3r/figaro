/**
 * Span chain utilities for asserting trace hierarchies in tests.
 *
 * Same algorithm as the Python version for cross-language comparability.
 */

export interface SpanEntry {
  name: string;
  depth: number;
}

export interface SpanData {
  name: string;
  spanId: string;
  parentSpanId?: string;
  startTime: number;
}

/**
 * Build a depth-first span chain from flat span data.
 *
 * Constructs a parent-child tree, DFS with children sorted by startTime,
 * normalizes repeats with " (repeat)" suffix, and optionally filters by name prefix.
 */
export function getSpanChain(
  spans: SpanData[],
  includeAuto: boolean = false,
): SpanEntry[] {
  // Build parent -> children map
  const childrenMap = new Map<string, SpanData[]>();
  const roots: SpanData[] = [];

  for (const span of spans) {
    if (!span.parentSpanId) {
      roots.push(span);
    } else {
      const siblings = childrenMap.get(span.parentSpanId) ?? [];
      siblings.push(span);
      childrenMap.set(span.parentSpanId, siblings);
    }
  }

  // Sort roots and children by startTime
  roots.sort((a, b) => a.startTime - b.startTime);
  for (const children of childrenMap.values()) {
    children.sort((a, b) => a.startTime - b.startTime);
  }

  // DFS traversal
  const result: SpanEntry[] = [];
  const seen = new Map<string, number>();

  function dfs(span: SpanData, depth: number): void {
    // Filter auto-instrumented spans unless includeAuto is true
    if (!includeAuto && !span.name.includes(".")) {
      return;
    }

    const count = (seen.get(span.name) ?? 0) + 1;
    seen.set(span.name, count);

    const name = count > 1 ? `${span.name} (repeat)` : span.name;
    result.push({ name, depth });

    const children = childrenMap.get(span.spanId) ?? [];
    for (const child of children) {
      dfs(child, depth + 1);
    }
  }

  for (const root of roots) {
    dfs(root, 0);
  }

  return result;
}

/**
 * Assert that actual spans match the expected chain.
 *
 * Throws an error with a structured diff on mismatch.
 */
export function assertSpanChain(
  actualSpans: SpanData[],
  expectedChain: SpanEntry[],
): void {
  const actualChain = getSpanChain(actualSpans);

  if (actualChain.length !== expectedChain.length) {
    const actualFormatted = formatChain(actualChain);
    const expectedFormatted = formatChain(expectedChain);
    throw new Error(
      `Span chain length mismatch: got ${actualChain.length}, expected ${expectedChain.length}\n` +
        `Actual:\n${actualFormatted}\n` +
        `Expected:\n${expectedFormatted}`,
    );
  }

  for (let i = 0; i < expectedChain.length; i++) {
    const actual = actualChain[i];
    const expected = expectedChain[i];

    if (actual.name !== expected.name || actual.depth !== expected.depth) {
      const actualFormatted = formatChain(actualChain);
      const expectedFormatted = formatChain(expectedChain);
      throw new Error(
        `Span chain mismatch at index ${i}:\n` +
          `  got:      ${formatEntry(actual)}\n` +
          `  expected: ${formatEntry(expected)}\n` +
          `\nActual:\n${actualFormatted}\n` +
          `Expected:\n${expectedFormatted}`,
      );
    }
  }
}

function formatEntry(entry: SpanEntry): string {
  const indent = "  ".repeat(entry.depth);
  return `${indent}${entry.name}`;
}

function formatChain(chain: SpanEntry[]): string {
  return chain.map((e) => `  ${formatEntry(e)}`).join("\n");
}
