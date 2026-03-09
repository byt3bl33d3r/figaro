import {
  type NatsConnection,
  type JetStreamClient,
} from "nats";

import { Subjects } from "./subjects";
import { injectTraceContext } from "../tracing/propagation";
import { codec, type JsonData } from "./request";

/** Publish a task message (SDK output) via JetStream. */
export async function publishTaskMessage(
  js: JetStreamClient,
  clientId: string,
  clientType: "worker" | "supervisor",
  taskId: string,
  message: JsonData,
): Promise<void> {
  const headers = injectTraceContext();
  await js.publish(
    Subjects.taskMessage(taskId),
    codec.encode({
      task_id: taskId,
      worker_id: clientId,
      ...(clientType === "supervisor" ? { supervisor_id: clientId } : {}),
      ...message,
    }),
    { headers },
  );
}

/** Publish task completion via JetStream. */
export async function publishTaskComplete(
  js: JetStreamClient,
  clientId: string,
  clientType: "worker" | "supervisor",
  taskId: string,
  result: unknown,
): Promise<void> {
  const headers = injectTraceContext();
  await js.publish(
    Subjects.taskComplete(taskId),
    codec.encode({
      task_id: taskId,
      worker_id: clientId,
      ...(clientType === "supervisor" ? { supervisor_id: clientId } : {}),
      result,
    }),
    { headers },
  );
}

/** Publish task error via JetStream. */
export async function publishTaskError(
  js: JetStreamClient,
  clientId: string,
  clientType: "worker" | "supervisor",
  taskId: string,
  error: string,
): Promise<void> {
  const headers = injectTraceContext();
  await js.publish(
    Subjects.taskError(taskId),
    codec.encode({
      task_id: taskId,
      worker_id: clientId,
      ...(clientType === "supervisor" ? { supervisor_id: clientId } : {}),
      error,
    }),
    { headers },
  );
}

/** Publish a help request via Core NATS. */
export async function publishHelpRequest(
  nc: NatsConnection,
  clientId: string,
  clientType: "worker" | "supervisor",
  requestId: string,
  taskId: string,
  questions: JsonData[],
  timeoutSeconds: number = 300,
): Promise<void> {
  nc.publish(
    Subjects.HELP_REQUEST,
    codec.encode({
      request_id: requestId,
      worker_id: clientId,
      ...(clientType === "supervisor" ? { supervisor_id: clientId } : {}),
      task_id: taskId,
      questions,
      timeout_seconds: timeoutSeconds,
    }),
  );
}

/** Publish status update via heartbeat. */
export async function sendStatus(
  nc: NatsConnection,
  clientId: string,
  clientType: "worker" | "supervisor",
  status: string,
): Promise<void> {
  nc.publish(
    Subjects.heartbeat(clientType, clientId),
    codec.encode({
      client_id: clientId,
      status,
    }),
  );
}

/** Publish heartbeat. */
export async function sendHeartbeat(
  nc: NatsConnection,
  clientId: string,
  clientType: "worker" | "supervisor",
  capabilities: string[],
  status: string,
  novncUrl: string | null,
): Promise<void> {
  const payload: JsonData = {
    client_id: clientId,
    client_type: clientType,
    capabilities,
    status,
  };
  if (clientType === "worker") {
    payload.novnc_url = novncUrl;
  }
  nc.publish(
    Subjects.heartbeat(clientType, clientId),
    codec.encode(payload),
  );
}
