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

  describe('setTasks', () => {
    it('should set tasks from array', () => {
      const tasks = [createTask('task-1'), createTask('task-2')];
      useTasksStore.getState().setTasks(tasks);

      const state = useTasksStore.getState();
      expect(state.tasks.size).toBe(2);
      expect(state.tasks.get('task-1')).toEqual(tasks[0]);
      expect(state.tasks.get('task-2')).toEqual(tasks[1]);
    });

    it('should replace existing tasks', () => {
      useTasksStore.getState().setTasks([createTask('task-1')]);
      useTasksStore.getState().setTasks([createTask('task-3')]);

      const state = useTasksStore.getState();
      expect(state.tasks.size).toBe(1);
      expect(state.tasks.has('task-1')).toBe(false);
      expect(state.tasks.has('task-3')).toBe(true);
    });
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

  describe('updateTaskStatus', () => {
    it('should update task status', () => {
      useTasksStore.getState().addTask(createTask('task-1'));
      useTasksStore.getState().updateTaskStatus('task-1', 'running');

      expect(useTasksStore.getState().tasks.get('task-1')?.status).toBe('running');
    });

    it('should not modify state for nonexistent task', () => {
      useTasksStore.getState().addTask(createTask('task-1'));
      useTasksStore.getState().updateTaskStatus('nonexistent', 'running');

      expect(useTasksStore.getState().tasks.size).toBe(1);
      expect(useTasksStore.getState().tasks.get('task-1')?.status).toBe('assigned');
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
