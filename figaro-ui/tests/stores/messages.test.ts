import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useMessagesStore } from '../../src/stores/messages';
import type { SDKMessage } from '../../src/types';

describe('useMessagesStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useMessagesStore.setState({
      events: [],
      filterWorkerId: null,
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('addEvent', () => {
    it('should add an event with id and timestamp', () => {
      const now = new Date('2024-01-15T10:00:00Z');
      vi.setSystemTime(now);

      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'status',
        data: { status: 'idle' },
      });

      const events = useMessagesStore.getState().events;
      expect(events).toHaveLength(1);
      expect(events[0].worker_id).toBe('worker-1');
      expect(events[0].type).toBe('status');
      expect(events[0].id).toMatch(/^event-\d+$/);
      expect(events[0].timestamp).toEqual(now);
    });

    it('should append events in order', () => {
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'status',
        data: { status: 'idle' },
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-2',
        type: 'status',
        data: { status: 'busy' },
      });

      const events = useMessagesStore.getState().events;
      expect(events).toHaveLength(2);
      expect(events[0].worker_id).toBe('worker-1');
      expect(events[1].worker_id).toBe('worker-2');
    });

    it('should trim events to MAX_EVENTS (1000)', () => {
      // Add 1005 events
      for (let i = 0; i < 1005; i++) {
        useMessagesStore.getState().addEvent({
          worker_id: `worker-${i}`,
          type: 'status',
          data: { index: i },
        });
      }

      const events = useMessagesStore.getState().events;
      expect(events).toHaveLength(1000);
      // Should have kept the most recent events (5-1004)
      expect((events[0].data as { index: number }).index).toBe(5);
      expect((events[999].data as { index: number }).index).toBe(1004);
    });
  });

  describe('addSDKMessage', () => {
    it('should add SDK message as event', () => {
      const message: SDKMessage = {
        task_id: 'task-123',
        worker_id: 'worker-1',
        __type__: 'AssistantMessage',
        content: 'Hello',
      };

      useMessagesStore.getState().addSDKMessage(message);

      const events = useMessagesStore.getState().events;
      expect(events).toHaveLength(1);
      expect(events[0].type).toBe('message');
      expect(events[0].worker_id).toBe('worker-1');
      expect(events[0].data).toEqual(message);
    });
  });

  describe('setFilterWorkerId', () => {
    it('should set filter worker id', () => {
      useMessagesStore.getState().setFilterWorkerId('worker-1');

      expect(useMessagesStore.getState().filterWorkerId).toBe('worker-1');
    });

    it('should clear filter with null', () => {
      useMessagesStore.getState().setFilterWorkerId('worker-1');
      useMessagesStore.getState().setFilterWorkerId(null);

      expect(useMessagesStore.getState().filterWorkerId).toBeNull();
    });
  });

  describe('clearEvents', () => {
    it('should clear all events', () => {
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'status',
        data: {},
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-2',
        type: 'status',
        data: {},
      });

      useMessagesStore.getState().clearEvents();

      expect(useMessagesStore.getState().events).toEqual([]);
    });
  });

  describe('getFilteredEvents', () => {
    beforeEach(() => {
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'status',
        data: { event: 1 },
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-2',
        type: 'status',
        data: { event: 2 },
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'message',
        data: { event: 3 },
      });
    });

    it('should return all events when no filter set', () => {
      const filtered = useMessagesStore.getState().getFilteredEvents();
      expect(filtered).toHaveLength(3);
    });

    it('should return only matching events when filter set', () => {
      useMessagesStore.getState().setFilterWorkerId('worker-1');

      const filtered = useMessagesStore.getState().getFilteredEvents();

      expect(filtered).toHaveLength(2);
      expect(filtered.every(e => e.worker_id === 'worker-1')).toBe(true);
    });

    it('should return empty array when filter matches no events', () => {
      useMessagesStore.getState().setFilterWorkerId('worker-999');

      expect(useMessagesStore.getState().getFilteredEvents()).toEqual([]);
    });
  });

  describe('getWorkerEvents', () => {
    beforeEach(() => {
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'status',
        data: { event: 1 },
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-2',
        type: 'status',
        data: { event: 2 },
      });
      useMessagesStore.getState().addEvent({
        worker_id: 'worker-1',
        type: 'message',
        data: { event: 3 },
      });
    });

    it('should return events for specific worker', () => {
      const events = useMessagesStore.getState().getWorkerEvents('worker-1');

      expect(events).toHaveLength(2);
      expect(events.every(e => e.worker_id === 'worker-1')).toBe(true);
    });

    it('should return empty array for worker with no events', () => {
      expect(useMessagesStore.getState().getWorkerEvents('worker-999')).toEqual([]);
    });
  });
});
