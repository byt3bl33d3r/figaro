import { create } from 'zustand';
import type { ConnectionStatus } from '../types';

interface ConnectionState {
  status: ConnectionStatus;
  error: string | null;
  reconnectAttempt: number;

  // Actions
  setStatus: (status: ConnectionStatus) => void;
  setError: (error: string | null) => void;
  incrementReconnectAttempt: () => void;
  resetReconnectAttempt: () => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  status: 'disconnected',
  error: null,
  reconnectAttempt: 0,

  setStatus: (status) => {
    set({ status, error: status === 'error' ? null : null });
  },

  setError: (error) => {
    set({ error, status: 'error' });
  },

  incrementReconnectAttempt: () => {
    set((state) => ({ reconnectAttempt: state.reconnectAttempt + 1 }));
  },

  resetReconnectAttempt: () => {
    set({ reconnectAttempt: 0 });
  },
}));
