import { create } from 'zustand';
import type { ScheduledTask } from '../types';

interface ScheduledTasksState {
  tasks: Map<string, ScheduledTask>;

  // Actions
  setTasks: (tasks: ScheduledTask[]) => void;
  addTask: (task: ScheduledTask) => void;
  updateTask: (task: ScheduledTask) => void;
  removeTask: (scheduleId: string) => void;

  // Selectors
  getTasksList: () => ScheduledTask[];
}

export const useScheduledTasksStore = create<ScheduledTasksState>((set, get) => ({
  tasks: new Map(),

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

  getTasksList: () => Array.from(get().tasks.values()),
}));
