import { describe, it, expect, beforeEach } from 'vitest';
import { useScheduledTasksStore } from '../../src/stores/scheduledTasks';
import type { ScheduledTask } from '../../src/types';

describe('useScheduledTasksStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useScheduledTasksStore.setState({
      tasks: new Map(),
      isLoading: false,
      error: null,
    });
  });

  const createTask = (
    id: string,
    enabled: boolean = true,
    overrides: Partial<ScheduledTask> = {}
  ): ScheduledTask => ({
    schedule_id: id,
    name: `Task ${id}`,
    prompt: `Prompt for ${id}`,
    start_url: `https://example${id}.com`,
    interval_seconds: 3600,
    enabled,
    created_at: '2024-01-01T00:00:00Z',
    last_run_at: null,
    next_run_at: '2024-01-01T01:00:00Z',
    run_count: 0,
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
      const task1 = createTask('1', true, { name: 'Original' });
      useScheduledTasksStore.getState().addTask(task1);

      const task2 = createTask('1', true, { name: 'Updated' });
      useScheduledTasksStore.getState().addTask(task2);

      expect(useScheduledTasksStore.getState().tasks.get('1')?.name).toBe('Updated');
      expect(useScheduledTasksStore.getState().tasks.size).toBe(1);
    });
  });

  describe('updateTask', () => {
    it('should update an existing task', () => {
      const task = createTask('1', true, { name: 'Original' });
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

  describe('setLoading', () => {
    it('should set loading state to true', () => {
      useScheduledTasksStore.getState().setLoading(true);
      expect(useScheduledTasksStore.getState().isLoading).toBe(true);
    });

    it('should set loading state to false', () => {
      useScheduledTasksStore.getState().setLoading(true);
      useScheduledTasksStore.getState().setLoading(false);
      expect(useScheduledTasksStore.getState().isLoading).toBe(false);
    });
  });

  describe('setError', () => {
    it('should set error message', () => {
      useScheduledTasksStore.getState().setError('Something went wrong');
      expect(useScheduledTasksStore.getState().error).toBe('Something went wrong');
    });

    it('should clear error with null', () => {
      useScheduledTasksStore.getState().setError('Error');
      useScheduledTasksStore.getState().setError(null);
      expect(useScheduledTasksStore.getState().error).toBeNull();
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

  describe('getTask', () => {
    it('should return task by id', () => {
      const task = createTask('1');
      useScheduledTasksStore.getState().addTask(task);

      expect(useScheduledTasksStore.getState().getTask('1')).toEqual(task);
    });

    it('should return undefined for nonexistent task', () => {
      expect(useScheduledTasksStore.getState().getTask('nonexistent')).toBeUndefined();
    });
  });

  describe('getEnabledTasks', () => {
    it('should return only enabled tasks', () => {
      useScheduledTasksStore.getState().setTasks([
        createTask('1', true),
        createTask('2', false),
        createTask('3', true),
        createTask('4', false),
      ]);

      const enabledTasks = useScheduledTasksStore.getState().getEnabledTasks();

      expect(enabledTasks).toHaveLength(2);
      expect(enabledTasks.map((t) => t.schedule_id).sort()).toEqual(['1', '3']);
    });

    it('should return empty array when no enabled tasks', () => {
      useScheduledTasksStore.getState().setTasks([
        createTask('1', false),
        createTask('2', false),
      ]);

      expect(useScheduledTasksStore.getState().getEnabledTasks()).toEqual([]);
    });

    it('should return empty array when no tasks', () => {
      expect(useScheduledTasksStore.getState().getEnabledTasks()).toEqual([]);
    });
  });

  describe('integration scenarios', () => {
    it('should handle task lifecycle: create, update, toggle, delete', () => {
      // Create
      const task = createTask('1', true, { run_count: 0 });
      useScheduledTasksStore.getState().addTask(task);
      expect(useScheduledTasksStore.getState().tasks.size).toBe(1);

      // Update after execution
      const executed = { ...task, run_count: 1, last_run_at: '2024-01-01T01:00:00Z' };
      useScheduledTasksStore.getState().updateTask(executed);
      expect(useScheduledTasksStore.getState().getTask('1')?.run_count).toBe(1);

      // Toggle disabled
      const disabled = { ...executed, enabled: false };
      useScheduledTasksStore.getState().updateTask(disabled);
      expect(useScheduledTasksStore.getState().getEnabledTasks()).toHaveLength(0);

      // Delete
      useScheduledTasksStore.getState().removeTask('1');
      expect(useScheduledTasksStore.getState().tasks.size).toBe(0);
    });

    it('should handle bulk operations', () => {
      // Add multiple tasks
      const tasks = Array.from({ length: 10 }, (_, i) => createTask(String(i), i % 2 === 0));
      useScheduledTasksStore.getState().setTasks(tasks);

      expect(useScheduledTasksStore.getState().getTasksList()).toHaveLength(10);
      expect(useScheduledTasksStore.getState().getEnabledTasks()).toHaveLength(5);

      // Clear all
      useScheduledTasksStore.getState().setTasks([]);
      expect(useScheduledTasksStore.getState().tasks.size).toBe(0);
    });
  });
});
