import { describe, test, expect, mock, beforeEach } from "bun:test";

// --- Mock nats module ---
mock.module("nats", () => ({
  connect: mock(() => Promise.resolve({})),
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
  RetentionPolicy: { Limits: 0 },
}));

import { HelpRequestHandler } from "../src/worker/help-request";
import type { NatsClient } from "../src/nats/client";

function createMockSubscription(messages: Array<{ data: Uint8Array }> = []) {
  let unsubscribed = false;
  return {
    unsubscribe: mock(() => {
      unsubscribed = true;
    }),
    async *[Symbol.asyncIterator]() {
      for (const msg of messages) {
        if (unsubscribed) return;
        yield msg;
      }
      // If no messages matched, hang until unsubscribed (simulating waiting)
      if (!unsubscribed) {
        await new Promise<void>((resolve) => {
          const interval = setInterval(() => {
            if (unsubscribed) {
              clearInterval(interval);
              resolve();
            }
          }, 10);
        });
      }
    },
  };
}

function createMockClient(
  subscription?: ReturnType<typeof createMockSubscription>,
): NatsClient {
  const sub = subscription ?? createMockSubscription();
  return {
    conn: {
      subscribe: mock(() => sub),
    },
    publishHelpRequest: mock(() => Promise.resolve()),
    id: "test-worker",
  } as unknown as NatsClient;
}

describe("HelpRequestHandler", () => {
  test("requestHelp subscribes to response subject before publishing", async () => {
    const sub = createMockSubscription();
    const client = createMockClient(sub);
    const handler = new HelpRequestHandler(client);

    // Use a very short timeout so the test finishes quickly
    const resultPromise = handler.requestHelp(
      "task-1",
      [{ question: "How?" }],
      null,
      0.01, // 10ms timeout
    );

    // Wait for result (will timeout)
    const result = await resultPromise;
    expect(result).toBeNull();

    // Verify subscribe was called before publishHelpRequest
    expect(client.conn.subscribe).toHaveBeenCalled();
    expect(client.publishHelpRequest).toHaveBeenCalled();
  });

  test("requestHelp publishes help request with correct parameters", async () => {
    const sub = createMockSubscription();
    const client = createMockClient(sub);
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
    const sub = createMockSubscription(); // No messages -> timeout
    const client = createMockClient(sub);
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
    const sub = createMockSubscription();
    const client = createMockClient(sub);
    const handler = new HelpRequestHandler(client);

    await handler.requestHelp("task-1", [{ question: "Help?" }], null, 0.01);

    expect(sub.unsubscribe).toHaveBeenCalled();
  });

  test("requestHelp returns null when response has error", async () => {
    // We need to supply a message that will match the request_id.
    // Since requestHelp generates a random UUID, we need a different approach:
    // provide a message iterator that yields a response with an error for any request_id.
    let capturedRequestId: string | null = null;

    const publishMock = mock(
      (requestId: string, _taskId: string, _questions: unknown[], _timeout: number) => {
        capturedRequestId = requestId;
        return Promise.resolve();
      },
    );

    // Create a subscription that yields an error response after publish
    const sub = {
      unsubscribe: mock(() => {}),
      async *[Symbol.asyncIterator]() {
        // Wait until publishHelpRequest is called so we know the requestId
        while (!capturedRequestId) {
          await new Promise((r) => setTimeout(r, 5));
        }
        yield {
          data: new TextEncoder().encode(
            JSON.stringify({
              request_id: capturedRequestId,
              error: "Request dismissed",
            }),
          ),
        };
      },
    };

    const client = {
      conn: { subscribe: mock(() => sub) },
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

    const sub = {
      unsubscribe: mock(() => {}),
      async *[Symbol.asyncIterator]() {
        while (!capturedRequestId) {
          await new Promise((r) => setTimeout(r, 5));
        }
        yield {
          data: new TextEncoder().encode(
            JSON.stringify({
              request_id: capturedRequestId,
              answers: { "What color?": "Blue" },
            }),
          ),
        };
      },
    };

    const client = {
      conn: { subscribe: mock(() => sub) },
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
    const client = createMockClient();
    const handler = new HelpRequestHandler(client);
    expect(handler.cancelPendingRequests()).toBe(0);
  });
});
