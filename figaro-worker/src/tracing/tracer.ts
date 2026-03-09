/**
 * OpenTelemetry tracing setup for the figaro-worker.
 *
 * Uses sdk-trace-base (not sdk-trace-node) for Bun compatibility.
 * Uses a lightweight fetch-based OTLP exporter to avoid CJS class
 * inheritance issues with @opentelemetry/exporter-trace-otlp-http in Bun's bundler.
 * Tracing is a no-op when OTEL_EXPORTER_OTLP_ENDPOINT is not set.
 */

import {
  trace,
  context,
  SpanStatusCode,
  type Tracer,
  type Span,
} from "@opentelemetry/api";
import {
  BasicTracerProvider,
  BatchSpanProcessor,
  type SpanExporter,
  type ReadableSpan,
} from "@opentelemetry/sdk-trace-base";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";

let initialized = false;

/**
 * Lightweight OTLP/HTTP JSON trace exporter using fetch().
 *
 * Avoids the CJS class constructor issue that @opentelemetry/exporter-trace-otlp-http
 * has when bundled with Bun's single-file compiler.
 */
class FetchOTLPExporter implements SpanExporter {
  private url: string;

  constructor(endpoint: string) {
    this.url = `${endpoint}/v1/traces`;
  }

  export(
    spans: ReadableSpan[],
    resultCallback: (result: { code: number }) => void,
  ): void {
    const body = JSON.stringify(this.toOtlpJson(spans));
    fetch(this.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })
      .then((res) => {
        resultCallback({ code: res.ok ? 0 : 1 });
      })
      .catch(() => {
        resultCallback({ code: 1 });
      });
  }

  async shutdown(): Promise<void> {}

  async forceFlush(): Promise<void> {}

  private toOtlpJson(spans: ReadableSpan[]): object {
    const resourceSpans = new Map<string, ReadableSpan[]>();

    for (const span of spans) {
      const key = JSON.stringify(span.resource.attributes);
      const group = resourceSpans.get(key) ?? [];
      group.push(span);
      resourceSpans.set(key, group);
    }

    return {
      resourceSpans: Array.from(resourceSpans.entries()).map(([, group]) => ({
        resource: {
          attributes: Object.entries(group[0].resource.attributes).map(
            ([k, v]) => ({
              key: k,
              value: { stringValue: String(v) },
            }),
          ),
        },
        scopeSpans: [
          {
            scope: {
              name: group[0].instrumentationLibrary.name,
              version: group[0].instrumentationLibrary.version ?? "",
            },
            spans: group.map((s) => this.spanToOtlp(s)),
          },
        ],
      })),
    };
  }

  private spanToOtlp(span: ReadableSpan): object {
    const ctx = span.spanContext();
    return {
      traceId: ctx.traceId,
      spanId: ctx.spanId,
      parentSpanId: span.parentSpanId || undefined,
      name: span.name,
      kind: span.kind,
      startTimeUnixNano: this.hrTimeToNanos(span.startTime),
      endTimeUnixNano: this.hrTimeToNanos(span.endTime),
      attributes: Object.entries(span.attributes).map(([k, v]) => ({
        key: k,
        value: { stringValue: String(v) },
      })),
      status: span.status,
    };
  }

  private hrTimeToNanos(hrTime: [number, number]): string {
    return String(hrTime[0] * 1_000_000_000 + hrTime[1]);
  }
}

/**
 * Initialize OpenTelemetry tracing.
 *
 * No-op when OTEL_EXPORTER_OTLP_ENDPOINT env var is not set
 * (unless a testExporter is provided for testing).
 */
export function initTracing(
  serviceName: string,
  testExporter?: SpanExporter,
): void {
  if (initialized) {
    return;
  }

  const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

  if (!endpoint && !testExporter) {
    return;
  }

  const resource = new Resource({
    [ATTR_SERVICE_NAME]: serviceName,
  });

  const provider = new BasicTracerProvider({ resource });

  const exporter = testExporter ?? new FetchOTLPExporter(endpoint!);
  provider.addSpanProcessor(new BatchSpanProcessor(exporter));

  const contextManager = new AsyncLocalStorageContextManager();
  provider.register({ contextManager });
  initialized = true;
}

/** Returns the figaro tracer instance. */
export function getTracer(): Tracer {
  return trace.getTracer("figaro");
}

/**
 * Execute an async function within a named span.
 *
 * Creates a span, runs fn within it, records errors, and ends the span.
 */
export async function traced<T>(
  name: string,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  const tracer = getTracer();
  return tracer.startActiveSpan(name, async (span: Span) => {
    try {
      const result = await fn(span);
      span.setStatus({ code: SpanStatusCode.OK });
      return result;
    } catch (err) {
      span.setStatus({
        code: SpanStatusCode.ERROR,
        message: err instanceof Error ? err.message : String(err),
      });
      span.recordException(
        err instanceof Error ? err : new Error(String(err)),
      );
      throw err;
    } finally {
      span.end();
    }
  });
}
