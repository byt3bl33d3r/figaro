import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import { PyodideSession } from "../src/python/session";

describe("PyodideSession", () => {
  let session: PyodideSession;

  beforeAll(async () => {
    session = new PyodideSession();
    await session.initialize();
  });

  afterAll(async () => {
    await session.destroy();
  });

  test("evaluates expressions and returns result", async () => {
    const result = await session.execute("2 + 2");
    expect(result.result).toBe("4");
    expect(result.stderr).toBe("");
  });

  test("returns null result for statements", async () => {
    const result = await session.execute("x = 42");
    expect(result.result).toBeNull();
  });

  test("variables persist across calls", async () => {
    await session.execute("counter = 10");
    const result = await session.execute("counter + 5");
    expect(result.result).toBe("15");
  });

  test("captures stdout from print", async () => {
    const result = await session.execute("print('hello world')");
    expect(result.stdout).toContain("hello world");
  });

  test("captures multi-line stdout", async () => {
    const result = await session.execute("print('line1')\nprint('line2')");
    expect(result.stdout).toContain("line1");
    expect(result.stdout).toContain("line2");
  });

  test("captures stderr from errors and returns null result", async () => {
    const result = await session.execute("undefined_var");
    expect(result.stderr).toContain("NameError");
    expect(result.result).toBeNull();
  });

  test("captures stderr from syntax errors", async () => {
    const result = await session.execute("def f(");
    expect(result.stderr).toContain("SyntaxError");
    expect(result.result).toBeNull();
  });

  test("stdlib imports work", async () => {
    const result = await session.execute(
      "import json\njson.dumps({'a': 1})",
    );
    expect(result.result).toBe('{"a": 1}');
  });

  test("math operations work", async () => {
    const result = await session.execute(
      "import math\nmath.factorial(10)",
    );
    expect(result.result).toBe("3628800");
  });

  test("collections work", async () => {
    const result = await session.execute(
      "from collections import Counter\nstr(Counter('abracadabra').most_common(3))",
    );
    expect(result.result!).toContain("a");
  });

  test("list comprehensions work", async () => {
    const result = await session.execute(
      "[x**2 for x in range(5)]",
    );
    expect(result.result).toContain("0");
    expect(result.result).toContain("16");
  });

  test("functions persist across calls", async () => {
    await session.execute("def fib(n):\n  if n <= 1: return n\n  return fib(n-1) + fib(n-2)");
    const result = await session.execute("fib(10)");
    expect(result.result).toBe("55");
  });

  test("destroy makes subsequent execute throw", async () => {
    const tempSession = new PyodideSession();
    await tempSession.initialize();
    const result = await tempSession.execute("1 + 1");
    expect(result.result).toBe("2");

    await tempSession.destroy();
    await expect(tempSession.execute("1")).rejects.toThrow();
  });
});
