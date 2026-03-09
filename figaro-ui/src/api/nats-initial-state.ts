import type {
  WorkersPayload,
  SupervisorsPayload,
  ScheduledTask,
  HelpRequestCreatedPayload,
} from "../types";
import { useWorkersStore } from "../stores/workers";
import { useSupervisorsStore } from "../stores/supervisors";
import { useScheduledTasksStore } from "../stores/scheduledTasks";
import { useHelpRequestsStore } from "../stores/helpRequests";

export async function fetchInitialState(
  request: <T = unknown>(subject: string, data?: unknown) => Promise<T>
): Promise<void> {
  try {
    const [workersResp, supervisorsResp, helpRequestsResp, scheduledTasksResp] =
      await Promise.all([
        request<WorkersPayload>("figaro.api.workers", {}),
        request<SupervisorsPayload>(
          "figaro.api.supervisor.status",
          {}
        ),
        request<{ requests: HelpRequestCreatedPayload[] }>(
          "figaro.api.help-requests.list",
          {}
        ).catch(() => null),
        request<{ tasks: ScheduledTask[] }>(
          "figaro.api.scheduled-tasks",
          {}
        ).catch(() => null),
      ]);

    if (workersResp?.workers) {
      useWorkersStore.getState().setWorkers(workersResp.workers);
    }
    if (supervisorsResp?.supervisors) {
      useSupervisorsStore
        .getState()
        .setSupervisors(supervisorsResp.supervisors);
    }
    if (helpRequestsResp?.requests) {
      for (const req of helpRequestsResp.requests) {
        useHelpRequestsStore.getState().addRequest({
          request_id: req.request_id,
          worker_id: req.worker_id,
          task_id: req.task_id,
          questions: req.questions,
          context: req.context,
          created_at: req.created_at,
          timeout_seconds: req.timeout_seconds,
          status: req.status || "pending",
        });
      }
    }
    if (scheduledTasksResp?.tasks) {
      useScheduledTasksStore.getState().setTasks(scheduledTasksResp.tasks);
    }
  } catch (err) {
    console.warn("Failed to fetch initial state:", err);
  }
}
