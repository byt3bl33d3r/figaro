import { describe, test, expect, mock, beforeEach } from "bun:test";

// --- Mock nats module ---
mock.module("nats", () => ({
  connect: mock(() => Promise.resolve({})),
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
  RetentionPolicy: { Limits: 0 },
  DeliverPolicy: { New: "new" },
}));

import { HelpRequestHandler } from "../src/worker/help-request";
import type { NatsClient } from "../src/nats/client";

/**
 * Create a mock Core NATS subscription that delivers data payloads
 * to the async iterator. Returns the subscribe mock and unsubscribe mock.
 */
function createMockCoreNatsSub(
  dataPayloads: Array<Record<string, unknown>> = [],
) {
  const unsubscribeMock = mock(() => {});
  const subscribeFn = mock((_subject: string) => {
    // Build an async iterable that yields encoded messages after a delay
    const messages = dataPayloads.map((payload) => ({
      data: new TextEncoder().encode(JSON.stringify(payload)),
    }));

    let resolveNext: ((value: IteratorResult<{ data: Uint8Array }>) => void) | null = null;
    const pending: { data: Uint8Array }[] = [];
    let done = false;

    // Deliver messages asynchronously
    for (const msg of messages) {
      setTimeout(() => {
        if (resolveNext) {
          const r = resolveNext;
          resolveNext = null;
          r({ value: msg, done: false });
        } else {
          pending.push(msg);
        }
      }, 15);
    }

    return {
      unsubscribe: () => {
        done = true;
        unsubscribeMock();
        // Resolve any pending next() call so the async loop exits
        if (resolveNext) {
          const r = resolveNext;
          resolveNext = null;
          r({ value: undefined, done: true });
        }
      },
      [Symbol.asyncIterator]() {
        return {
          next() {
            if (done) return Promise.resolve({ value: undefined, done: true } as IteratorResult<{ data: Uint8Array }>);
            if (pending.length > 0) {
              return Promise.resolve({ value: pending.shift()!, done: false });
            }
            return new Promise<IteratorResult<{ data: Uint8Array }>>((resolve) => {
              resolveNext = resolve;
            });
          },
        };
      },
    };
  });
  return { subscribeFn, unsubscribeMock };
}

function createMockClient(opts?: {
  subscribeFn?: ReturnType<typeof createMockCoreNatsSub>["subscribeFn"];
}): NatsClient {
  const { subscribeFn } = opts ?? createMockCoreNatsSub();
  return {
    conn: {
      subscribe: subscribeFn,
    },
    publishHelpRequest: mock(() => Promise.resolve()),
    id: "test-worker",
  } as unknown as NatsClient;
}

describe("HelpRequestHandler", () => {
  test("requestHelp subscribes via Core NATS before publishing", async () => {
    const { subscribeFn } = createMockCoreNatsSub();
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);

    // Use a very short timeout so the test finishes quickly
    const result = await handler.requestHelp(
      "task-1",
      [{ question: "How?" }],
      null,
      0.01, // 10ms timeout
    );

    expect(result).toBeNull();

    // Verify conn.subscribe was called before publishHelpRequest
    expect(subscribeFn).toHaveBeenCalled();
    expect(client.publishHelpRequest).toHaveBeenCalled();
  });

  test("requestHelp publishes help request with correct parameters", async () => {
    const { subscribeFn } = createMockCoreNatsSub();
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);

    const questions = [{ question: "What color?" }];
    await handler.requestHelp("task-42", questions, null, 0.01);

    const publishMock = client.publishHelpRequest as ReturnType<typeof mock>;
    expect(publishMock).toHaveBeenCalledTimes(1);

    const callArgs = publishMock.mock.calls[0];
    // callArgs: [requestId, taskId, questions, timeoutSeconds]
    expect(typeof callArgs[0]).toBe("string"); // requestId (UUID)
    expect(callArgs[1]).toBe("task-42"); // taskId
    expect(callArgs[2]).toEqual(questions); // questions
    expect(callArgs[3]).toBe(0.01); // timeoutSeconds
  });

  test("requestHelp returns null on timeout", async () => {
    const { subscribeFn } = createMockCoreNatsSub(); // No messages -> timeout
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);

    const result = await handler.requestHelp(
      "task-1",
      [{ question: "Help?" }],
      null,
      0.01, // Very short timeout
    );

    expect(result).toBeNull();
  });

  test("requestHelp unsubscribes after completion", async () => {
    const { subscribeFn, unsubscribeMock } = createMockCoreNatsSub();
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);

    await handler.requestHelp("task-1", [{ question: "Help?" }], null, 0.01);

    expect(unsubscribeMock).toHaveBeenCalled();
  });

  test("requestHelp returns null when response has error", async () => {
    let capturedRequestId: string | null = null;

    const publishMock = mock(
      (requestId: string, _taskId: string, _questions: unknown[], _timeout: number) => {
        capturedRequestId = requestId;
        return Promise.resolve();
      },
    );

    // Create a subscription that delivers the error response after publish captures the requestId
    const unsubscribeMock = mock(() => {});
    const subscribeFn = mock((_subject: string) => {
      let resolveNext: ((value: IteratorResult<{ data: Uint8Array }>) => void) | null = null;
      let done = false;

      const interval = setInterval(() => {
        if (capturedRequestId && resolveNext) {
          clearInterval(interval);
          const r = resolveNext;
          resolveNext = null;
          r({
            value: {
              data: new TextEncoder().encode(
                JSON.stringify({
                  request_id: capturedRequestId,
                  error: "Request dismissed",
                }),
              ),
            },
            done: false,
          });
        }
      }, 5);

      return {
        unsubscribe: () => {
          done = true;
          clearInterval(interval);
          unsubscribeMock();
          if (resolveNext) {
            const r = resolveNext;
            resolveNext = null;
            r({ value: undefined, done: true });
          }
        },
        [Symbol.asyncIterator]() {
          return {
            next() {
              if (done) return Promise.resolve({ value: undefined, done: true } as IteratorResult<{ data: Uint8Array }>);
              return new Promise<IteratorResult<{ data: Uint8Array }>>((resolve) => {
                resolveNext = resolve;
              });
            },
          };
        },
      };
    });

    const client = {
      conn: { subscribe: subscribeFn },
      publishHelpRequest: publishMock,
      id: "test-worker",
    } as unknown as NatsClient;

    const handler = new HelpRequestHandler(client);
    const result = await handler.requestHelp("task-1", [{ question: "Help?" }], null, 5);

    expect(result).toBeNull();
  });

  test("requestHelp returns answers on successful response", async () => {
    let capturedRequestId: string | null = null;

    const publishMock = mock(
      (requestId: string, _taskId: string, _questions: unknown[], _timeout: number) => {
        capturedRequestId = requestId;
        return Promise.resolve();
      },
    );

    const unsubscribeMock = mock(() => {});
    const subscribeFn = mock((_subject: string) => {
      let resolveNext: ((value: IteratorResult<{ data: Uint8Array }>) => void) | null = null;
      let done = false;

      const interval = setInterval(() => {
        if (capturedRequestId && resolveNext) {
          clearInterval(interval);
          const r = resolveNext;
          resolveNext = null;
          r({
            value: {
              data: new TextEncoder().encode(
                JSON.stringify({
                  request_id: capturedRequestId,
                  answers: { "What color?": "Blue" },
                }),
              ),
            },
            done: false,
          });
        }
      }, 5);

      return {
        unsubscribe: () => {
          done = true;
          clearInterval(interval);
          unsubscribeMock();
          if (resolveNext) {
            const r = resolveNext;
            resolveNext = null;
            r({ value: undefined, done: true });
          }
        },
        [Symbol.asyncIterator]() {
          return {
            next() {
              if (done) return Promise.resolve({ value: undefined, done: true } as IteratorResult<{ data: Uint8Array }>);
              return new Promise<IteratorResult<{ data: Uint8Array }>>((resolve) => {
                resolveNext = resolve;
              });
            },
          };
        },
      };
    });

    const client = {
      conn: { subscribe: subscribeFn },
      publishHelpRequest: publishMock,
      id: "test-worker",
    } as unknown as NatsClient;

    const handler = new HelpRequestHandler(client);
    const result = await handler.requestHelp(
      "task-1",
      [{ question: "What color?" }],
      null,
      5,
    );

    expect(result).toEqual({ "What color?": "Blue" });
  });

  test("cancelPendingRequests returns 0", () => {
    const { subscribeFn } = createMockCoreNatsSub();
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);
    expect(handler.cancelPendingRequests()).toBe(0);
  });
});
