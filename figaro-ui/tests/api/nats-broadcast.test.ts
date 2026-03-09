import { describe, it, expect, beforeEach, vi } from "vitest";
import { handleBroadcastEvent } from "../../src/api/nats-broadcast-handler";
import { useMessagesStore } from "../../src/stores/messages";
import { useWorkersStore } from "../../src/stores/workers";
import { useTasksStore } from "../../src/stores/tasks";
import { useSupervisorsStore } from "../../src/stores/supervisors";

describe("handleBroadcastEvent", () => {
  beforeEach(() => {
    useMessagesStore.setState({ events: [] });
    useWorkersStore.setState({ workers: [] });
    useTasksStore.setState({ tasks: [] });
    useSupervisorsStore.setState({ supervisors: [] });
  });

  describe("JetStream-duplicated events are silently ignored", () => {
    const ignoredEvents = [
      {
        type: "task_assigned",
        data: { task_id: "t1", worker_id: "w1" },
      },
      {
        type: "task_message",
        data: {
          task_id: "t1",
          worker_id: "w1",
          type: "system",
          subtype: "init",
        },
      },
      {
        type: "task_error",
        data: { task_id: "t1", worker_id: "w1", error: "boom" },
      },
      {
        type: "task_submitted_to_supervisor",
        data: { task_id: "t1", supervisor_id: "s1" },
      },
    ];

    for (const { type, data } of ignoredEvents) {
      it(`should ignore "${type}" without logging or updating stores`, () => {
        const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

        handleBroadcastEvent(type, data);

        expect(consoleSpy).not.toHaveBeenCalled();
        expect(useMessagesStore.getState().events).toHaveLength(0);
        consoleSpy.mockRestore();
      });
    }
  });

  it('should log unknown broadcast events', () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    handleBroadcastEvent("some_unknown_event", { foo: "bar" });

    expect(consoleSpy).toHaveBeenCalledWith(
      "Unknown broadcast event:",
      "some_unknown_event",
      { foo: "bar" }
    );
    consoleSpy.mockRestore();
  });
});
