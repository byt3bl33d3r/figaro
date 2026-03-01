import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  fetchScheduledTasks,
  getScheduledTask,
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  toggleScheduledTask,
  triggerScheduledTask,
} from '../../src/api/scheduledTasks';
import type { ScheduledTask, ScheduledTaskCreate, ScheduledTaskUpdate } from '../../src/types';
import { natsManager } from '../../src/api/nats';

// Mock the natsManager.request method
vi.spyOn(natsManager, 'request');

const mockRequest = vi.mocked(natsManager.request);

describe('scheduledTasks API', () => {
  beforeEach(() => {
    mockRequest.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const createMockTask = (id: string = '1'): ScheduledTask => ({
    schedule_id: id,
    name: `Task ${id}`,
    prompt: 'Test prompt',
    start_url: 'https://example.com',
    interval_seconds: 3600,
    enabled: true,
    created_at: '2024-01-01T00:00:00Z',
    last_run_at: null,
    next_run_at: '2024-01-01T01:00:00Z',
    run_count: 0,
  });

  describe('fetchScheduledTasks', () => {
    it('should fetch all scheduled tasks', async () => {
      const tasks = [createMockTask('1'), createMockTask('2')];
      mockRequest.mockResolvedValueOnce({ tasks });

      const result = await fetchScheduledTasks();

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks');
      expect(result).toEqual(tasks);
    });

    it('should throw error on failed request', async () => {
      mockRequest.mockRejectedValueOnce(new Error('NATS request failed'));

      await expect(fetchScheduledTasks()).rejects.toThrow('NATS request failed');
    });
  });

  describe('getScheduledTask', () => {
    it('should fetch a single scheduled task', async () => {
      const task = createMockTask('1');
      mockRequest.mockResolvedValueOnce(task);

      const result = await getScheduledTask('1');

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.get', {
        schedule_id: '1',
      });
      expect(result).toEqual(task);
    });

    it('should throw error on not found', async () => {
      mockRequest.mockRejectedValueOnce(new Error('Not found'));

      await expect(getScheduledTask('nonexistent')).rejects.toThrow('Not found');
    });
  });

  describe('createScheduledTask', () => {
    it('should create a new scheduled task', async () => {
      const createData: ScheduledTaskCreate = {
        name: 'New Task',
        prompt: 'Do something',
        start_url: 'https://example.com',
        interval_seconds: 1800,
      };
      const createdTask = createMockTask('new-id');
      mockRequest.mockResolvedValueOnce(createdTask);

      const result = await createScheduledTask(createData);

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.create', createData);
      expect(result).toEqual(createdTask);
    });

    it('should throw error on creation failure', async () => {
      const createData: ScheduledTaskCreate = {
        name: 'New Task',
        prompt: 'Do something',
        start_url: 'https://example.com',
        interval_seconds: 1800,
      };
      mockRequest.mockRejectedValueOnce(new Error('Creation failed'));

      await expect(createScheduledTask(createData)).rejects.toThrow('Creation failed');
    });
  });

  describe('updateScheduledTask', () => {
    it('should update an existing scheduled task', async () => {
      const updateData: ScheduledTaskUpdate = {
        name: 'Updated Name',
        interval_seconds: 7200,
      };
      const updatedTask = { ...createMockTask('1'), ...updateData };
      mockRequest.mockResolvedValueOnce(updatedTask);

      const result = await updateScheduledTask('1', updateData);

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.update', {
        schedule_id: '1',
        ...updateData,
      });
      expect(result).toEqual(updatedTask);
    });

    it('should throw error on update failure', async () => {
      mockRequest.mockRejectedValueOnce(new Error('Update failed'));

      await expect(updateScheduledTask('nonexistent', { name: 'New Name' })).rejects.toThrow(
        'Update failed'
      );
    });
  });

  describe('deleteScheduledTask', () => {
    it('should delete a scheduled task', async () => {
      mockRequest.mockResolvedValueOnce(undefined);

      await expect(deleteScheduledTask('1')).resolves.toBeUndefined();

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.delete', {
        schedule_id: '1',
      });
    });

    it('should throw error on deletion failure', async () => {
      mockRequest.mockRejectedValueOnce(new Error('Deletion failed'));

      await expect(deleteScheduledTask('nonexistent')).rejects.toThrow('Deletion failed');
    });
  });

  describe('toggleScheduledTask', () => {
    it('should toggle a scheduled task', async () => {
      const toggledTask = { ...createMockTask('1'), enabled: false };
      mockRequest.mockResolvedValueOnce(toggledTask);

      const result = await toggleScheduledTask('1');

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.toggle', {
        schedule_id: '1',
      });
      expect(result).toEqual(toggledTask);
      expect(result.enabled).toBe(false);
    });

    it('should throw error on toggle failure', async () => {
      mockRequest.mockRejectedValueOnce(new Error('Toggle failed'));

      await expect(toggleScheduledTask('nonexistent')).rejects.toThrow('Toggle failed');
    });
  });

  describe('triggerScheduledTask', () => {
    it('should trigger a scheduled task', async () => {
      const triggerResult = { schedule_id: '1', triggered: true };
      mockRequest.mockResolvedValueOnce(triggerResult);

      const result = await triggerScheduledTask('1');

      expect(mockRequest).toHaveBeenCalledWith('figaro.api.scheduled-tasks.trigger', {
        schedule_id: '1',
      });
      expect(result).toEqual(triggerResult);
      expect(result.triggered).toBe(true);
    });

    it('should throw error on trigger failure', async () => {
      mockRequest.mockRejectedValueOnce(new Error('Trigger failed'));

      await expect(triggerScheduledTask('nonexistent')).rejects.toThrow('Trigger failed');
    });
  });
});
