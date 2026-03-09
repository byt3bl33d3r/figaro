import { describe, it, expect, beforeEach } from 'vitest';
import { useScheduledTasksStore } from '../../src/stores/scheduledTasks';
import type { ScheduledTask } from '../../src/types';

describe('useScheduledTasksStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useScheduledTasksStore.setState({
      tasks: new Map(),
    });
  });

  const createTask = (
    id: string,
    overrides: Partial<ScheduledTask> = {}
  ): ScheduledTask => ({
    schedule_id: id,
    name: `Task ${id}`,
    prompt: `Prompt for ${id}`,
    start_url: `https://example${id}.com`,
    interval_seconds: 3600,
    enabled: true,
    created_at: '2024-01-01T00:00:00Z',
    last_run_at: null,
    next_run_at: '2024-01-01T01:00:00Z',
    run_at: null,
    run_count: 0,
    options: {},
    parallel_workers: 1,
    max_runs: null,
    notify_on_complete: false,
    self_learning: false,
    self_healing: false,
    self_learning_max_runs: null,
    self_learning_run_count: 0,
    ...overrides,
  });

  describe('setTasks', () => {
    it('should set tasks from array', () => {
      const tasks = [createTask('1'), createTask('2')];

      useScheduledTasksStore.getState().setTasks(tasks);

      const state = useScheduledTasksStore.getState();
      expect(state.tasks.size).toBe(2);
      expect(state.tasks.get('1')).toEqual(tasks[0]);
      expect(state.tasks.get('2')).toEqual(tasks[1]);
    });

    it('should replace existing tasks', () => {
      const initialTasks = [createTask('1')];
      useScheduledTasksStore.getState().setTasks(initialTasks);

      const newTasks = [createTask('3')];
      useScheduledTasksStore.getState().setTasks(newTasks);

      const state = useScheduledTasksStore.getState();
      expect(state.tasks.size).toBe(1);
      expect(state.tasks.has('1')).toBe(false);
      expect(state.tasks.has('3')).toBe(true);
    });

    it('should handle empty array', () => {
      useScheduledTasksStore.getState().setTasks([createTask('1')]);
      useScheduledTasksStore.getState().setTasks([]);

      expect(useScheduledTasksStore.getState().tasks.size).toBe(0);
    });
  });

  describe('addTask', () => {
    it('should add a new task', () => {
      const task = createTask('1');

      useScheduledTasksStore.getState().addTask(task);

      expect(useScheduledTasksStore.getState().tasks.get('1')).toEqual(task);
    });

    it('should overwrite existing task with same id', () => {
      const task1 = createTask('1', { name: 'Original' });
      useScheduledTasksStore.getState().addTask(task1);

      const task2 = createTask('1', { name: 'Updated' });
      useScheduledTasksStore.getState().addTask(task2);

      expect(useScheduledTasksStore.getState().tasks.get('1')?.name).toBe('Updated');
      expect(useScheduledTasksStore.getState().tasks.size).toBe(1);
    });
  });

  describe('updateTask', () => {
    it('should update an existing task', () => {
      const task = createTask('1', { name: 'Original' });
      useScheduledTasksStore.getState().addTask(task);

      const updatedTask = { ...task, name: 'Updated', run_count: 5 };
      useScheduledTasksStore.getState().updateTask(updatedTask);

      const result = useScheduledTasksStore.getState().tasks.get('1');
      expect(result?.name).toBe('Updated');
      expect(result?.run_count).toBe(5);
    });

    it('should add task if it does not exist', () => {
      const task = createTask('1');
      useScheduledTasksStore.getState().updateTask(task);

      expect(useScheduledTasksStore.getState().tasks.get('1')).toEqual(task);
    });
  });

  describe('removeTask', () => {
    it('should remove a task', () => {
      useScheduledTasksStore.getState().addTask(createTask('1'));
      useScheduledTasksStore.getState().addTask(createTask('2'));

      useScheduledTasksStore.getState().removeTask('1');

      expect(useScheduledTasksStore.getState().tasks.has('1')).toBe(false);
      expect(useScheduledTasksStore.getState().tasks.has('2')).toBe(true);
    });

    it('should do nothing if task does not exist', () => {
      useScheduledTasksStore.getState().addTask(createTask('1'));

      useScheduledTasksStore.getState().removeTask('nonexistent');

      expect(useScheduledTasksStore.getState().tasks.size).toBe(1);
    });
  });

  describe('getTasksList', () => {
    it('should return all tasks as array', () => {
      const tasks = [createTask('1'), createTask('2'), createTask('3')];
      useScheduledTasksStore.getState().setTasks(tasks);

      const list = useScheduledTasksStore.getState().getTasksList();

      expect(list).toHaveLength(3);
      expect(list.map((t) => t.schedule_id).sort()).toEqual(['1', '2', '3']);
    });

    it('should return empty array when no tasks', () => {
      expect(useScheduledTasksStore.getState().getTasksList()).toEqual([]);
    });
  });

  describe('integration scenarios', () => {
    it('should handle task lifecycle: create, update, toggle, delete', () => {
      // Create
      const task = createTask('1', { run_count: 0 });
      useScheduledTasksStore.getState().addTask(task);
      expect(useScheduledTasksStore.getState().tasks.size).toBe(1);

      // Update after execution
      const executed = { ...task, run_count: 1, last_run_at: '2024-01-01T01:00:00Z' };
      useScheduledTasksStore.getState().updateTask(executed);
      expect(useScheduledTasksStore.getState().tasks.get('1')?.run_count).toBe(1);

      // Toggle disabled
      const disabled = { ...executed, enabled: false };
      useScheduledTasksStore.getState().updateTask(disabled);
      expect(useScheduledTasksStore.getState().getTasksList().filter(t => t.enabled)).toHaveLength(0);

      // Delete
      useScheduledTasksStore.getState().removeTask('1');
      expect(useScheduledTasksStore.getState().tasks.size).toBe(0);
    });

    it('should handle bulk operations', () => {
      // Add multiple tasks
      const tasks = Array.from({ length: 10 }, (_, i) => createTask(String(i), { enabled: i % 2 === 0 }));
      useScheduledTasksStore.getState().setTasks(tasks);

      expect(useScheduledTasksStore.getState().getTasksList()).toHaveLength(10);
      expect(useScheduledTasksStore.getState().getTasksList().filter(t => t.enabled)).toHaveLength(5);

      // Clear all
      useScheduledTasksStore.getState().setTasks([]);
      expect(useScheduledTasksStore.getState().tasks.size).toBe(0);
    });
  });
});
