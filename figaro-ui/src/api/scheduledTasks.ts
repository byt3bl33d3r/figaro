import type { ScheduledTask, ScheduledTaskCreate, ScheduledTaskUpdate } from '../types';
import { natsManager } from './nats';

export async function fetchScheduledTasks(): Promise<ScheduledTask[]> {
  const resp = await natsManager.request<{ tasks: ScheduledTask[] }>('figaro.api.scheduled-tasks');
  return resp.tasks ?? [];
}

export async function getScheduledTask(scheduleId: string): Promise<ScheduledTask> {
  return natsManager.request<ScheduledTask>('figaro.api.scheduled-tasks.get', {
    schedule_id: scheduleId,
  });
}

export async function createScheduledTask(data: ScheduledTaskCreate): Promise<ScheduledTask> {
  return natsManager.request<ScheduledTask>('figaro.api.scheduled-tasks.create', data);
}

export async function updateScheduledTask(
  scheduleId: string,
  data: ScheduledTaskUpdate
): Promise<ScheduledTask> {
  return natsManager.request<ScheduledTask>('figaro.api.scheduled-tasks.update', {
    schedule_id: scheduleId,
    ...data,
  });
}

export async function deleteScheduledTask(scheduleId: string): Promise<void> {
  await natsManager.request('figaro.api.scheduled-tasks.delete', {
    schedule_id: scheduleId,
  });
}

export async function toggleScheduledTask(scheduleId: string): Promise<ScheduledTask> {
  return natsManager.request<ScheduledTask>('figaro.api.scheduled-tasks.toggle', {
    schedule_id: scheduleId,
  });
}

export async function triggerScheduledTask(scheduleId: string): Promise<{ schedule_id: string; triggered: boolean }> {
  return natsManager.request('figaro.api.scheduled-tasks.trigger', {
    schedule_id: scheduleId,
  });
}
