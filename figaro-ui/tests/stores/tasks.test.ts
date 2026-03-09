import { describe, it, expect, beforeEach } from 'vitest';
import { useTasksStore } from '../../src/stores/tasks';
import type { ActiveTask } from '../../src/types';

describe('useTasksStore', () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: new Map() });
  });

  const createTask = (
    id: string,
    agentId = 'worker-1',
    agentType: 'worker' | 'supervisor' = 'worker',
  ): ActiveTask => ({
    task_id: id,
    prompt: `Do task ${id}`,
    status: 'assigned',
    agent_id: agentId,
    agent_type: agentType,
    assigned_at: new Date().toISOString(),
    options: {},
    cost_usd: 0,
    input_tokens: 0,
    output_tokens: 0,
  });

  describe('addTask', () => {
    it('should add a new task', () => {
      const task = createTask('task-1');
      useTasksStore.getState().addTask(task);

      expect(useTasksStore.getState().tasks.get('task-1')).toEqual(task);
    });

    it('should overwrite existing task with same id', () => {
      const task1 = createTask('task-1');
      useTasksStore.getState().addTask(task1);

      const task1Updated = { ...task1, prompt: 'Updated prompt' };
      useTasksStore.getState().addTask(task1Updated);

      expect(useTasksStore.getState().tasks.size).toBe(1);
      expect(useTasksStore.getState().tasks.get('task-1')?.prompt).toBe('Updated prompt');
    });
  });

  describe('removeTask', () => {
    it('should remove a task', () => {
      useTasksStore.getState().addTask(createTask('task-1'));
      useTasksStore.getState().removeTask('task-1');

      expect(useTasksStore.getState().tasks.has('task-1')).toBe(false);
    });

    it('should not fail when removing nonexistent task', () => {
      useTasksStore.getState().addTask(createTask('task-1'));
      useTasksStore.getState().removeTask('nonexistent');

      expect(useTasksStore.getState().tasks.size).toBe(1);
    });
  });

  describe('clearTasks', () => {
    it('should remove all tasks', () => {
      useTasksStore.getState().addTask(createTask('task-1'));
      useTasksStore.getState().addTask(createTask('task-2'));
      useTasksStore.getState().clearTasks();

      expect(useTasksStore.getState().tasks.size).toBe(0);
    });
  });

  describe('getTasksByAgentId', () => {
    it('should return tasks for a specific agent', () => {
      useTasksStore.getState().addTask(createTask('task-1', 'worker-1'));
      useTasksStore.getState().addTask(createTask('task-2', 'worker-2'));
      useTasksStore.getState().addTask(createTask('task-3', 'worker-1'));

      const tasks = useTasksStore.getState().getTasksByAgentId('worker-1');
      expect(tasks).toHaveLength(2);
      expect(tasks.map((t) => t.task_id).sort()).toEqual(['task-1', 'task-3']);
    });

    it('should return empty array for agent with no tasks', () => {
      useTasksStore.getState().addTask(createTask('task-1', 'worker-1'));

      expect(useTasksStore.getState().getTasksByAgentId('worker-99')).toEqual([]);
    });

    it('should return empty array when no tasks exist', () => {
      expect(useTasksStore.getState().getTasksByAgentId('worker-1')).toEqual([]);
    });
  });
});
