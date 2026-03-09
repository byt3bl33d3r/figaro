import type { NatsClient } from "../nats/client";

// biome-ignore lint: JSON payloads are loosely typed
export type JsonData = Record<string, any>;

export function result(data: unknown): {
  content: Array<{ type: string; text: string }>;
} {
  const text =
    typeof data === "object" && data !== null
      ? JSON.stringify(data, null, 2)
      : String(data);
  return { content: [{ type: "text", text }] };
}

export function error(msg: string): {
  content: Array<{ type: string; text: string }>;
} {
  return { content: [{ type: "text", text: `Error: ${msg}` }] };
}

export function createNatsRequest(client: NatsClient) {
  return async function natsRequest(
    subject: string,
    data: JsonData,
    timeout: number = 10_000,
  ): Promise<JsonData> {
    try {
      const resp = await client.request(subject, data, timeout);
      if (resp.error) {
        console.error(
          `[supervisor-tools] NATS request ${subject} returned error: ${resp.error}`,
        );
      }
      return resp;
    } catch (e) {
      console.error(
        `[supervisor-tools] NATS request ${subject} failed (timeout=${timeout}ms): ${e}`,
      );
      return { error: `Request failed: ${e}` };
    }
  };
}
