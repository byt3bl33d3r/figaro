import { create } from 'zustand';
import type { StreamEvent, SDKMessage } from '../types';

const MAX_EVENTS = 1000;

interface MessagesState {
  events: StreamEvent[];
  filterWorkerId: string | null;

  // Actions
  addEvent: (event: Omit<StreamEvent, 'id' | 'timestamp'>) => void;
  addSDKMessage: (message: SDKMessage) => void;
  setFilterWorkerId: (workerId: string | null) => void;
  clearEvents: () => void;

  // Selectors
  getFilteredEvents: () => StreamEvent[];
  getWorkerEvents: (workerId: string) => StreamEvent[];
}

let eventCounter = 0;

export const useMessagesStore = create<MessagesState>((set, get) => ({
  events: [],
  filterWorkerId: null,

  addEvent: (eventData) => {
    const event: StreamEvent = {
      ...eventData,
      id: `event-${++eventCounter}`,
      timestamp: new Date(),
    };

    set((state) => {
      const newEvents = [...state.events, event];
      // Trim to max events, removing oldest
      if (newEvents.length > MAX_EVENTS) {
        return { events: newEvents.slice(-MAX_EVENTS) };
      }
      return { events: newEvents };
    });
  },

  addSDKMessage: (message) => {
    get().addEvent({
      worker_id: message.worker_id,
      type: 'message',
      data: message,
    });
  },

  setFilterWorkerId: (workerId) => {
    set({ filterWorkerId: workerId });
  },

  clearEvents: () => {
    set({ events: [] });
  },

  getFilteredEvents: () => {
    const { events, filterWorkerId } = get();
    if (!filterWorkerId) return events;
    return events.filter((e) => e.worker_id === filterWorkerId);
  },

  getWorkerEvents: (workerId) => {
    return get().events.filter((e) => e.worker_id === workerId);
  },
}));
