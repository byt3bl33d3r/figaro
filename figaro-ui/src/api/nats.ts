import { connect, JSONCodec, headers as createHeaders } from "nats.ws";
import type {
  NatsConnection,
  Subscription,
} from "nats.ws";
import { context, trace as traceApi, propagation } from "@opentelemetry/api";
import type { Span } from "@opentelemetry/api";
import { createTaskSpan, getTracer } from "../tracing";
import { useConnectionStore } from "../stores/connection";
import { useMessagesStore } from "../stores/messages";
import { useTasksStore } from "../stores/tasks";
import { fetchInitialState } from "./nats-initial-state";
import { setupCoreSubscriptions, setupJetStreamSubscription } from "./nats-subscriptions";

export const jc = JSONCodec();

const INITIAL_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;

class NatsManager {
  private nc: NatsConnection | null = null;
  private subscriptions: Subscription[] = [];
  private jsCleanup: (() => void)[] = [];
  private url: string;
  private shouldReconnect = false;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = INITIAL_RECONNECT_DELAY;

  constructor() {
    this.url =
      import.meta.env.VITE_NATS_WS_URL || "ws://localhost:8443";
  }

  async connect(): Promise<void> {
    if (this.nc && !this.nc.isClosed()) {
      return;
    }

    this.shouldReconnect = true;
    useConnectionStore.getState().setStatus("connecting");

    try {
      // Try to get NATS URL from orchestrator config endpoint
      try {
        const resp = await fetch("/api/config");
        if (resp.ok) {
          const config = await resp.json();
          if (config.nats_ws_url) {
            this.url = config.nats_ws_url;
          }
        }
      } catch {
        // Use default URL
      }

      this.nc = await connect({ servers: this.url });
      console.log("Connected to NATS at", this.url);

      useConnectionStore.getState().setStatus("connected");
      useConnectionStore.getState().resetReconnectAttempt();
      this.reconnectDelay = INITIAL_RECONNECT_DELAY;

      // Clear stale events before re-subscribing (JetStream will replay)
      useMessagesStore.getState().clearEvents();
      useTasksStore.getState().clearTasks();

      setupCoreSubscriptions(this.nc, this.subscriptions);
      await setupJetStreamSubscription(this.nc, this.jsCleanup);

      // Fetch initial state (broadcasts are ephemeral, so we need to request current state)
      await fetchInitialState((subject, data) => this.request(subject, data));

      // Monitor for close
      this.nc.closed().then(() => {
        console.log("NATS connection closed");
        this.nc = null;
        useConnectionStore.getState().setStatus("disconnected");
        this.scheduleReconnect();
      });
    } catch (error) {
      console.error("Failed to connect to NATS:", error);
      useConnectionStore.getState().setError(String(error));
      this.scheduleReconnect();
    }
  }

  async disconnect(): Promise<void> {
    this.shouldReconnect = false;
    this.clearReconnectTimeout();

    for (const cleanup of this.jsCleanup) {
      cleanup();
    }
    this.jsCleanup = [];

    for (const sub of this.subscriptions) {
      sub.unsubscribe();
    }
    this.subscriptions = [];

    if (this.nc) {
      await this.nc.drain();
      this.nc = null;
    }

    useConnectionStore.getState().setStatus("disconnected");
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect) return;

    this.clearReconnectTimeout();
    useConnectionStore.getState().incrementReconnectAttempt();

    console.log(`Scheduling NATS reconnect in ${this.reconnectDelay}ms`);
    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);

    // Exponential backoff
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 2,
      MAX_RECONNECT_DELAY
    );
  }

  private clearReconnectTimeout(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
  }

  async request<T = unknown>(subject: string, data?: unknown): Promise<T> {
    if (!this.nc || this.nc.isClosed()) {
      throw new Error("Not connected to NATS");
    }

    const isTaskCreate = subject === "figaro.api.tasks.create";
    const span: Span =
      isTaskCreate && data && typeof data === "object" && "prompt" in data
        ? createTaskSpan((data as { prompt: string }).prompt)
        : getTracer().startSpan(`ui.nats_request`, {
            attributes: { "nats.subject": subject },
          });

    try {
      const payload = data ? jc.encode(data) : undefined;

      const traceHeaders = this.injectTraceHeaders(span);

      const response = await this.nc.request(subject, payload, {
        timeout: 30000,
        headers: traceHeaders,
      });

      span.setStatus({ code: 1 }); // SpanStatusCode.OK
      return jc.decode(response.data) as T;
    } catch (error) {
      span.setStatus({
        code: 2, // SpanStatusCode.ERROR
        message: error instanceof Error ? error.message : String(error),
      });
      span.recordException(
        error instanceof Error ? error : new Error(String(error))
      );
      throw error;
    } finally {
      span.end();
    }
  }

  private injectTraceHeaders(span: Span) {
    const spanContext = traceApi.setSpan(context.active(), span);
    const carrier: Record<string, string> = {};
    propagation.inject(spanContext, carrier);
    return this.carrierToHeaders(carrier);
  }

  private carrierToHeaders(carrier: Record<string, string>) {
    const keys = Object.keys(carrier);
    if (keys.length === 0) {
      return undefined;
    }
    const hdrs = createHeaders();
    for (const key of keys) {
      hdrs.set(key, carrier[key]);
    }
    return hdrs;
  }

  get isConnected(): boolean {
    return this.nc !== null && !this.nc.isClosed();
  }
}

// Singleton instance
export const natsManager = new NatsManager();
