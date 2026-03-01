import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkersStore } from '../../src/stores/workers';
import type { Worker } from '../../src/types';

describe('useWorkersStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useWorkersStore.setState({
      workers: new Map(),
      selectedWorkerId: null,
    });
  });

  const createWorker = (id: string, status: 'idle' | 'busy' = 'idle', agent_connected = true): Worker => ({
    id,
    status,
    capabilities: ['browser'],
    novnc_url: `ws://localhost:${6080 + parseInt(id.replace('worker-', ''))}/websockify`,
    agent_connected,
  });

  describe('setWorkers', () => {
    it('should set workers from array', () => {
      const workers = [createWorker('worker-1'), createWorker('worker-2')];

      useWorkersStore.getState().setWorkers(workers);

      const state = useWorkersStore.getState();
      expect(state.workers.size).toBe(2);
      expect(state.workers.get('worker-1')).toEqual(workers[0]);
      expect(state.workers.get('worker-2')).toEqual(workers[1]);
    });

    it('should replace existing workers', () => {
      const initialWorkers = [createWorker('worker-1')];
      useWorkersStore.getState().setWorkers(initialWorkers);

      const newWorkers = [createWorker('worker-3')];
      useWorkersStore.getState().setWorkers(newWorkers);

      const state = useWorkersStore.getState();
      expect(state.workers.size).toBe(1);
      expect(state.workers.has('worker-1')).toBe(false);
      expect(state.workers.has('worker-3')).toBe(true);
    });
  });

  describe('updateWorker', () => {
    it('should add a new worker', () => {
      const worker = createWorker('worker-1');

      useWorkersStore.getState().updateWorker(worker);

      expect(useWorkersStore.getState().workers.get('worker-1')).toEqual(worker);
    });

    it('should update an existing worker', () => {
      const worker = createWorker('worker-1', 'idle');
      useWorkersStore.getState().updateWorker(worker);

      const updatedWorker = { ...worker, status: 'busy' as const };
      useWorkersStore.getState().updateWorker(updatedWorker);

      expect(useWorkersStore.getState().workers.get('worker-1')?.status).toBe('busy');
    });
  });

  describe('updateWorkerStatus', () => {
    it('should update worker status', () => {
      const worker = createWorker('worker-1', 'idle');
      useWorkersStore.getState().updateWorker(worker);

      useWorkersStore.getState().updateWorkerStatus('worker-1', 'busy');

      expect(useWorkersStore.getState().workers.get('worker-1')?.status).toBe('busy');
    });

    it('should not modify state if worker does not exist', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);

      useWorkersStore.getState().updateWorkerStatus('nonexistent', 'busy');

      expect(useWorkersStore.getState().workers.size).toBe(1);
      expect(useWorkersStore.getState().workers.get('worker-1')?.status).toBe('idle');
    });
  });

  describe('removeWorker', () => {
    it('should remove a worker', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);

      useWorkersStore.getState().removeWorker('worker-1');

      expect(useWorkersStore.getState().workers.has('worker-1')).toBe(false);
    });

    it('should clear selection if removed worker was selected', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);
      useWorkersStore.getState().selectWorker('worker-1');

      useWorkersStore.getState().removeWorker('worker-1');

      expect(useWorkersStore.getState().selectedWorkerId).toBeNull();
    });

    it('should not clear selection if a different worker was removed', () => {
      useWorkersStore.getState().updateWorker(createWorker('worker-1'));
      useWorkersStore.getState().updateWorker(createWorker('worker-2'));
      useWorkersStore.getState().selectWorker('worker-1');

      useWorkersStore.getState().removeWorker('worker-2');

      expect(useWorkersStore.getState().selectedWorkerId).toBe('worker-1');
    });
  });

  describe('selectWorker', () => {
    it('should select a worker', () => {
      useWorkersStore.getState().selectWorker('worker-1');

      expect(useWorkersStore.getState().selectedWorkerId).toBe('worker-1');
    });

    it('should clear selection with null', () => {
      useWorkersStore.getState().selectWorker('worker-1');
      useWorkersStore.getState().selectWorker(null);

      expect(useWorkersStore.getState().selectedWorkerId).toBeNull();
    });
  });

  describe('getWorker', () => {
    it('should return a worker by id', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);

      expect(useWorkersStore.getState().getWorker('worker-1')).toEqual(worker);
    });

    it('should return undefined for nonexistent worker', () => {
      expect(useWorkersStore.getState().getWorker('nonexistent')).toBeUndefined();
    });
  });

  describe('getWorkersList', () => {
    it('should return all workers as array', () => {
      const workers = [createWorker('worker-1'), createWorker('worker-2')];
      useWorkersStore.getState().setWorkers(workers);

      const list = useWorkersStore.getState().getWorkersList();

      expect(list).toHaveLength(2);
      expect(list.map(w => w.id).sort()).toEqual(['worker-1', 'worker-2']);
    });

    it('should return empty array when no workers', () => {
      expect(useWorkersStore.getState().getWorkersList()).toEqual([]);
    });
  });

  describe('getIdleWorkers', () => {
    it('should return only idle workers', () => {
      useWorkersStore.getState().setWorkers([
        createWorker('worker-1', 'idle'),
        createWorker('worker-2', 'busy'),
        createWorker('worker-3', 'idle'),
      ]);

      const idleWorkers = useWorkersStore.getState().getIdleWorkers();

      expect(idleWorkers).toHaveLength(2);
      expect(idleWorkers.map(w => w.id).sort()).toEqual(['worker-1', 'worker-3']);
    });

    it('should return empty array when no idle workers', () => {
      useWorkersStore.getState().setWorkers([
        createWorker('worker-1', 'busy'),
        createWorker('worker-2', 'busy'),
      ]);

      expect(useWorkersStore.getState().getIdleWorkers()).toEqual([]);
    });
  });

  describe('getSelectedWorker', () => {
    it('should return selected worker', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);
      useWorkersStore.getState().selectWorker('worker-1');

      expect(useWorkersStore.getState().getSelectedWorker()).toEqual(worker);
    });

    it('should return undefined when no worker selected', () => {
      const worker = createWorker('worker-1');
      useWorkersStore.getState().updateWorker(worker);

      expect(useWorkersStore.getState().getSelectedWorker()).toBeUndefined();
    });

    it('should return undefined when selected worker does not exist', () => {
      useWorkersStore.getState().selectWorker('nonexistent');

      expect(useWorkersStore.getState().getSelectedWorker()).toBeUndefined();
    });
  });
});
