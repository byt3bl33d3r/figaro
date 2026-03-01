import { create } from 'zustand';
import type { Supervisor, WorkerStatus } from '../types';

interface SupervisorsState {
  supervisors: Map<string, Supervisor>;

  // Actions
  setSupervisors: (supervisors: Supervisor[]) => void;
  updateSupervisor: (supervisor: Supervisor) => void;
  updateSupervisorStatus: (supervisorId: string, status: WorkerStatus) => void;
  removeSupervisor: (supervisorId: string) => void;

  // Selectors
  getSupervisor: (supervisorId: string) => Supervisor | undefined;
  getSupervisorsList: () => Supervisor[];
  getIdleSupervisors: () => Supervisor[];
  hasSupervisor: () => boolean;
}

export const useSupervisorsStore = create<SupervisorsState>((set, get) => ({
  supervisors: new Map(),

  setSupervisors: (supervisors) => {
    const supervisorsMap = new Map(supervisors.map((s) => [s.id, s]));
    set({ supervisors: supervisorsMap });
  },

  updateSupervisor: (supervisor) => {
    set((state) => {
      const newSupervisors = new Map(state.supervisors);
      newSupervisors.set(supervisor.id, supervisor);
      return { supervisors: newSupervisors };
    });
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

  removeSupervisor: (supervisorId) => {
    set((state) => {
      const newSupervisors = new Map(state.supervisors);
      newSupervisors.delete(supervisorId);
      return { supervisors: newSupervisors };
    });
  },

  getSupervisor: (supervisorId) => {
    return get().supervisors.get(supervisorId);
  },

  getSupervisorsList: () => {
    return Array.from(get().supervisors.values());
  },

  getIdleSupervisors: () => {
    return Array.from(get().supervisors.values()).filter((s) => s.status === 'idle');
  },

  hasSupervisor: () => {
    return get().supervisors.size > 0;
  },
}));
