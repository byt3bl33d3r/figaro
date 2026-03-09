import { create } from 'zustand';
import type { Worker, WorkerStatus } from '../types';

interface WorkersState {
  workers: Map<string, Worker>;
  selectedWorkerId: string | null;

  // Actions
  setWorkers: (workers: Worker[]) => void;
  updateWorker: (worker: Worker) => void;
  updateWorkerStatus: (workerId: string, status: WorkerStatus) => void;
  removeWorker: (workerId: string) => void;
  selectWorker: (workerId: string | null) => void;

  // Selectors
  getWorker: (workerId: string) => Worker | undefined;
  getWorkersList: () => Worker[];
}

export const useWorkersStore = create<WorkersState>((set, get) => ({
  workers: new Map(),
  selectedWorkerId: null,

  setWorkers: (workers) => {
    const workersMap = new Map(workers.map((w) => [w.id, w]));
    set({ workers: workersMap });
  },

  updateWorker: (worker) => {
    set((state) => {
      const newWorkers = new Map(state.workers);
      newWorkers.set(worker.id, worker);
      return { workers: newWorkers };
    });
  },

  updateWorkerStatus: (workerId, status) => {
    set((state) => {
      const worker = state.workers.get(workerId);
      if (!worker) return state;

      const newWorkers = new Map(state.workers);
      newWorkers.set(workerId, { ...worker, status });
      return { workers: newWorkers };
    });
  },

  removeWorker: (workerId) => {
    set((state) => {
      const newWorkers = new Map(state.workers);
      newWorkers.delete(workerId);
      // Clear selection if the removed worker was selected
      const newSelectedId = state.selectedWorkerId === workerId ? null : state.selectedWorkerId;
      return { workers: newWorkers, selectedWorkerId: newSelectedId };
    });
  },

  selectWorker: (workerId) => {
    set({ selectedWorkerId: workerId });
  },

  getWorker: (workerId) => {
    return get().workers.get(workerId);
  },

  getWorkersList: () => {
    return Array.from(get().workers.values());
  },
}));
