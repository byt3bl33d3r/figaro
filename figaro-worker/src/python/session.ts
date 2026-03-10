import { loadPyodide, type PyodideInterface } from "pyodide";

// Import pyodide.asm.js as code — Bun bundles it, and its side effect
// sets globalThis._createPyodideModule so pyodide skips the dynamic load.
import "pyodide/pyodide.asm.js";

// Embed data files as assets into the compiled binary ($bunfs/)
// @ts-expect-error Bun asset imports not recognized by TypeScript
import wasmPath from "pyodide/pyodide.asm.wasm" with { type: "file" };
// @ts-expect-error Bun asset imports not recognized by TypeScript
import stdlibPath from "pyodide/python_stdlib.zip" with { type: "file" };
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore Bun asset imports not recognized by TypeScript
import lockFilePath from "pyodide/pyodide-lock.json" with { type: "file" };

// Reference all asset imports to prevent tree-shaking
const _embedded = [wasmPath, stdlibPath, lockFilePath];

export class PyodideSession {
  private pyodide: PyodideInterface | null = null;

  async initialize(): Promise<void> {
    this.pyodide = await loadPyodide({
      indexURL: _embedded[0].slice(0, _embedded[0].lastIndexOf("/") + 1),
      stdLibURL: _embedded[1],
      lockFileURL: _embedded[2],
    });
  }

  async execute(
    code: string,
  ): Promise<{ stdout: string; stderr: string; result: string | null }> {
    const stdoutLines: string[] = [];
    const stderrLines: string[] = [];

    this.pyodide!.setStdout({ batched: (line: string) => stdoutLines.push(line) });
    this.pyodide!.setStderr({ batched: (line: string) => stderrLines.push(line) });

    try {
      const rawResult = await this.pyodide!.runPythonAsync(code);

      let result: string | null = null;
      if (rawResult !== undefined && rawResult !== null) {
        result =
          typeof rawResult === "object" && rawResult.toJs
            ? JSON.stringify(rawResult.toJs())
            : String(rawResult);
      }

      return {
        stdout: stdoutLines.join("\n"),
        stderr: stderrLines.join("\n"),
        result,
      };
    } catch (e) {
      return {
        stdout: stdoutLines.join("\n"),
        stderr:
          stderrLines.join("\n") +
          "\n" +
          (e instanceof Error ? e.message : String(e)),
        result: null,
      };
    }
  }

  registerJsModule(name: string, module: Record<string, unknown>): void {
    this.pyodide!.registerJsModule(name, module);
  }

  async destroy(): Promise<void> {
    this.pyodide = null;
  }
}
