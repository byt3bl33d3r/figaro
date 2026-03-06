import { create } from 'zustand';
import type { ActiveTask, TaskStatus } from '../types';

interface AgentStats {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

interface TasksState {
  tasks: Map<string, ActiveTask>;
  seenMessageIds: Record<string, Set<string>>;
  agentLifetimeStats: Map<string, AgentStats>;

  // Actions
  setTasks: (tasks: ActiveTask[]) => void;
  addTask: (task: ActiveTask) => void;
  removeTask: (taskId: string) => void;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  updateTaskCost: (taskId: string, costUsd?: number, inputTokens?: number, outputTokens?: number, messageId?: string) => void;
  clearTasks: () => void;

  // Selectors
  getTasksByAgentId: (agentId: string) => ActiveTask[];
  getAgentTotalStats: (agentId: string) => AgentStats;
}

export const useTasksStore = create<TasksState>((set, get) => ({
  tasks: new Map(),
  seenMessageIds: {},
  agentLifetimeStats: new Map(),

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
      const task = state.tasks.get(taskId);
      const newTasks = new Map(state.tasks);
      newTasks.delete(taskId);
      const newSeenMessageIds = { ...state.seenMessageIds };
      delete newSeenMessageIds[taskId];

      // Accumulate stats into agent lifetime totals
      const newLifetimeStats = new Map(state.agentLifetimeStats);
      if (task) {
        const existing = newLifetimeStats.get(task.agent_id) ?? { cost_usd: 0, input_tokens: 0, output_tokens: 0 };
        newLifetimeStats.set(task.agent_id, {
          cost_usd: existing.cost_usd + task.cost_usd,
          input_tokens: existing.input_tokens + task.input_tokens,
          output_tokens: existing.output_tokens + task.output_tokens,
        });
      }

      return { tasks: newTasks, seenMessageIds: newSeenMessageIds, agentLifetimeStats: newLifetimeStats };
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

  updateTaskCost: (taskId, costUsd, inputTokens, outputTokens, messageId) => {
    set((state) => {
      const task = state.tasks.get(taskId);
      if (!task) return state;

      const updatedTask = { ...task };
      const newSeenMessageIds = { ...state.seenMessageIds };

      if (costUsd !== undefined) {
        updatedTask.cost_usd = costUsd;
      }

      if (inputTokens !== undefined || outputTokens !== undefined) {
        if (messageId) {
          if (!newSeenMessageIds[taskId]) {
            newSeenMessageIds[taskId] = new Set();
          }
          if (newSeenMessageIds[taskId].has(messageId)) {
            return state;
          }
          newSeenMessageIds[taskId] = new Set(newSeenMessageIds[taskId]);
          newSeenMessageIds[taskId].add(messageId);
        }
        updatedTask.input_tokens += (inputTokens ?? 0);
        updatedTask.output_tokens += (outputTokens ?? 0);
      }

      const newTasks = new Map(state.tasks);
      newTasks.set(taskId, updatedTask);
      return { tasks: newTasks, seenMessageIds: newSeenMessageIds };
    });
  },

  clearTasks: () => {
    set({ tasks: new Map(), seenMessageIds: {} });
  },

  getTasksByAgentId: (agentId) => {
    return Array.from(get().tasks.values()).filter((t) => t.agent_id === agentId);
  },

  getAgentTotalStats: (agentId) => {
    const lifetime = get().agentLifetimeStats.get(agentId) ?? { cost_usd: 0, input_tokens: 0, output_tokens: 0 };
    const activeTasks = Array.from(get().tasks.values()).filter((t) => t.agent_id === agentId);
    return {
      cost_usd: lifetime.cost_usd + activeTasks.reduce((sum, t) => sum + t.cost_usd, 0),
      input_tokens: lifetime.input_tokens + activeTasks.reduce((sum, t) => sum + t.input_tokens, 0),
      output_tokens: lifetime.output_tokens + activeTasks.reduce((sum, t) => sum + t.output_tokens, 0),
    };
  },
}));
