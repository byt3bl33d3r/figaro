/**
 * JetStream stream configuration for Figaro.
 *
 * Ported from figaro-nats/src/figaro_nats/streams.py
 */

import { RetentionPolicy, type NatsConnection } from "nats";

export const TASKS_STREAM = "TASKS";
export const TASKS_SUBJECTS = ["figaro.task.>"];
export const TASKS_MAX_AGE_SECONDS = 7 * 24 * 60 * 60; // 7 days

export const HELP_STREAM = "HELP";
export const HELP_SUBJECTS = ["figaro.help.*.response"];
export const HELP_MAX_AGE_SECONDS = 24 * 60 * 60; // 1 day

/** Convert seconds to nanoseconds (nats.js uses nanos for max_age). */
function secondsToNanos(seconds: number): number {
  return seconds * 1_000_000_000;
}

/**
 * Create or update a single JetStream stream.
 */
async function ensureStream(
  nc: NatsConnection,
  name: string,
  subjects: string[],
  maxAgeSeconds: number,
): Promise<void> {
  const jsm = await nc.jetstreamManager();

  try {
    // Try to get the existing stream and update it
    await jsm.streams.info(name);
    await jsm.streams.update(name, {
      subjects,
      max_age: secondsToNanos(maxAgeSeconds),
    });
    console.log(`[streams] Updated JetStream stream: ${name}`);
  } catch {
    // Stream does not exist yet -- create it
    await jsm.streams.add({
      name,
      subjects,
      retention: RetentionPolicy.Limits,
      max_age: secondsToNanos(maxAgeSeconds),
    });
    console.log(`[streams] Created JetStream stream: ${name}`);
  }
}

/**
 * Create or update all JetStream streams required by Figaro.
 */
export async function ensureStreams(nc: NatsConnection): Promise<void> {
  await Promise.all([
    ensureStream(nc, TASKS_STREAM, TASKS_SUBJECTS, TASKS_MAX_AGE_SECONDS),
    ensureStream(nc, HELP_STREAM, HELP_SUBJECTS, HELP_MAX_AGE_SECONDS),
  ]);
}
