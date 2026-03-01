import { describe, it, expect, beforeEach } from 'vitest';
import { useConnectionStore } from '../../src/stores/connection';

describe('useConnectionStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useConnectionStore.setState({
      status: 'disconnected',
      error: null,
      reconnectAttempt: 0,
    });
  });

  describe('initial state', () => {
    it('should have correct initial values', () => {
      const state = useConnectionStore.getState();

      expect(state.status).toBe('disconnected');
      expect(state.error).toBeNull();
      expect(state.reconnectAttempt).toBe(0);
    });
  });

  describe('setStatus', () => {
    it('should update status to connecting', () => {
      useConnectionStore.getState().setStatus('connecting');

      expect(useConnectionStore.getState().status).toBe('connecting');
    });

    it('should update status to connected', () => {
      useConnectionStore.getState().setStatus('connected');

      expect(useConnectionStore.getState().status).toBe('connected');
    });

    it('should update status to disconnected', () => {
      useConnectionStore.getState().setStatus('connected');
      useConnectionStore.getState().setStatus('disconnected');

      expect(useConnectionStore.getState().status).toBe('disconnected');
    });

    it('should update status to error', () => {
      useConnectionStore.getState().setStatus('error');

      expect(useConnectionStore.getState().status).toBe('error');
    });
  });

  describe('setError', () => {
    it('should set error and update status to error', () => {
      useConnectionStore.getState().setStatus('connected');
      useConnectionStore.getState().setError('Connection refused');

      const state = useConnectionStore.getState();
      expect(state.error).toBe('Connection refused');
      expect(state.status).toBe('error');
    });

    it('should clear error with null', () => {
      useConnectionStore.getState().setError('Some error');
      useConnectionStore.getState().setError(null);

      expect(useConnectionStore.getState().error).toBeNull();
    });
  });

  describe('incrementReconnectAttempt', () => {
    it('should increment reconnect attempt counter', () => {
      useConnectionStore.getState().incrementReconnectAttempt();
      expect(useConnectionStore.getState().reconnectAttempt).toBe(1);

      useConnectionStore.getState().incrementReconnectAttempt();
      expect(useConnectionStore.getState().reconnectAttempt).toBe(2);

      useConnectionStore.getState().incrementReconnectAttempt();
      expect(useConnectionStore.getState().reconnectAttempt).toBe(3);
    });
  });

  describe('resetReconnectAttempt', () => {
    it('should reset reconnect attempt counter to 0', () => {
      useConnectionStore.getState().incrementReconnectAttempt();
      useConnectionStore.getState().incrementReconnectAttempt();
      useConnectionStore.getState().incrementReconnectAttempt();

      useConnectionStore.getState().resetReconnectAttempt();

      expect(useConnectionStore.getState().reconnectAttempt).toBe(0);
    });
  });

  describe('reconnection flow', () => {
    it('should handle typical reconnection sequence', () => {
      const store = useConnectionStore.getState();

      // Initial connection
      store.setStatus('connecting');
      expect(useConnectionStore.getState().status).toBe('connecting');

      store.setStatus('connected');
      expect(useConnectionStore.getState().status).toBe('connected');

      // Disconnect
      store.setError('Connection lost');
      expect(useConnectionStore.getState().status).toBe('error');
      expect(useConnectionStore.getState().error).toBe('Connection lost');

      // Retry attempts
      store.incrementReconnectAttempt();
      store.setStatus('connecting');
      expect(useConnectionStore.getState().reconnectAttempt).toBe(1);

      store.setError('Still disconnected');
      store.incrementReconnectAttempt();
      expect(useConnectionStore.getState().reconnectAttempt).toBe(2);

      // Successful reconnection
      store.setStatus('connected');
      store.resetReconnectAttempt();
      // Note: setError(null) would set status to 'error', so we set status after clearing
      // In real usage, you'd likely just setStatus('connected') which clears the error via setStatus

      const finalState = useConnectionStore.getState();
      expect(finalState.status).toBe('connected');
      expect(finalState.reconnectAttempt).toBe(0);
      // Note: error is cleared when status changes (not via setError(null) which also sets status to error)
      expect(finalState.error).toBeNull();
    });
  });
});
