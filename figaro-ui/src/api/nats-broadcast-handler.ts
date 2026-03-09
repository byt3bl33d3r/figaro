import type {
  Worker,
  ErrorPayload,
  StatusPayload,
  ScheduledTask,
  ScheduledTaskExecutedPayload,
  ScheduledTaskSkippedPayload,
  HelpRequestCreatedPayload,
  HelpRequestRespondedPayload,
  HelpRequestTimeoutPayload,
  TaskCompletePayload,
  TaskHealingPayload,
} from "../types";
import { useWorkersStore } from "../stores/workers";
import { useSupervisorsStore } from "../stores/supervisors";
import { useMessagesStore } from "../stores/messages";
import { useScheduledTasksStore } from "../stores/scheduledTasks";
import { useHelpRequestsStore } from "../stores/helpRequests";
import { useTasksStore } from "../stores/tasks";

export function handleBroadcastEvent(
  eventType: string,
  data: unknown
): void {
  const messagesStore = useMessagesStore.getState();
  const workersStore = useWorkersStore.getState();
  const supervisorsStore = useSupervisorsStore.getState();

  switch (eventType) {
    case "worker_connected": {
      const worker = data as unknown as Worker;
      workersStore.updateWorker(worker);
      messagesStore.addEvent({
        worker_id: worker.id,
        type: "system",
        data: { message: `Worker ${worker.id} connected` },
      });
      break;
    }

    case "worker_disconnected": {
      const payload = data as { worker_id: string };
      workersStore.removeWorker(payload.worker_id);
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `Worker ${payload.worker_id} disconnected`,
        },
      });
      break;
    }

    case "status": {
      const payload = data as unknown as StatusPayload;
      workersStore.updateWorkerStatus(
        payload.worker_id,
        payload.status
      );
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "status",
        data: payload,
      });
      break;
    }

    case "error": {
      const payload = data as unknown as ErrorPayload;
      messagesStore.addEvent({
        type: "error",
        data: payload,
      });
      break;
    }

    // Scheduled task broadcasts
    case "scheduled_task_created":
    case "scheduled_task_updated": {
      const task = data as unknown as ScheduledTask;
      useScheduledTasksStore.getState().updateTask(task);
      messagesStore.addEvent({
        type: "system",
        data: {
          message: `Scheduled task "${task.name}" ${eventType === "scheduled_task_created" ? "created" : "updated"}`,
        },
      });
      break;
    }

    case "scheduled_task_deleted": {
      const payload = data as { schedule_id: string };
      useScheduledTasksStore
        .getState()
        .removeTask(payload.schedule_id);
      messagesStore.addEvent({
        type: "system",
        data: { message: "Scheduled task deleted" },
      });
      break;
    }

    case "scheduled_task_executed": {
      const payload =
        data as unknown as ScheduledTaskExecutedPayload;
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `Scheduled task executed (task: ${payload.task_id.slice(0, 8)}...)`,
        },
      });
      break;
    }

    case "scheduled_task_skipped": {
      const payload =
        data as unknown as ScheduledTaskSkippedPayload;
      messagesStore.addEvent({
        type: "system",
        data: {
          message: `Scheduled task skipped: ${payload.reason}`,
        },
      });
      break;
    }

    case "task_healing": {
      const payload = data as unknown as TaskHealingPayload;
      messagesStore.addEvent({
        type: "task_healing",
        data: payload,
      });
      break;
    }

    // Help request broadcasts
    case "help_request_responded": {
      const payload =
        data as unknown as HelpRequestRespondedPayload;
      useHelpRequestsStore
        .getState()
        .updateRequestStatus(
          payload.request_id,
          "responded",
          payload.source
        );
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "help_response",
        data: payload,
      });
      break;
    }

    case "help_request_timeout": {
      const payload =
        data as unknown as HelpRequestTimeoutPayload;
      useHelpRequestsStore
        .getState()
        .updateRequestStatus(payload.request_id, "timeout");
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: { message: "Help request timed out" },
      });
      break;
    }

    case "help_request_dismissed": {
      const payload =
        data as unknown as HelpRequestRespondedPayload;
      useHelpRequestsStore
        .getState()
        .updateRequestStatus(
          payload.request_id,
          "cancelled",
          payload.source
        );
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `Help request dismissed via ${payload.source}`,
        },
      });
      break;
    }

    // Task assignment is handled via JetStream (handleTaskEvent "assigned")
    // so we skip the broadcast duplicate here

    // Help request broadcast
    case "help_request": {
      const payload = data as unknown as HelpRequestCreatedPayload;
      useHelpRequestsStore.getState().addRequest({
        request_id: payload.request_id,
        worker_id: payload.worker_id,
        task_id: payload.task_id,
        questions: payload.questions,
        context: payload.context,
        created_at: payload.created_at,
        timeout_seconds: payload.timeout_seconds,
        status: "pending",
      });
      const helpQuestionText = payload.questions?.[0]?.question
        ? `: ${payload.questions[0].question}`
        : "";
      messagesStore.addEvent({
        worker_id: payload.worker_id,
        type: "system",
        data: {
          message: `Worker ${payload.worker_id} needs help${helpQuestionText}`,
        },
      });
      break;
    }

    // Supervisor broadcasts
    case "supervisor_error": {
      const payload = data as unknown as ErrorPayload & {
        supervisor_id: string;
      };
      messagesStore.addEvent({
        supervisor_id: payload.supervisor_id,
        type: "supervisor_error",
        data: payload,
      });
      break;
    }

    case "supervisor_task_complete": {
      const payload = data as unknown as TaskCompletePayload & {
        supervisor_id: string;
      };
      useTasksStore.getState().removeTask(payload.task_id);
      supervisorsStore.updateSupervisorStatus(
        payload.supervisor_id,
        "idle"
      );
      messagesStore.addEvent({
        supervisor_id: payload.supervisor_id,
        type: "supervisor_task_complete",
        data: payload,
      });
      break;
    }

    // These are handled via JetStream (handleTaskEvent), skip broadcast duplicates
    case "task_assigned":
    case "task_message":
    case "task_error":
    case "task_submitted_to_supervisor":
      break;

    default:
      console.log("Unknown broadcast event:", eventType, data);
  }
}
