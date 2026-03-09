import { describe, it, expect, beforeEach, vi } from "vitest";
import { handleBroadcastEvent } from "../../src/api/nats-broadcast-handler";
import { handleTaskEvent } from "../../src/api/nats-task-handler";
import { useMessagesStore } from "../../src/stores/messages";
import { useWorkersStore } from "../../src/stores/workers";
import { useTasksStore } from "../../src/stores/tasks";
import { useSupervisorsStore } from "../../src/stores/supervisors";

describe("handleBroadcastEvent", () => {
  beforeEach(() => {
    useMessagesStore.setState({ events: [] });
    useWorkersStore.setState({
      workers: new Map([
        ["w1", { id: "w1", status: "busy", novnc_url: "" } as any],
      ]),
    });
    useTasksStore.setState({ tasks: new Map() });
    useSupervisorsStore.setState({
      supervisors: new Map([
        ["s1", { id: "s1", status: "busy" } as any],
      ]),
    });
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
        type: "task_complete",
        data: { task_id: "t1", worker_id: "w1", result: "done" },
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

  describe("task_complete deduplication (regression)", () => {
    it("should produce exactly one event when both JetStream and broadcast fire", () => {
      const payload = {
        task_id: "t1",
        worker_id: "w1",
        result: "done",
      };

      // Simulate: JetStream delivers completion first
      handleTaskEvent("complete", payload);
      // Then orchestrator re-broadcasts the same completion
      handleBroadcastEvent("task_complete", payload);

      const completeEvents = useMessagesStore
        .getState()
        .events.filter((e) => e.type === "task_complete");
      expect(completeEvents).toHaveLength(1);
    });

    it("should produce exactly one event for supervisor completion via both paths", () => {
      const payload = {
        task_id: "t1",
        supervisor_id: "s1",
        result: "done",
      };

      handleTaskEvent("complete", payload);
      handleBroadcastEvent("task_complete", payload);

      const completeEvents = useMessagesStore
        .getState()
        .events.filter((e) => e.type === "supervisor_task_complete");
      expect(completeEvents).toHaveLength(1);
    });
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
