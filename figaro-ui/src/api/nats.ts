import { connect, JSONCodec } from "nats.ws";
import type {
  NatsConnection,
  Subscription,
  JetStreamClient,
  Msg,
} from "nats.ws";
import type {
  Worker,
  WorkersPayload,
  SupervisorsPayload,
  TaskAssignedPayload,
  TaskCompletePayload,
  ErrorPayload,
  StatusPayload,
  SDKMessage,
  ScheduledTask,
  ScheduledTaskExecutedPayload,
  ScheduledTaskSkippedPayload,
  HelpRequestCreatedPayload,
  HelpRequestRespondedPayload,
  HelpRequestTimeoutPayload,
  TaskHealingPayload,
} from "../types";
import { useConnectionStore } from "../stores/connection";
import { useWorkersStore } from "../stores/workers";
import { useSupervisorsStore } from "../stores/supervisors";
import { useMessagesStore } from "../stores/messages";
import { useScheduledTasksStore } from "../stores/scheduledTasks";
import { useHelpRequestsStore } from "../stores/helpRequests";

const jc = JSONCodec();

const INITIAL_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;

class NatsManager {
  private nc: NatsConnection | null = null;
  private js: JetStreamClient | null = null;
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

      this.setupCoreSubscriptions();
      await this.setupJetStreamSubscription();

      // Fetch initial state (broadcasts are ephemeral, so we need to request current state)
      await this.fetchInitialState();

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

  private async fetchInitialState(): Promise<void> {
    try {
      const [workersResp, supervisorsResp, helpRequestsResp, scheduledTasksResp] =
        await Promise.all([
          this.request<WorkersPayload>("figaro.api.workers", {}),
          this.request<SupervisorsPayload>(
            "figaro.api.supervisor.status",
            {}
          ),
          this.request<{ requests: HelpRequestCreatedPayload[] }>(
            "figaro.api.help-requests.list",
            {}
          ).catch(() => null),
          this.request<{ tasks: ScheduledTask[] }>(
            "figaro.api.scheduled-tasks",
            {}
          ).catch(() => null),
        ]);

      if (workersResp?.workers) {
        useWorkersStore.getState().setWorkers(workersResp.workers);
      }
      if (supervisorsResp?.supervisors) {
        useSupervisorsStore
          .getState()
          .setSupervisors(supervisorsResp.supervisors);
      }
      if (helpRequestsResp?.requests) {
        for (const req of helpRequestsResp.requests) {
          useHelpRequestsStore.getState().addRequest({
            request_id: req.request_id,
            worker_id: req.worker_id,
            task_id: req.task_id,
            questions: req.questions,
            context: req.context,
            created_at: req.created_at,
            timeout_seconds: req.timeout_seconds,
            status: req.status || "pending",
          });
        }
      }
      if (scheduledTasksResp?.tasks) {
        useScheduledTasksStore.getState().setTasks(scheduledTasksResp.tasks);
      }
    } catch (err) {
      console.warn("Failed to fetch initial state:", err);
    }
  }

  private setupCoreSubscriptions(): void {
    if (!this.nc) return;

    // Workers broadcast
    const workersSub = this.nc.subscribe("figaro.broadcast.workers");
    this.subscriptions.push(workersSub);
    this.consumeSubscription(workersSub, (data) => {
      const payload = data as unknown as WorkersPayload;
      useWorkersStore.getState().setWorkers(payload.workers);
    });

    // Supervisors broadcast
    const supervisorsSub = this.nc.subscribe(
      "figaro.broadcast.supervisors"
    );
    this.subscriptions.push(supervisorsSub);
    this.consumeSubscription(supervisorsSub, (data) => {
      const payload = data as unknown as SupervisorsPayload;
      useSupervisorsStore.getState().setSupervisors(payload.supervisors);
    });

    // Broadcast catch-all for other events
    const broadcastSub = this.nc.subscribe("figaro.broadcast.>");
    this.subscriptions.push(broadcastSub);
    this.consumeSubscription(broadcastSub, (data, msg) => {
      const subject = msg.subject;
      // Skip subjects that have dedicated handlers above
      if (
        subject === "figaro.broadcast.workers" ||
        subject === "figaro.broadcast.supervisors" ||
        subject === "figaro.broadcast.help_request"
      ) {
        return;
      }

      // Parse event type from subject: figaro.broadcast.{event_type}
      const parts = subject.split(".");
      const eventType = parts.slice(2).join(".");
      this.handleBroadcastEvent(eventType, data);
    });

    // Dedicated help request broadcast subscription
    // (more reliable than relying solely on the wildcard catch-all)
    const helpBroadcastSub = this.nc.subscribe(
      "figaro.broadcast.help_request"
    );
    this.subscriptions.push(helpBroadcastSub);
    this.consumeSubscription(helpBroadcastSub, (data) => {
      const payload = data as unknown as HelpRequestCreatedPayload;
      console.log("Help request broadcast received:", payload.request_id);
      useHelpRequestsStore.getState().addRequest({
        request_id: payload.request_id,
        worker_id: payload.worker_id,
        task_id: payload.task_id,
        questions: payload.questions,
        context: payload.context,
        created_at: payload.created_at,
        timeout_seconds: payload.timeout_seconds,
        status: "pending",
      });
      const questionText = payload.questions?.[0]?.question
        ? `: ${payload.questions[0].question}`
        : "";
      useMessagesStore.getState().addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `${payload.worker_id} needs help${questionText}`,
        },
      });
    });

    // Help response events (wildcard for request_id)
    const helpResponseSub = this.nc.subscribe("figaro.help.*.response");
    this.subscriptions.push(helpResponseSub);
    this.consumeSubscription(helpResponseSub, (data) => {
      const payload = data as unknown as HelpRequestRespondedPayload;
      useHelpRequestsStore
        .getState()
        .updateRequestStatus(
          payload.request_id,
          "responded",
          payload.source
        );
      useMessagesStore.getState().addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `Help request answered via ${payload.source}`,
        },
      });
    });
  }

  private async setupJetStreamSubscription(): Promise<void> {
    if (!this.nc) return;

    try {
      this.js = this.nc.jetstream();

      // Use an ordered consumer for ephemeral read-only access to task events
      const consumer = await this.js.consumers.get("TASKS", {
        filterSubjects: ["figaro.task.>"],
      });

      const messages = await consumer.consume();

      // Process messages asynchronously
      let stopped = false;
      const processMessages = async () => {
        try {
          for await (const msg of messages) {
            if (stopped) break;
            try {
              const data = msg.json();
              const subject = msg.subject;
              // Parse event type from subject: figaro.task.{id}.{event}
              const parts = subject.split(".");
              const eventType = parts[parts.length - 1];
              this.handleTaskEvent(eventType, data);
            } catch (err) {
              console.error("Error processing JetStream task event:", err);
            }
          }
        } catch (err) {
          if (!stopped) {
            console.error("JetStream consumer error:", err);
          }
        }
      };

      processMessages();

      this.jsCleanup.push(() => {
        stopped = true;
        messages.close();
      });
    } catch (err) {
      console.warn(
        "JetStream TASKS consumer not available (stream may not exist yet):",
        err
      );
    }
  }

  private consumeSubscription(
    sub: Subscription,
    handler: (data: unknown, msg: Msg) => void
  ): void {
    (async () => {
      for await (const msg of sub) {
        try {
          const data = jc.decode(msg.data);
          handler(data, msg);
        } catch (err) {
          console.error(
            `Error processing message on ${msg.subject}:`,
            err
          );
        }
      }
    })();
  }

  private handleBroadcastEvent(
    eventType: string,
    data: unknown
  ): void {
    const messagesStore = useMessagesStore.getState();
    const workersStore = useWorkersStore.getState();
    const supervisorsStore = useSupervisorsStore.getState();

    switch (eventType) {
      case "worker_connected": {
        const worker = data as unknown as Worker;
        workersStore.updateWorker(worker);
        messagesStore.addEvent({
          worker_id: worker.id,
          type: "system",
          data: { message: `Worker ${worker.id} connected` },
        });
        break;
      }

      case "worker_disconnected": {
        const payload = data as { worker_id: string };
        workersStore.removeWorker(payload.worker_id);
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "system",
          data: {
            message: `Worker ${payload.worker_id} disconnected`,
          },
        });
        break;
      }

      case "status": {
        const payload = data as unknown as StatusPayload;
        workersStore.updateWorkerStatus(
          payload.worker_id,
          payload.status
        );
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "status",
          data: payload,
        });
        break;
      }

      case "error": {
        const payload = data as unknown as ErrorPayload;
        messagesStore.addEvent({
          type: "error",
          data: payload,
        });
        break;
      }

      // Scheduled task broadcasts
      case "scheduled_task_created":
      case "scheduled_task_updated": {
        const task = data as unknown as ScheduledTask;
        useScheduledTasksStore.getState().updateTask(task);
        messagesStore.addEvent({
          type: "system",
          data: {
            message: `Scheduled task "${task.name}" ${eventType === "scheduled_task_created" ? "created" : "updated"}`,
          },
        });
        break;
      }

      case "scheduled_task_deleted": {
        const payload = data as { schedule_id: string };
        useScheduledTasksStore
          .getState()
          .removeTask(payload.schedule_id);
        messagesStore.addEvent({
          type: "system",
          data: { message: "Scheduled task deleted" },
        });
        break;
      }

      case "scheduled_task_executed": {
        const payload =
          data as unknown as ScheduledTaskExecutedPayload;
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "system",
          data: {
            message: `Scheduled task executed (task: ${payload.task_id.slice(0, 8)}...)`,
          },
        });
        break;
      }

      case "scheduled_task_skipped": {
        const payload =
          data as unknown as ScheduledTaskSkippedPayload;
        messagesStore.addEvent({
          type: "system",
          data: {
            message: `Scheduled task skipped: ${payload.reason}`,
          },
        });
        break;
      }

      case "task_healing": {
        const payload = data as unknown as TaskHealingPayload;
        messagesStore.addEvent({
          type: "task_healing",
          data: payload,
        });
        break;
      }

      // Help request broadcasts
      case "help_request_responded": {
        const payload =
          data as unknown as HelpRequestRespondedPayload;
        useHelpRequestsStore
          .getState()
          .updateRequestStatus(
            payload.request_id,
            "responded",
            payload.source
          );
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "help_response",
          data: payload,
        });
        break;
      }

      case "help_request_timeout": {
        const payload =
          data as unknown as HelpRequestTimeoutPayload;
        useHelpRequestsStore
          .getState()
          .updateRequestStatus(payload.request_id, "timeout");
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "system",
          data: { message: "Help request timed out" },
        });
        break;
      }

      case "help_request_dismissed": {
        const payload =
          data as unknown as HelpRequestRespondedPayload;
        useHelpRequestsStore
          .getState()
          .updateRequestStatus(
            payload.request_id,
            "cancelled",
            payload.source
          );
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "system",
          data: {
            message: `Help request dismissed via ${payload.source}`,
          },
        });
        break;
      }

      // Task assignment is handled via JetStream (handleTaskEvent "assigned")
      // so we skip the broadcast duplicate here

      // Help request broadcast
      case "help_request": {
        const payload = data as unknown as HelpRequestCreatedPayload;
        useHelpRequestsStore.getState().addRequest({
          request_id: payload.request_id,
          worker_id: payload.worker_id,
          task_id: payload.task_id,
          questions: payload.questions,
          context: payload.context,
          created_at: payload.created_at,
          timeout_seconds: payload.timeout_seconds,
          status: "pending",
        });
        const helpQuestionText = payload.questions?.[0]?.question
          ? `: ${payload.questions[0].question}`
          : "";
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "system",
          data: {
            message: `Worker ${payload.worker_id} needs help${helpQuestionText}`,
          },
        });
        break;
      }

      // Supervisor broadcasts
      case "supervisor_error": {
        const payload = data as unknown as ErrorPayload & {
          supervisor_id: string;
        };
        messagesStore.addEvent({
          supervisor_id: payload.supervisor_id,
          type: "supervisor_error",
          data: payload,
        });
        break;
      }

      case "supervisor_task_complete": {
        const payload = data as unknown as TaskCompletePayload & {
          supervisor_id: string;
        };
        supervisorsStore.updateSupervisorStatus(
          payload.supervisor_id,
          "idle"
        );
        messagesStore.addEvent({
          supervisor_id: payload.supervisor_id,
          type: "supervisor_task_complete",
          data: payload,
        });
        break;
      }

      // These are handled via JetStream (handleTaskEvent), skip broadcast duplicates
      case "task_assigned":
      case "task_error":
      case "task_submitted_to_supervisor":
        break;

      default:
        console.log("Unknown broadcast event:", eventType, data);
    }
  }

  private handleTaskEvent(
    eventType: string,
    data: unknown
  ): void {
    const messagesStore = useMessagesStore.getState();
    const workersStore = useWorkersStore.getState();
    const supervisorsStore = useSupervisorsStore.getState();

    switch (eventType) {
      case "assigned": {
        const payload = data as unknown as TaskAssignedPayload & {
          supervisor_id?: string;
        };
        if (payload.supervisor_id) {
          supervisorsStore.updateSupervisorStatus(
            payload.supervisor_id,
            "busy"
          );
          messagesStore.addEvent({
            supervisor_id: payload.supervisor_id,
            type: "task_submitted_to_supervisor",
            data: payload,
          });
        } else if (payload.worker_id) {
          workersStore.updateWorkerStatus(payload.worker_id, "busy");
          messagesStore.addEvent({
            worker_id: payload.worker_id,
            type: "task_assigned",
            data: payload,
          });
        }
        break;
      }

      case "message": {
        const sdkMessage = data as unknown as SDKMessage;
        if (sdkMessage.supervisor_id) {
          messagesStore.addEvent({
            supervisor_id: sdkMessage.supervisor_id,
            type: "supervisor_message",
            data: sdkMessage,
          });
        } else {
          messagesStore.addSDKMessage(sdkMessage);
        }
        break;
      }

      case "complete": {
        const payload = data as unknown as TaskCompletePayload & {
          supervisor_id?: string;
        };
        if (payload.supervisor_id) {
          supervisorsStore.updateSupervisorStatus(
            payload.supervisor_id,
            "idle"
          );
          messagesStore.addEvent({
            supervisor_id: payload.supervisor_id,
            type: "supervisor_task_complete",
            data: payload,
          });
        } else if (payload.worker_id) {
          workersStore.updateWorkerStatus(
            payload.worker_id,
            "idle"
          );
          messagesStore.addEvent({
            worker_id: payload.worker_id,
            type: "task_complete",
            data: payload,
          });
        }
        break;
      }

      case "error": {
        const payload = data as unknown as ErrorPayload;
        messagesStore.addEvent({
          type: "error",
          data: payload,
        });
        break;
      }

      default:
        console.log("Unknown task event:", eventType, data);
    }
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
    const payload = data ? jc.encode(data) : undefined;
    const response = await this.nc.request(subject, payload, {
      timeout: 30000,
    });
    return jc.decode(response.data) as T;
  }

  get isConnected(): boolean {
    return this.nc !== null && !this.nc.isClosed();
  }
}

// Singleton instance
export const natsManager = new NatsManager();
