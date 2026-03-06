import { hostname } from "os";

export interface Config {
  readonly mode: "worker" | "supervisor";
  readonly natsUrl: string;
  readonly workerId: string;
  readonly heartbeatInterval: number;
  readonly reconnectDelay: number;
  readonly maxReconnectDelay: number;
  readonly novncUrl: string;
  readonly novncPort: number;
  readonly model: string;
  readonly claudeCodePath: string | undefined;
  readonly maxTurns: number | undefined;
  readonly delegationInactivityTimeout: number;
  readonly loopDetection: {
    enabled: boolean;
    windowSize: number;
    warningThreshold: number;
    criticalThreshold: number;
    pingPongWarning: number;
    pingPongCritical: number;
  };
}

function parseLoopDetectionConfig(prefix: string): Config["loopDetection"] {
  const env = process.env;
  return {
    enabled: (env[`${prefix}_LOOP_DETECTION_ENABLED`] ?? "true") !== "false",
    windowSize: parseInt(env[`${prefix}_LOOP_DETECTION_WINDOW_SIZE`] ?? "30", 10),
    warningThreshold: parseInt(env[`${prefix}_LOOP_DETECTION_WARNING_THRESHOLD`] ?? "10", 10),
    criticalThreshold: parseInt(env[`${prefix}_LOOP_DETECTION_CRITICAL_THRESHOLD`] ?? "20", 10),
    pingPongWarning: parseInt(env[`${prefix}_LOOP_DETECTION_PING_PONG_WARNING`] ?? "6", 10),
    pingPongCritical: parseInt(env[`${prefix}_LOOP_DETECTION_PING_PONG_CRITICAL`] ?? "12", 10),
  };
}

export function loadConfig(): Config {
  const mode: "worker" | "supervisor" = process.argv.includes("--supervisor")
    ? "supervisor"
    : "worker";

  const env = process.env;

  if (mode === "supervisor") {
    const natsUrl = env.SUPERVISOR_NATS_URL ?? "nats://localhost:4222";
    const workerIdRaw = env.SUPERVISOR_ID ?? null;
    const heartbeatInterval = parseFloat(env.SUPERVISOR_HEARTBEAT_INTERVAL ?? "30");
    const reconnectDelay = parseFloat(env.WORKER_RECONNECT_DELAY ?? "1");
    const maxReconnectDelay = parseFloat(env.WORKER_MAX_RECONNECT_DELAY ?? "60");
    const model = env.SUPERVISOR_MODEL ?? "claude-opus-4-6";
    const claudeCodePath = env.SUPERVISOR_CLAUDE_CODE_PATH ?? undefined;
    const maxTurnsRaw = env.SUPERVISOR_MAX_TURNS;
    const maxTurns = maxTurnsRaw ? parseInt(maxTurnsRaw, 10) : undefined;
    const delegationInactivityTimeout = parseFloat(
      env.SUPERVISOR_DELEGATION_INACTIVITY_TIMEOUT ?? "600",
    );

    const workerId = workerIdRaw ?? hostname();

    return Object.freeze({
      mode,
      natsUrl,
      workerId,
      heartbeatInterval,
      reconnectDelay,
      maxReconnectDelay,
      novncUrl: "",
      novncPort: 0,
      model,
      claudeCodePath,
      maxTurns,
      delegationInactivityTimeout,
      loopDetection: parseLoopDetectionConfig("SUPERVISOR"),
    });
  }

  const natsUrl = env.WORKER_NATS_URL ?? "nats://localhost:4222";
  const workerIdRaw = env.WORKER_ID ?? null;
  const heartbeatInterval = parseFloat(env.WORKER_HEARTBEAT_INTERVAL ?? "30");
  const reconnectDelay = parseFloat(env.WORKER_RECONNECT_DELAY ?? "1");
  const maxReconnectDelay = parseFloat(env.WORKER_MAX_RECONNECT_DELAY ?? "60");
  const novncUrlRaw = env.WORKER_NOVNC_URL || null;
  const novncPort = parseInt(env.WORKER_NOVNC_PORT ?? "6080", 10);
  const model = env.WORKER_MODEL ?? "claude-opus-4-6";
  const claudeCodePath = env.WORKER_CLAUDE_CODE_PATH ?? undefined;
  const maxTurnsRaw = env.WORKER_MAX_TURNS;
  const maxTurns = maxTurnsRaw ? parseInt(maxTurnsRaw, 10) : undefined;
  const delegationInactivityTimeout = parseFloat(
    env.WORKER_DELEGATION_INACTIVITY_TIMEOUT ?? "600",
  );

  const workerId = workerIdRaw ?? hostname();

  const novncUrl =
    novncUrlRaw ?? `ws://${hostname()}:${novncPort}/websockify`;

  return Object.freeze({
    mode,
    natsUrl,
    workerId,
    heartbeatInterval,
    reconnectDelay,
    maxReconnectDelay,
    novncUrl,
    novncPort,
    model,
    claudeCodePath,
    maxTurns,
    delegationInactivityTimeout,
    loopDetection: parseLoopDetectionConfig("WORKER"),
  });
}
