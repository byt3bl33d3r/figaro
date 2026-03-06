import { loadConfig } from "./config";
import { NatsClient } from "./nats/client";
import { TaskExecutor } from "./worker/executor";
import { SupervisorExecutor } from "./supervisor/executor";
import type { TaskPayload } from "./types";

const config = loadConfig();
const label = config.mode === "supervisor" ? "supervisor" : "worker";

console.log(`[${label}] Starting ${label} ${config.workerId}`);
console.log(`[${label}] Connecting to NATS at ${config.natsUrl}`);
if (config.mode === "worker") {
  console.log(`[${label}] VNC URL: ${config.novncUrl}`);
}

const client = new NatsClient({
  natsUrl: config.natsUrl,
  workerId: config.workerId,
  clientType: config.mode,
  novncUrl: config.mode === "worker" ? config.novncUrl : undefined,
});

if (config.mode === "supervisor") {
  const executor = new SupervisorExecutor(
    client,
    config.model,
    config.maxTurns,
    config.claudeCodePath,
    config.loopDetection,
  );
  client.on("task", (payload) => executor.handleTask(payload));
  client.onStop((taskId) => executor.stopTask(taskId));
} else {
  const executor = new TaskExecutor(client, config.model, config.claudeCodePath, config.loopDetection);
  client.on("task", (payload) => executor.handleTask(payload as TaskPayload));
  client.onStop((taskId) => executor.stopTask(taskId));
}

const connected = await client.connect();
if (!connected) {
  console.error(`[${label}] Failed to connect to NATS, exiting`);
  process.exit(1);
}

async function runHeartbeat(interval: number): Promise<void> {
  try {
    await client.sendHeartbeat();
  } catch (e) {
    console.warn(`[${label}] Initial heartbeat failed: ${e}`);
  }
  while (true) {
    await Bun.sleep(interval * 1000);
    try {
      await client.sendHeartbeat();
    } catch (e) {
      console.warn(`[${label}] Heartbeat failed: ${e}`);
    }
  }
}

let shuttingDown = false;

async function shutdown(): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`[${label}] Shutting down...`);
  await client.close();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

await Promise.all([
  client.run(),
  runHeartbeat(config.heartbeatInterval),
]);
