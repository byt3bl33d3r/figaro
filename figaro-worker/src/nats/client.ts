/**
 * Worker NATS client for publishing events and receiving task assignments.
 *
 * Ported from figaro-worker/src/figaro_worker/worker/client.py
 */

import {
  connect,
  type NatsConnection,
  type Subscription,
  type JetStreamClient,
  JSONCodec,
} from "nats";
import os from "node:os";

import { Subjects } from "./subjects";
import { ensureStreams } from "./streams";

// biome-ignore lint: JSON payloads are loosely typed
type JsonData = Record<string, any>;
type EventHandler = (data: JsonData) => Promise<void>;

const codec = JSONCodec<JsonData>();

export class NatsClient {
  private natsUrl: string;
  private workerId: string;
  private capabilities: string[];
  private novncUrl: string | null;
  private nc: NatsConnection | null = null;
  private js: JetStreamClient | null = null;
  private handlers: Map<string, EventHandler[]> = new Map();
  private running = false;
  private subscriptions: Subscription[] = [];

  constructor(opts: {
    natsUrl: string;
    workerId: string;
    capabilities?: string[];
    novncUrl?: string | null;
  }) {
    this.natsUrl = opts.natsUrl;
    this.workerId = opts.workerId;
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
    return this.workerId;
  }

  get isConnected(): boolean {
    return this.nc !== null && !this.nc.isClosed();
  }

  // ---- Event emitter ----

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

  // ---- Connection lifecycle ----

  /** Connect to NATS, ensure JetStream streams, subscribe, and register. */
  async connect(): Promise<boolean> {
    try {
      this.nc = await connect({
        servers: [this.natsUrl],
        name: `worker-${this.workerId}`,
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
    const sub = this.nc!.subscribe(Subjects.workerTask(this.workerId));
    this.subscriptions.push(sub);

    // Process incoming messages in the background
    this.processSubscription(sub);
  }

  /**
   * Iterate over a subscription's messages in the background.
   * Each message is decoded and emitted as a "task" event.
   */
  private processSubscription(sub: Subscription): void {
    (async () => {
      for await (const msg of sub) {
        try {
          const data = codec.decode(msg.data);
          await this.handleTask(data);
        } catch (err) {
          console.error("[nats-client] Error processing task message:", err);
        }
      }
    })();
  }

  private async registerWithRetries(): Promise<void> {
    const payload = codec.encode({
      worker_id: this.workerId,
      capabilities: this.capabilities,
      novnc_url: this.novncUrl,
      status: "idle",
      metadata: {
        os: os.platform(),
        hostname: os.hostname(),
      },
    });
    for (let attempt = 0; attempt < 15; attempt++) {
      try {
        await this.nc!.request(Subjects.REGISTER_WORKER, payload, {
          timeout: 2_000,
        });
        console.log(`[nats-client] Registered worker ${this.workerId}`);
        return;
      } catch {
        if (attempt === 0) {
          console.debug("[nats-client] Registration not acked yet, retrying...");
        }
        await new Promise((resolve) => setTimeout(resolve, 2_000));
      }
    }
    console.warn(
      `[nats-client] Failed to register worker ${this.workerId} after retries`,
    );
  }

  private async handleTask(data: JsonData): Promise<void> {
    await this.emit("task", data);
  }

  // ---- Publish methods for task events (JetStream) ----

  /** Publish a task message (SDK output) via JetStream. */
  async publishTaskMessage(taskId: string, message: JsonData): Promise<void> {
    await this.js!.publish(
      Subjects.taskMessage(taskId),
      codec.encode({
        task_id: taskId,
        worker_id: this.workerId,
        ...message,
      }),
    );
  }

  /** Publish task completion via JetStream. */
  async publishTaskComplete(taskId: string, result: unknown): Promise<void> {
    await this.js!.publish(
      Subjects.taskComplete(taskId),
      codec.encode({
        task_id: taskId,
        worker_id: this.workerId,
        result,
      }),
    );
  }

  /** Publish task error via JetStream. */
  async publishTaskError(taskId: string, error: string): Promise<void> {
    await this.js!.publish(
      Subjects.taskError(taskId),
      codec.encode({
        task_id: taskId,
        worker_id: this.workerId,
        error,
      }),
    );
  }

  // ---- Publish methods for Core NATS ----

  /** Publish a help request via Core NATS. */
  async publishHelpRequest(
    requestId: string,
    taskId: string,
    questions: JsonData[],
    timeoutSeconds: number = 300,
  ): Promise<void> {
    this.nc!.publish(
      Subjects.HELP_REQUEST,
      codec.encode({
        request_id: requestId,
        worker_id: this.workerId,
        task_id: taskId,
        questions,
        timeout_seconds: timeoutSeconds,
      }),
    );
  }

  /** Publish worker status update via heartbeat. */
  async sendStatus(status: string): Promise<void> {
    this.nc!.publish(
      Subjects.heartbeat("worker", this.workerId),
      codec.encode({
        client_id: this.workerId,
        status,
      }),
    );
  }

  /** Publish heartbeat. */
  async sendHeartbeat(): Promise<void> {
    this.nc!.publish(
      Subjects.heartbeat("worker", this.workerId),
      codec.encode({
        client_id: this.workerId,
        client_type: "worker",
        novnc_url: this.novncUrl,
        capabilities: this.capabilities,
      }),
    );
  }

  // ---- Run loop ----

  /** Main run loop -- keeps alive while connected, reconnects if needed. */
  async run(): Promise<void> {
    this.running = true;
    while (this.running) {
      if (!this.isConnected) {
        console.warn("[nats-client] NATS disconnected, attempting reconnect...");
        try {
          this.nc = await connect({
            servers: [this.natsUrl],
            name: `worker-${this.workerId}`,
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
        Subjects.deregister("worker", this.workerId),
        codec.encode({
          client_id: this.workerId,
        }),
      );
      // Flush pending publishes then drain all subscriptions and close
      await this.nc.drain();
      console.log("[nats-client] NATS connection drained and closed");
    }
  }
}
