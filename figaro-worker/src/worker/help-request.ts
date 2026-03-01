/**
 * Worker-side help request handler for human-in-the-loop assistance.
 *
 * Subscribes per-request to the specific Core NATS response subject
 * (figaro.help.{request_id}.response) for reliable delivery. JetStream
 * publish also delivers to Core NATS subscribers, so this works with
 * the orchestrator's js_publish without needing a JetStream consumer.
 *
 * Ported from figaro-worker/src/figaro_worker/worker/help_request.py
 */

import { JSONCodec, type Subscription } from "nats";
import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";
import type { HelpResponsePayload } from "../types";

const codec = JSONCodec<HelpResponsePayload>();

export class HelpRequestHandler {
  private readonly client: NatsClient;

  constructor(client: NatsClient) {
    this.client = client;
  }

  /**
   * Request human help and wait for a response.
   *
   * Subscribes to the specific response subject via Core NATS before
   * sending the request, ensuring no race conditions with delivery.
   *
   * @param taskId - The ID of the current task
   * @param questions - List of questions in AskUserQuestion format
   * @param context - Optional context to include with the request
   * @param timeoutSeconds - How long to wait for a response (default 30 min)
   * @returns A record mapping question text to answers, or null if timeout/error
   */
  async requestHelp(
    taskId: string,
    questions: Array<Record<string, unknown>>,
    context?: Record<string, unknown> | null,
    timeoutSeconds: number = 1800,
  ): Promise<Record<string, string> | null> {
    const requestId = crypto.randomUUID();

    const subject = Subjects.helpResponse(requestId);
    const sub: Subscription = this.client.conn.subscribe(subject);

    try {
      // Start listening for the response in the background.
      // The async iterator will yield messages as they arrive.
      const responsePromise = (async (): Promise<HelpResponsePayload | null> => {
        for await (const msg of sub) {
          const data = codec.decode(msg.data);
          if (data.request_id === requestId) {
            return data;
          }
        }
        // Subscription was drained/unsubscribed before a matching message arrived
        return null;
      })();

      // Publish the help request AFTER subscribing (race condition prevention)
      await this.client.publishHelpRequest(
        requestId,
        taskId,
        questions,
        timeoutSeconds,
      );

      // Race the response against a timeout
      const timeoutPromise = new Promise<null>((resolve) => {
        setTimeout(() => resolve(null), timeoutSeconds * 1000);
      });

      const result = await Promise.race([responsePromise, timeoutPromise]);

      if (result === null) {
        return null;
      }

      // Check for errors in the response
      if (result.error) {
        return null;
      }

      return result.answers ?? null;
    } finally {
      sub.unsubscribe();
    }
  }

  /**
   * Cancel all pending help requests.
   *
   * No-op: subscriptions are cleaned up in requestHelp's finally block.
   * @returns Count of cancelled requests (always 0).
   */
  cancelPendingRequests(): number {
    return 0;
  }
}
