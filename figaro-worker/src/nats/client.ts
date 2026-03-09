/**
 * NATS client for publishing events and receiving task assignments.
 *
 * Supports both worker and supervisor modes via the `clientType` constructor option.
 */

import {
  connect,
  type NatsConnection,
  type Subscription,
  type JetStreamClient,
} from "nats";
import os from "node:os";
import { context } from "@opentelemetry/api";

import { Subjects } from "./subjects";
import { ensureStreams } from "./streams";
import { extractTraceContext } from "../tracing/propagation";
import {
  publishTaskMessage as _publishTaskMessage,
  publishTaskComplete as _publishTaskComplete,
  publishTaskError as _publishTaskError,
  publishHelpRequest as _publishHelpRequest,
  sendStatus as _sendStatus,
  sendHeartbeat as _sendHeartbeat,
} from "./publishers";
import { natsRequest, subscribeJetStream, codec, type JsonData } from "./request";

type EventHandler = (data: JsonData) => Promise<void>;

export class NatsClient {
  private natsUrl: string;
  private clientId: string;
  private _clientType: "worker" | "supervisor";
  private capabilities: string[];
  private novncUrl: string | null;
  private nc: NatsConnection | null = null;
  private js: JetStreamClient | null = null;
  private handlers: Map<string, EventHandler[]> = new Map();
  private running = false;
  private subscriptions: Subscription[] = [];
  private stopHandler: ((taskId: string) => boolean) | null = null;
  private _status = "idle";

  constructor(opts: {
    natsUrl: string;
    workerId: string;
    clientType?: "worker" | "supervisor";
    capabilities?: string[];
    novncUrl?: string | null;
  }) {
    this.natsUrl = opts.natsUrl;
    this.clientId = opts.workerId;
    this._clientType = opts.clientType ?? "worker";
    this.capabilities = opts.capabilities ?? [];
    this.novncUrl = opts.novncUrl ?? null;
  }

  // ---- Public accessors ----

  /** The underlying NATS connection, for use by help request handler etc. */
  get conn(): NatsConnection {
    if (!this.nc) {
      throw new Error("NATS connection not established. Call connect() first.");
    }
    return this.nc;
  }

  get id(): string {
    return this.clientId;
  }

  get clientType(): "worker" | "supervisor" {
    return this._clientType;
  }

  get isConnected(): boolean {
    return this.nc !== null && !this.nc.isClosed();
  }

  // ---- Event emitter ----

  /** Register a handler for stop-task messages. */
  onStop(handler: (taskId: string) => boolean): void {
    this.stopHandler = handler;
  }

  /** Register an event handler (e.g. "task"). */
  on(event: string, handler: EventHandler): void {
    const list = this.handlers.get(event) ?? [];
    list.push(handler);
    this.handlers.set(event, list);
  }

  private async emit(event: string, payload: JsonData): Promise<void> {
    const list = this.handlers.get(event) ?? [];
    for (const handler of list) {
      try {
        await handler(payload);
      } catch (err) {
        console.error(`[nats-client] Error in handler for event "${event}":`, err);
      }
    }
  }

  // ---- Derived subjects ----

  private get connectionName(): string {
    return `${this._clientType}-${this.clientId}`;
  }

  private get taskSubject(): string {
    if (this._clientType === "supervisor") {
      return Subjects.supervisorTask(this.clientId);
    }
    return Subjects.workerTask(this.clientId);
  }

  private get registerSubject(): string {
    if (this._clientType === "supervisor") {
      return Subjects.REGISTER_SUPERVISOR;
    }
    return Subjects.REGISTER_WORKER;
  }

  private get stopSubject(): string {
    if (this._clientType === "supervisor") {
      return Subjects.supervisorStop(this.clientId);
    }
    return Subjects.workerStop(this.clientId);
  }

  // ---- Connection lifecycle ----

  /** Connect to NATS, ensure JetStream streams, subscribe, and register. */
  async connect(): Promise<boolean> {
    try {
      this.nc = await connect({
        servers: [this.natsUrl],
        name: this.connectionName,
        maxReconnectAttempts: -1,
        reconnectTimeWait: 2_000,
      });
      this.js = this.nc.jetstream();

      console.log(`[nats-client] Connected to NATS at ${this.natsUrl}`);

      await ensureStreams(this.nc);
      await this.setupSubscriptions();
      // Register in background with retries to handle orchestrator startup race
      this.registerWithRetries();
      return true;
    } catch (err) {
      console.error("[nats-client] Failed to connect to NATS:", err);
      return false;
    }
  }

  private async setupSubscriptions(): Promise<void> {
    // Task assignments via Core NATS
    const sub = this.nc!.subscribe(this.taskSubject);
    this.subscriptions.push(sub);

    // Process incoming messages in the background
    this.processSubscription(sub);

    // Stop task subscription
    const stopSub = this.nc!.subscribe(this.stopSubject);
    this.subscriptions.push(stopSub);
    this.processStopSubscription(stopSub);
  }

  private processStopSubscription(sub: Subscription): void {
    (async () => {
      for await (const msg of sub) {
        try {
          const data = codec.decode(msg.data);
          const taskId = data.task_id as string;
          if (taskId && this.stopHandler) {
            const stopped = this.stopHandler(taskId);
            console.log(`[nats-client] Stop request for task ${taskId}: ${stopped ? "stopped" : "not found"}`);
          }
        } catch (err) {
          console.error("[nats-client] Error processing stop message:", err);
        }
      }
    })();
  }

  /**
   * Iterate over a subscription's messages in the background.
   * Each message is decoded and emitted as a "task" event.
   *
   * For supervisors, the message is acknowledged via request/reply before
   * emitting so the orchestrator can detect dead supervisors.
   */
  private processSubscription(sub: Subscription): void {
    (async () => {
      for await (const msg of sub) {
        try {
          const data = codec.decode(msg.data);
          if (this._clientType === "supervisor") {
            msg.respond(codec.encode({ status: "ok" }));
          }
          const extractedCtx = extractTraceContext(msg.headers ?? undefined);
          await context.with(extractedCtx, () => this.handleTask(data));
        } catch (err) {
          console.error("[nats-client] Error processing task message:", err);
        }
      }
    })();
  }

  private async registerWithRetries(): Promise<void> {
    const registrationData: JsonData = {
      worker_id: this.clientId,
      capabilities: this.capabilities,
      status: "idle",
      metadata: {
        os: os.platform(),
        hostname: os.hostname(),
      },
    };
    if (this._clientType === "worker") {
      registrationData.novnc_url = this.novncUrl;
    }
    const payload = codec.encode(registrationData);
    for (let attempt = 0; attempt < 15; attempt++) {
      try {
        await this.nc!.request(this.registerSubject, payload, {
          timeout: 2_000,
        });
        console.log(`[nats-client] Registered ${this._clientType} ${this.clientId}`);
        return;
      } catch {
        if (attempt === 0) {
          console.debug("[nats-client] Registration not acked yet, retrying...");
        }
        await new Promise((resolve) => setTimeout(resolve, 2_000));
      }
    }
    console.warn(
      `[nats-client] Failed to register ${this._clientType} ${this.clientId} after retries`,
    );
  }

  private async handleTask(data: JsonData): Promise<void> {
    await this.emit("task", data);
  }

  // ---- Publish methods (delegate to standalone functions) ----

  /** Publish a task message (SDK output) via JetStream. */
  async publishTaskMessage(taskId: string, message: JsonData): Promise<void> {
    await _publishTaskMessage(this.js!, this.clientId, this._clientType, taskId, message);
  }

  /** Publish task completion via JetStream. */
  async publishTaskComplete(taskId: string, result: unknown): Promise<void> {
    await _publishTaskComplete(this.js!, this.clientId, this._clientType, taskId, result);
  }

  /** Publish task error via JetStream. */
  async publishTaskError(taskId: string, error: string): Promise<void> {
    await _publishTaskError(this.js!, this.clientId, this._clientType, taskId, error);
  }

  /** Publish a help request via Core NATS. */
  async publishHelpRequest(
    requestId: string,
    taskId: string,
    questions: JsonData[],
    timeoutSeconds: number = 300,
  ): Promise<void> {
    await _publishHelpRequest(this.nc!, this.clientId, this._clientType, requestId, taskId, questions, timeoutSeconds);
  }

  /** Send a NATS request/reply with JSON encode/decode. */
  async request(
    subject: string,
    data: JsonData,
    timeout: number = 10_000,
  ): Promise<JsonData> {
    return natsRequest(this.nc!, subject, data, timeout);
  }

  /** Subscribe to a JetStream subject with an ephemeral push consumer for new messages. */
  async subscribeJetStream(
    subject: string,
    handler: (data: JsonData) => void,
  ): Promise<{ unsubscribe: () => void }> {
    return subscribeJetStream(this.js!, subject, handler);
  }

  /** Publish status update via heartbeat. */
  async sendStatus(status: string): Promise<void> {
    this._status = status;
    await _sendStatus(this.nc!, this.clientId, this._clientType, status);
  }

  /** Publish heartbeat. */
  async sendHeartbeat(): Promise<void> {
    await _sendHeartbeat(this.nc!, this.clientId, this._clientType, this.capabilities, this._status, this.novncUrl);
  }

  // ---- Run loop ----

  /** Unsubscribe and clear all active subscriptions. */
  private drainSubscriptions(): void {
    for (const sub of this.subscriptions) {
      try {
        sub.unsubscribe();
      } catch {
        // ignore — subscription may already be closed
      }
    }
    this.subscriptions = [];
  }

  /** Main run loop -- keeps alive while connected, reconnects if needed. */
  async run(): Promise<void> {
    this.running = true;
    while (this.running) {
      if (!this.isConnected) {
        console.warn("[nats-client] NATS disconnected, attempting reconnect...");
        try {
          // Clean up stale subscriptions from the old connection
          this.drainSubscriptions();
          this.nc = await connect({
            servers: [this.natsUrl],
            name: this.connectionName,
            maxReconnectAttempts: -1,
            reconnectTimeWait: 2_000,
          });
          this.js = this.nc.jetstream();
          await ensureStreams(this.nc);
          await this.setupSubscriptions();
          this.registerWithRetries();
        } catch (err) {
          console.error("[nats-client] Reconnect failed:", err);
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
  }

  /** Signal to stop the run loop. */
  stop(): void {
    this.running = false;
  }

  /** Gracefully deregister and drain the NATS connection. */
  async close(): Promise<void> {
    this.stop();
    if (this.nc && !this.nc.isClosed()) {
      // Publish deregistration before draining
      this.nc.publish(
        Subjects.deregister(this._clientType, this.clientId),
        codec.encode({
          client_id: this.clientId,
        }),
      );
      // Flush pending publishes then drain all subscriptions and close
      await this.nc.drain();
      console.log("[nats-client] NATS connection drained and closed");
    }
  }
}
