import { create } from 'zustand';
import type { Supervisor, WorkerStatus } from '../types';

interface SupervisorsState {
  supervisors: Map<string, Supervisor>;

  // Actions
  setSupervisors: (supervisors: Supervisor[]) => void;
  updateSupervisorStatus: (supervisorId: string, status: WorkerStatus) => void;

  // Selectors
  getSupervisorsList: () => Supervisor[];
  hasSupervisor: () => boolean;
}

export const useSupervisorsStore = create<SupervisorsState>((set, get) => ({
  supervisors: new Map(),

  setSupervisors: (supervisors) => {
    const supervisorsMap = new Map(supervisors.map((s) => [s.id, s]));
    set({ supervisors: supervisorsMap });
  },

  updateSupervisorStatus: (supervisorId, status) => {
    set((state) => {
      const supervisor = state.supervisors.get(supervisorId);
      if (!supervisor) return state;

      const newSupervisors = new Map(state.supervisors);
      newSupervisors.set(supervisorId, { ...supervisor, status });
      return { supervisors: newSupervisors };
    });
  },

  getSupervisorsList: () => {
    return Array.from(get().supervisors.values());
  },

  hasSupervisor: () => {
    return get().supervisors.size > 0;
  },
}));
