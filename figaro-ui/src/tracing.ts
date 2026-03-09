import { trace, propagation, context } from "@opentelemetry/api";
import type { Span } from "@opentelemetry/api";
import {
  WebTracerProvider,
  BatchSpanProcessor,
} from "@opentelemetry/sdk-trace-web";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";

export function initTracing(): void {
  const endpoint = import.meta.env.VITE_OTEL_EXPORTER_OTLP_ENDPOINT;
  if (!endpoint) {
    return;
  }

  const resource = new Resource({
    "service.name": "figaro-ui",
  });

  const exporter = new OTLPTraceExporter({
    url: `${endpoint.replace(/\/+$/, "")}/v1/traces`,
    // Pass headers to force XHR transport instead of sendBeacon.
    // sendBeacon always includes credentials, which triggers CORS errors
    // with cross-origin Jaeger endpoints.
    headers: {},
  });

  const provider = new WebTracerProvider({
    resource,
  });

  provider.addSpanProcessor(new BatchSpanProcessor(exporter));
  provider.register();
}

export function getTracer() {
  return trace.getTracer("figaro");
}

export function createTaskSpan(taskPrompt: string): Span {
  const tracer = getTracer();
  const span = tracer.startSpan("ui.task_submission", {
    attributes: {
      "task.prompt": taskPrompt,
    },
  });
  return span;
}

export function injectTraceContext(): Record<string, string> {
  const carrier: Record<string, string> = {};
  propagation.inject(context.active(), carrier);
  return carrier;
}
