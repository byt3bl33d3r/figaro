import { loadConfig } from "./config";
import { NatsClient } from "./nats/client";
import { TaskExecutor } from "./worker/executor";

const config = loadConfig();

console.log(`[worker] Starting worker ${config.workerId}`);
console.log(`[worker] Connecting to NATS at ${config.natsUrl}`);
console.log(`[worker] VNC URL: ${config.novncUrl}`);

const client = new NatsClient({
  natsUrl: config.natsUrl,
  workerId: config.workerId,
  novncUrl: config.novncUrl,
});

const executor = new TaskExecutor(client, config.model, config.claudeCodePath);
client.on("task", (payload) => executor.handleTask(payload as import("./types").TaskPayload));

const connected = await client.connect();
if (!connected) {
  console.error("[worker] Failed to connect to NATS, exiting");
  process.exit(1);
}

async function runHeartbeat(interval: number): Promise<void> {
  try {
    await client.sendHeartbeat();
  } catch (e) {
    console.warn(`[worker] Initial heartbeat failed: ${e}`);
  }
  while (true) {
    await Bun.sleep(interval * 1000);
    try {
      await client.sendHeartbeat();
    } catch (e) {
      console.warn(`[worker] Heartbeat failed: ${e}`);
    }
  }
}

let shuttingDown = false;

async function shutdown(): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log("[worker] Shutting down...");
  await client.close();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

await Promise.all([
  client.run(),
  runHeartbeat(config.heartbeatInterval),
]);
