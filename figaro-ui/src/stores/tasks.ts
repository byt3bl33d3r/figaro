import { create } from 'zustand';
import type { ActiveTask, TaskStatus } from '../types';

interface TasksState {
  tasks: Map<string, ActiveTask>;

  // Actions
  setTasks: (tasks: ActiveTask[]) => void;
  addTask: (task: ActiveTask) => void;
  removeTask: (taskId: string) => void;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  clearTasks: () => void;

  // Selectors
  getTasksByAgentId: (agentId: string) => ActiveTask[];
}

export const useTasksStore = create<TasksState>((set, get) => ({
  tasks: new Map(),

  setTasks: (tasks) => {
    const tasksMap = new Map(tasks.map((t) => [t.task_id, t]));
    set({ tasks: tasksMap });
  },

  addTask: (task) => {
    set((state) => {
      const newTasks = new Map(state.tasks);
      newTasks.set(task.task_id, task);
      return { tasks: newTasks };
    });
  },

  removeTask: (taskId) => {
    set((state) => {
      const newTasks = new Map(state.tasks);
      newTasks.delete(taskId);
      return { tasks: newTasks };
    });
  },

  updateTaskStatus: (taskId, status) => {
    set((state) => {
      const task = state.tasks.get(taskId);
      if (!task) return state;
      const newTasks = new Map(state.tasks);
      newTasks.set(taskId, { ...task, status });
      return { tasks: newTasks };
    });
  },

  clearTasks: () => {
    set({ tasks: new Map() });
  },

  getTasksByAgentId: (agentId) => {
    return Array.from(get().tasks.values()).filter((t) => t.agent_id === agentId);
  },
}));
