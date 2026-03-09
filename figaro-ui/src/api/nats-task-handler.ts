import type {
  TaskAssignedPayload,
  TaskCompletePayload,
  ErrorPayload,
  SDKMessage,
} from "../types";
import { useWorkersStore } from "../stores/workers";
import { useSupervisorsStore } from "../stores/supervisors";
import { useMessagesStore } from "../stores/messages";
import { useTasksStore } from "../stores/tasks";

export function handleTaskEvent(
  eventType: string,
  data: unknown
): void {
  const messagesStore = useMessagesStore.getState();
  const workersStore = useWorkersStore.getState();
  const supervisorsStore = useSupervisorsStore.getState();

  switch (eventType) {
    case "assigned": {
      const payload = data as unknown as TaskAssignedPayload & {
        supervisor_id?: string;
      };
      if (payload.supervisor_id) {
        supervisorsStore.updateSupervisorStatus(
          payload.supervisor_id,
          "busy"
        );
        messagesStore.addEvent({
          supervisor_id: payload.supervisor_id,
          type: "task_submitted_to_supervisor",
          data: payload,
        });
        useTasksStore.getState().addTask({
          task_id: payload.task_id,
          prompt: payload.prompt,
          status: "assigned",
          agent_id: payload.supervisor_id,
          agent_type: "supervisor",
          assigned_at: new Date().toISOString(),
          options: {},
          cost_usd: 0,
          input_tokens: 0,
          output_tokens: 0,
        });
      } else if (payload.worker_id) {
        workersStore.updateWorkerStatus(payload.worker_id, "busy");
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "task_assigned",
          data: payload,
        });
        useTasksStore.getState().addTask({
          task_id: payload.task_id,
          prompt: payload.prompt,
          status: "assigned",
          agent_id: payload.worker_id,
          agent_type: "worker",
          assigned_at: new Date().toISOString(),
          options: {},
          cost_usd: 0,
          input_tokens: 0,
          output_tokens: 0,
        });
      }
      break;
    }

    case "message": {
      const sdkMessage = data as unknown as SDKMessage;
      if (sdkMessage.supervisor_id) {
        messagesStore.addEvent({
          supervisor_id: sdkMessage.supervisor_id,
          type: "supervisor_message",
          data: sdkMessage,
        });
      } else {
        messagesStore.addSDKMessage(sdkMessage);
      }

      // Extract cost data from the SDK message
      const taskId = sdkMessage.task_id;
      if (taskId) {
        if (sdkMessage.total_cost_usd !== undefined) {
          useTasksStore.getState().updateTaskCost(taskId, sdkMessage.total_cost_usd);
        }
        if (sdkMessage.usage && sdkMessage.__type__ === 'AssistantMessage') {
          useTasksStore.getState().updateTaskCost(
            taskId,
            undefined,
            sdkMessage.usage.input_tokens,
            sdkMessage.usage.output_tokens,
            sdkMessage.message_id
          );
        }
      }
      break;
    }

    case "complete": {
      const payload = data as unknown as TaskCompletePayload & {
        supervisor_id?: string;
      };
      useTasksStore.getState().removeTask(payload.task_id);
      if (payload.supervisor_id) {
        supervisorsStore.updateSupervisorStatus(
          payload.supervisor_id,
          "idle"
        );
        messagesStore.addEvent({
          supervisor_id: payload.supervisor_id,
          type: "supervisor_task_complete",
          data: payload,
        });
      } else if (payload.worker_id) {
        workersStore.updateWorkerStatus(
          payload.worker_id,
          "idle"
        );
        messagesStore.addEvent({
          worker_id: payload.worker_id,
          type: "task_complete",
          data: payload,
        });
      }
      break;
    }

    case "error": {
      const payload = data as unknown as ErrorPayload;
      useTasksStore.getState().removeTask(payload.task_id);
      messagesStore.addEvent({
        type: "error",
        data: payload,
      });
      break;
    }

    default:
      console.log("Unknown task event:", eventType, data);
  }
}
