import { create } from 'zustand';
import type { ScheduledTask } from '../types';

interface ScheduledTasksState {
  tasks: Map<string, ScheduledTask>;
  isLoading: boolean;
  error: string | null;

  // Actions
  setTasks: (tasks: ScheduledTask[]) => void;
  addTask: (task: ScheduledTask) => void;
  updateTask: (task: ScheduledTask) => void;
  removeTask: (scheduleId: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  // Selectors
  getTasksList: () => ScheduledTask[];
  getTask: (scheduleId: string) => ScheduledTask | undefined;
  getEnabledTasks: () => ScheduledTask[];
}

export const useScheduledTasksStore = create<ScheduledTasksState>((set, get) => ({
  tasks: new Map(),
  isLoading: false,
  error: null,

  setTasks: (tasks) => {
    const tasksMap = new Map(tasks.map((t) => [t.schedule_id, t]));
    set({ tasks: tasksMap });
  },

  addTask: (task) => {
    set((state) => {
      const newTasks = new Map(state.tasks);
      newTasks.set(task.schedule_id, task);
      return { tasks: newTasks };
    });
  },

  updateTask: (task) => {
    set((state) => {
      const newTasks = new Map(state.tasks);
      newTasks.set(task.schedule_id, task);
      return { tasks: newTasks };
    });
  },

  removeTask: (scheduleId) => {
    set((state) => {
      const newTasks = new Map(state.tasks);
      newTasks.delete(scheduleId);
      return { tasks: newTasks };
    });
  },

  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),

  getTasksList: () => Array.from(get().tasks.values()),
  getTask: (scheduleId) => get().tasks.get(scheduleId),
  getEnabledTasks: () => Array.from(get().tasks.values()).filter((t) => t.enabled),
}));
