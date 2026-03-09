import type {
  NatsConnection,
  Subscription,
  JetStreamClient,
  Msg,
} from "nats.ws";
import type {
  WorkersPayload,
  SupervisorsPayload,
  HelpRequestCreatedPayload,
  HelpRequestRespondedPayload,
} from "../types";
import { useWorkersStore } from "../stores/workers";
import { useSupervisorsStore } from "../stores/supervisors";
import { useMessagesStore } from "../stores/messages";
import { useHelpRequestsStore } from "../stores/helpRequests";
import { useTasksStore } from "../stores/tasks";
import { handleBroadcastEvent } from "./nats-broadcast-handler";
import { handleTaskEvent } from "./nats-task-handler";
import { jc } from "./nats";

export function setupCoreSubscriptions(
  nc: NatsConnection,
  subscriptions: Subscription[]
): void {
  // Workers broadcast
  const workersSub = nc.subscribe("figaro.broadcast.workers");
  subscriptions.push(workersSub);
  consumeSubscription(workersSub, (data) => {
    const payload = data as unknown as WorkersPayload;
    useWorkersStore.getState().setWorkers(payload.workers);
  });

  // Supervisors broadcast
  const supervisorsSub = nc.subscribe(
    "figaro.broadcast.supervisors"
  );
  subscriptions.push(supervisorsSub);
  consumeSubscription(supervisorsSub, (data) => {
    const payload = data as unknown as SupervisorsPayload;
    useSupervisorsStore.getState().setSupervisors(payload.supervisors);
  });

  // Broadcast catch-all for other events
  const broadcastSub = nc.subscribe("figaro.broadcast.>");
  subscriptions.push(broadcastSub);
  consumeSubscription(broadcastSub, (data, msg) => {
    const subject = msg.subject;
    // Skip subjects that have dedicated handlers above
    if (
      subject === "figaro.broadcast.workers" ||
      subject === "figaro.broadcast.supervisors" ||
      subject === "figaro.broadcast.help_request" ||
      subject === "figaro.broadcast.task_cancelled"
    ) {
      return;
    }

    // Parse event type from subject: figaro.broadcast.{event_type}
    const parts = subject.split(".");
    const eventType = parts.slice(2).join(".");
    handleBroadcastEvent(eventType, data);
  });

  // Dedicated help request broadcast subscription
  // (more reliable than relying solely on the wildcard catch-all)
  const helpBroadcastSub = nc.subscribe(
    "figaro.broadcast.help_request"
  );
  subscriptions.push(helpBroadcastSub);
  consumeSubscription(helpBroadcastSub, (data) => {
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

  // Task cancelled broadcast
  const taskCancelledSub = nc.subscribe("figaro.broadcast.task_cancelled");
  subscriptions.push(taskCancelledSub);
  consumeSubscription(taskCancelledSub, (data) => {
    const payload = data as { task_id: string; worker_id?: string; supervisor_id?: string };
    useTasksStore.getState().removeTask(payload.task_id);
    if (payload.worker_id) {
      useWorkersStore.getState().updateWorkerStatus(payload.worker_id, "idle");
    }
    if (payload.supervisor_id) {
      useSupervisorsStore.getState().updateSupervisorStatus(payload.supervisor_id, "idle");
    }
    useMessagesStore.getState().addEvent({
      worker_id: payload.worker_id,
      supervisor_id: payload.supervisor_id,
      type: "system",
      data: { message: `Task ${payload.task_id.slice(0, 8)}... cancelled` },
    });
  });

  // Help response events (wildcard for request_id)
  const helpResponseSub = nc.subscribe("figaro.help.*.response");
  subscriptions.push(helpResponseSub);
  consumeSubscription(helpResponseSub, (data) => {
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

export async function setupJetStreamSubscription(
  nc: NatsConnection,
  jsCleanup: (() => void)[]
): Promise<JetStreamClient | null> {
  try {
    const js = nc.jetstream();

    // Use an ordered consumer for ephemeral read-only access to task events
    const consumer = await js.consumers.get("TASKS", {
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
            handleTaskEvent(eventType, data);
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

    jsCleanup.push(() => {
      stopped = true;
      messages.close();
    });

    return js;
  } catch (err) {
    console.warn(
      "JetStream TASKS consumer not available (stream may not exist yet):",
      err
    );
    return null;
  }
}

export function consumeSubscription(
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
