/**
 * NATS message payload types for the Figaro worker.
 *
 * These interfaces match the JSON payloads the Python worker sends and receives
 * over Core NATS and JetStream. Field names use snake_case to match the wire format.
 */

/** Published to figaro.register.worker on connect. */
export interface RegistrationPayload {
  worker_id: string;
  capabilities: string[];
  novnc_url: string | null;
  status: "idle" | "busy";
  metadata: {
    os: string;
    hostname: string;
  };
}

/** Published to figaro.heartbeat.worker.{worker_id} periodically. */
export interface HeartbeatPayload {
  client_id: string;
  status?: string;
}

/** Options embedded in a task assignment. */
export interface TaskOptions {
  permission_mode?: string;
  max_turns?: number;
  start_url?: string;
  self_healing?: boolean;
}

/** Received on figaro.worker.{worker_id}.task from the orchestrator. */
export interface TaskPayload {
  task_id: string;
  prompt: string;
  options: TaskOptions;
}

/**
 * Published to figaro.task.{task_id}.message via JetStream.
 *
 * Contains the serialized SDK message fields spread at the top level,
 * plus task_id, worker_id, and __type__ for deserialization.
 */
export interface TaskMessagePayload {
  task_id: string;
  worker_id: string;
  __type__: string;
  [key: string]: unknown;
}

/** Published to figaro.task.{task_id}.complete via JetStream. */
export interface TaskCompletePayload {
  task_id: string;
  worker_id: string;
  result: Record<string, unknown> | null;
}

/** Published to figaro.task.{task_id}.error via JetStream. */
export interface TaskErrorPayload {
  task_id: string;
  worker_id: string;
  error: string;
}

/** Published to figaro.help.request via Core NATS. */
export interface HelpRequestPayload {
  request_id: string;
  worker_id: string;
  task_id: string;
  questions: Array<Record<string, unknown>>;
  timeout_seconds: number;
}

/** Received on figaro.help.{request_id}.response via Core NATS. */
export interface HelpResponsePayload {
  request_id: string;
  answers?: Record<string, string>;
  error?: string;
}
