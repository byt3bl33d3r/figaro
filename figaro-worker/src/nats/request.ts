import {
  type NatsConnection,
  type JetStreamClient,
  type JetStreamSubscription,
  JSONCodec,
  DeliverPolicy,
} from "nats";
import { injectTraceContext } from "../tracing/propagation";

// biome-ignore lint: JSON payloads are loosely typed
export type JsonData = Record<string, any>;

export const codec = JSONCodec<JsonData>();

/** Send a NATS request/reply with JSON encode/decode. */
export async function natsRequest(
  nc: NatsConnection,
  subject: string,
  data: JsonData,
  timeout: number = 10_000,
): Promise<JsonData> {
  const headers = injectTraceContext();
  const response = await nc.request(subject, codec.encode(data), { timeout, headers });
  return codec.decode(response.data);
}

/** Subscribe to a JetStream subject with an ephemeral push consumer for new messages. */
export async function subscribeJetStream(
  js: JetStreamClient,
  subject: string,
  handler: (data: JsonData) => void,
): Promise<{ unsubscribe: () => void }> {
  const sub: JetStreamSubscription = await js.subscribe(subject, {
    config: {
      deliver_policy: DeliverPolicy.New,
    },
  });
  (async () => {
    for await (const msg of sub) {
      try {
        const data = codec.decode(msg.data);
        handler(data);
        msg.ack();
      } catch (err) {
        console.error(`[nats-client] Error in JetStream handler for ${subject}:`, err);
      }
    }
  })();
  return {
    unsubscribe: () => {
      sub.unsubscribe();
    },
  };
}
