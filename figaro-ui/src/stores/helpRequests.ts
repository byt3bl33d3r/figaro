import { create } from 'zustand';
import type { HelpRequest, HelpRequestStatus } from '../types';

interface HelpRequestsState {
  requests: Map<string, HelpRequest>;
  activeRequestId: string | null;

  // Actions
  addRequest: (request: HelpRequest) => void;
  updateRequestStatus: (requestId: string, status: HelpRequestStatus, source?: string) => void;
  setActiveRequestId: (id: string | null) => void;

  // Selectors
  getRequest: (requestId: string) => HelpRequest | undefined;
  getPendingRequests: () => HelpRequest[];
}

export const useHelpRequestsStore = create<HelpRequestsState>((set, get) => ({
  requests: new Map(),
  activeRequestId: null,

  addRequest: (request) => {
    set((state) => {
      const newRequests = new Map(state.requests);
      newRequests.set(request.request_id, request);
      return { requests: newRequests };
    });
  },

  updateRequestStatus: (requestId, status, source) => {
    set((state) => {
      const request = state.requests.get(requestId);
      if (!request) return state;

      const newRequests = new Map(state.requests);
      newRequests.set(requestId, {
        ...request,
        status,
        response_source: source,
        responded_at: status === 'responded' ? new Date().toISOString() : request.responded_at,
      });
      return { requests: newRequests };
    });
  },

  setActiveRequestId: (id) => {
    set({ activeRequestId: id });
  },

  getRequest: (requestId) => {
    return get().requests.get(requestId);
  },

  getPendingRequests: () => {
    return Array.from(get().requests.values()).filter((r) => r.status === 'pending');
  },

}));
