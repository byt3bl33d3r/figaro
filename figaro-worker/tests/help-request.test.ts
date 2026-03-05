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
 * Create a mock JetStream subscription that calls the handler with provided
 * data payloads. Returns an object with an unsubscribe mock.
 */
function createMockJetStreamSub(
  dataPayloads: Array<Record<string, unknown>> = [],
) {
  const unsubscribeMock = mock(() => {});
  // subscribeJetStream returns { unsubscribe }. The handler is called for each message.
  const subscribeFn = mock(
    async (
      _subject: string,
      handler: (data: Record<string, unknown>) => void,
    ) => {
      // Deliver messages asynchronously (after publish has been called)
      for (const payload of dataPayloads) {
        setTimeout(() => handler(payload), 15);
      }
      return { unsubscribe: unsubscribeMock };
    },
  );
  return { subscribeFn, unsubscribeMock };
}

function createMockClient(opts?: {
  subscribeFn?: ReturnType<typeof createMockJetStreamSub>["subscribeFn"];
}): NatsClient {
  const { subscribeFn } = opts ?? createMockJetStreamSub();
  return {
    subscribeJetStream: subscribeFn,
    publishHelpRequest: mock(() => Promise.resolve()),
    id: "test-worker",
  } as unknown as NatsClient;
}

describe("HelpRequestHandler", () => {
  test("requestHelp subscribes via JetStream before publishing", async () => {
    const { subscribeFn } = createMockJetStreamSub();
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

    // Verify subscribeJetStream was called before publishHelpRequest
    expect(subscribeFn).toHaveBeenCalled();
    expect(client.publishHelpRequest).toHaveBeenCalled();
  });

  test("requestHelp publishes help request with correct parameters", async () => {
    const { subscribeFn } = createMockJetStreamSub();
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
    const { subscribeFn } = createMockJetStreamSub(); // No messages -> timeout
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
    const { subscribeFn, unsubscribeMock } = createMockJetStreamSub();
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

    // subscribeJetStream delivers the error response after a short delay
    const subscribeFn = mock(
      async (
        _subject: string,
        handler: (data: Record<string, unknown>) => void,
      ) => {
        // Wait for publish to capture the requestId, then deliver error response
        const interval = setInterval(() => {
          if (capturedRequestId) {
            clearInterval(interval);
            handler({
              request_id: capturedRequestId,
              error: "Request dismissed",
            });
          }
        }, 5);
        return { unsubscribe: mock(() => clearInterval(interval)) };
      },
    );

    const client = {
      subscribeJetStream: subscribeFn,
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

    const subscribeFn = mock(
      async (
        _subject: string,
        handler: (data: Record<string, unknown>) => void,
      ) => {
        const interval = setInterval(() => {
          if (capturedRequestId) {
            clearInterval(interval);
            handler({
              request_id: capturedRequestId,
              answers: { "What color?": "Blue" },
            });
          }
        }, 5);
        return { unsubscribe: mock(() => clearInterval(interval)) };
      },
    );

    const client = {
      subscribeJetStream: subscribeFn,
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
    const { subscribeFn } = createMockJetStreamSub();
    const client = createMockClient({ subscribeFn });
    const handler = new HelpRequestHandler(client);
    expect(handler.cancelPendingRequests()).toBe(0);
  });
});
