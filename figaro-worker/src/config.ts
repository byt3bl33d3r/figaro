import { hostname } from "os";

export interface Config {
  readonly natsUrl: string;
  readonly workerId: string;
  readonly heartbeatInterval: number;
  readonly reconnectDelay: number;
  readonly maxReconnectDelay: number;
  readonly novncUrl: string;
  readonly novncPort: number;
  readonly model: string;
  readonly claudeCodePath: string | undefined;
}

export function loadConfig(): Config {
  const env = process.env;

  const natsUrl = env.WORKER_NATS_URL ?? "nats://localhost:4222";
  const workerIdRaw = env.WORKER_ID ?? null;
  const heartbeatInterval = parseFloat(env.WORKER_HEARTBEAT_INTERVAL ?? "30");
  const reconnectDelay = parseFloat(env.WORKER_RECONNECT_DELAY ?? "1");
  const maxReconnectDelay = parseFloat(env.WORKER_MAX_RECONNECT_DELAY ?? "60");
  const novncUrlRaw = env.WORKER_NOVNC_URL || null;
  const novncPort = parseInt(env.WORKER_NOVNC_PORT ?? "6080", 10);
  const model = env.WORKER_MODEL ?? "claude-opus-4-6";
  const claudeCodePath = env.WORKER_CLAUDE_CODE_PATH ?? undefined;

  const workerId = workerIdRaw ?? hostname();

  const novncUrl =
    novncUrlRaw ?? `ws://${hostname()}:${novncPort}/websockify`;

  return Object.freeze({
    natsUrl,
    workerId,
    heartbeatInterval,
    reconnectDelay,
    maxReconnectDelay,
    novncUrl,
    novncPort,
    model,
    claudeCodePath,
  });
}
