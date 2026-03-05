/**
 * Worker-side help request handler for human-in-the-loop assistance.
 *
 * Subscribes per-request to the specific JetStream response subject
 * (figaro.help.{request_id}.response) via the HELP stream. JetStream
 * ensures responses survive NATS reconnections during long waits,
 * matching the Python supervisor's durable subscription approach.
 *
 * Ported from figaro-supervisor/src/figaro_supervisor/supervisor/client.py
 */

import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";
import type { HelpResponsePayload } from "../types";

export class HelpRequestHandler {
  private readonly client: NatsClient;

  constructor(client: NatsClient) {
    this.client = client;
  }

  /**
   * Request human help and wait for a response.
   *
   * Subscribes to the specific response subject via JetStream before
   * sending the request, ensuring no race conditions with delivery.
   * JetStream subscriptions survive NATS reconnections, so responses
   * are not lost during transient connection drops.
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

    let settled = false;
    let settle: (value: HelpResponsePayload | null) => void;
    const responsePromise = new Promise<HelpResponsePayload | null>((res) => {
      settle = res;
    });

    // Subscribe via JetStream (HELP stream covers figaro.help.*.response)
    // before publishing the request to prevent race conditions.
    const sub = await this.client.subscribeJetStream(
      subject,
      (data: Record<string, unknown>) => {
        if (settled) return;
        if (data.request_id === requestId) {
          settled = true;
          settle(data as unknown as HelpResponsePayload);
        }
      },
    );

    try {
      // Publish the help request AFTER subscribing (race condition prevention)
      await this.client.publishHelpRequest(
        requestId,
        taskId,
        questions,
        timeoutSeconds,
      );

      // Race the response against a timeout
      const timeoutPromise = new Promise<null>((resolve) => {
        const timer = setTimeout(() => resolve(null), timeoutSeconds * 1000);
        // Allow the timer to not keep the process alive
        if (typeof timer === "object" && "unref" in timer) {
          timer.unref();
        }
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
      settled = true;
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
