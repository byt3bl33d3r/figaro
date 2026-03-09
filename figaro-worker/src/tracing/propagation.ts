/**
 * W3C Trace Context propagation over NATS message headers.
 *
 * Injects/extracts traceparent and tracestate headers into NATS MsgHdrs
 * using the OpenTelemetry propagation API with custom text map carriers.
 */

import {
  context,
  propagation,
  type TextMapGetter,
  type TextMapSetter,
  type Context,
} from "@opentelemetry/api";
import { headers as createHeaders, type MsgHdrs } from "nats";

const natsSetter: TextMapSetter<MsgHdrs> = {
  set(carrier: MsgHdrs, key: string, value: string): void {
    carrier.set(key, value);
  },
};

const natsGetter: TextMapGetter<MsgHdrs> = {
  get(carrier: MsgHdrs, key: string): string | undefined {
    try {
      const value = carrier.get(key);
      return value || undefined;
    } catch {
      return undefined;
    }
  },
  keys(carrier: MsgHdrs): string[] {
    return carrier.keys();
  },
};

/**
 * Create NATS MsgHdrs with W3C traceparent injected from the current span context.
 *
 * Returns a new MsgHdrs instance (or the provided one) with trace context headers set.
 */
export function injectTraceContext(hdrs?: MsgHdrs): MsgHdrs {
  const msgHeaders = hdrs ?? createHeaders();
  propagation.inject(context.active(), msgHeaders, natsSetter);
  return msgHeaders;
}

/**
 * Extract W3C trace context from NATS message headers.
 *
 * Returns a Context that can be used with context.with() to set as active.
 */
export function extractTraceContext(hdrs?: MsgHdrs): Context {
  if (!hdrs) {
    return context.active();
  }
  return propagation.extract(context.active(), hdrs, natsGetter);
}
