import { JSONCodec, type Subscription } from "nats";
import type { NatsClient } from "../nats/client";
import { Subjects } from "../nats/subjects";
import { traced } from "../tracing/tracer";
import { result, type JsonData } from "./tool-helpers";

const DELEGATION_INACTIVITY_TIMEOUT = 600;

const codec = JSONCodec<JsonData>();

/**
 * Wait for a delegated task to complete using Core NATS subscriptions.
 *
 * Uses Core NATS (not JetStream consumers) for reliability — JetStream
 * publishes also deliver to Core NATS subscribers on the same subject.
 * Subscriptions should be set up BEFORE the delegation request is sent
 * to prevent race conditions (see delegateToWorker).
 */
export function waitForDelegation(
  client: NatsClient,
  taskId: string,
  apiResult: JsonData,
  inactivityTimeout: number = DELEGATION_INACTIVITY_TIMEOUT,
): {
  promise: Promise<JsonData>;
  subs: Subscription[];
} {
  const subs: Subscription[] = [];
  let timer: ReturnType<typeof setTimeout>;
  let settled = false;

  function cleanup(): void {
    clearTimeout(timer);
    for (const sub of subs) {
      try {
        sub.unsubscribe();
      } catch {
        // ignore
      }
    }
  }

  let settle!: (value: JsonData) => void;
  const innerPromise = new Promise<JsonData>((res) => {
    settle = res;
  });

  // Wrap the inner promise with tracing
  const promise = traced("supervisor.wait_for_delegation", async (span) => {
    span.setAttribute("task.id", taskId);
    return innerPromise;
  });

  function resetTimer(): void {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      console.warn(
        `[supervisor-tools] Worker inactivity timeout for task ${taskId}`,
      );
      settle(
        result({
          ...apiResult,
          status: "timeout",
          message: `Worker had no activity for ${inactivityTimeout} seconds`,
        }),
      );
    }, inactivityTimeout * 1000);
  }

  resetTimer();

  // Subscribe via Core NATS. JetStream publishes also deliver to Core NATS
  // subscribers, so no JetStream consumer needed (same pattern as help-request).
  const nc = client.conn;

  const subComplete = nc.subscribe(Subjects.taskComplete(taskId));
  subs.push(subComplete);
  (async () => {
    for await (const msg of subComplete) {
      try {
        const data = codec.decode(msg.data);
        if (settled) return;
        settled = true;
        cleanup();
        settle(
          result({
            ...apiResult,
            status: "completed",
            worker_result: data.result,
          }),
        );
      } catch (err) {
        console.error(
          `[supervisor-tools] Error processing completion for task ${taskId}:`,
          err,
        );
      }
    }
  })();

  const subError = nc.subscribe(Subjects.taskError(taskId));
  subs.push(subError);
  (async () => {
    for await (const msg of subError) {
      try {
        const data = codec.decode(msg.data);
        if (settled) return;
        settled = true;
        cleanup();
        settle(
          result({
            ...apiResult,
            status: "failed",
            error: data.error ?? "Unknown error",
          }),
        );
      } catch (err) {
        console.error(
          `[supervisor-tools] Error processing error for task ${taskId}:`,
          err,
        );
      }
    }
  })();

  const subMessage = nc.subscribe(Subjects.taskMessage(taskId));
  subs.push(subMessage);
  (async () => {
    for await (const msg of subMessage) {
      try {
        resetTimer();
      } catch {
        // ignore
      }
    }
  })();

  return { promise, subs };
}
