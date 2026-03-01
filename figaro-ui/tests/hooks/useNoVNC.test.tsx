import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Mock the noVNC RFB class
const mockRFB = {
  viewOnly: true,
  scaleViewport: true,
  clipViewport: false,
  resizeSession: false,
  disconnect: vi.fn(),
  sendKey: vi.fn(),
  sendCtrlAltDel: vi.fn(),
  focus: vi.fn(),
  addEventListener: vi.fn(),
};

const MockRFBConstructor = vi.fn(() => mockRFB);

vi.mock('@novnc/novnc/lib/rfb.js', () => ({
  default: MockRFBConstructor,
}));

// Import after mocking
import { useNoVNC } from '../../src/hooks/useNoVNC';

describe('useNoVNC', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset mock RFB
    mockRFB.viewOnly = true;
    mockRFB.scaleViewport = true;
    mockRFB.clipViewport = false;
    mockRFB.resizeSession = false;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should return initial state when url is undefined', () => {
      const { result } = renderHook(() =>
        useNoVNC({ url: undefined })
      );

      expect(result.current.connected).toBe(false);
      expect(result.current.connecting).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should have container ref', () => {
      const { result } = renderHook(() =>
        useNoVNC({ url: undefined })
      );

      expect(result.current.containerRef).toBeDefined();
      expect(result.current.containerRef.current).toBeNull();
    });
  });

  describe('connection lifecycle', () => {
    it('should start connecting when url is provided', async () => {
      // Create a container element
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      // Now set the ref and provide url
      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      // Rerender with url
      rerender({ url: 'ws://localhost:6080/websockify' });

      // Should be connecting
      await waitFor(() => {
        expect(result.current.connecting).toBe(true);
      });
    });
  });

  describe('actions', () => {
    it('should disconnect when called', () => {
      const { result } = renderHook(() =>
        useNoVNC({ url: undefined })
      );

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.connected).toBe(false);
      expect(result.current.connecting).toBe(false);
    });

    it('should call sendKey on RFB instance', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      // Trigger connection and wait for it
      rerender({ url: 'ws://localhost:6080/websockify' });

      // Wait a bit for the async connection
      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate connect event
      const connectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'connect'
      )?.[1];

      if (connectListener) {
        act(() => {
          connectListener();
        });
      }

      // Now call sendKey
      act(() => {
        result.current.sendKey(65, true); // 'A' key
      });

      expect(mockRFB.sendKey).toHaveBeenCalledWith(65, null, true);
    });

    it('should call sendCtrlAltDel on RFB instance', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      act(() => {
        result.current.sendCtrlAltDel();
      });

      expect(mockRFB.sendCtrlAltDel).toHaveBeenCalled();
    });

    it('should call focus on RFB instance', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      act(() => {
        result.current.focus();
      });

      expect(mockRFB.focus).toHaveBeenCalled();
    });
  });

  describe('reconnection', () => {
    it('should schedule reconnect after unclean disconnect', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate unclean disconnect
      const disconnectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'disconnect'
      )?.[1];

      act(() => {
        disconnectListener?.({ detail: { clean: false } });
      });

      // Should show reconnecting message and be in connecting state
      expect(result.current.connecting).toBe(true);
      expect(result.current.error).toMatch(/Reconnecting in/);
    });

    it('should schedule reconnect after clean disconnect', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate clean disconnect (e.g. orchestrator graceful shutdown)
      const disconnectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'disconnect'
      )?.[1];

      act(() => {
        disconnectListener?.({ detail: { clean: true } });
      });

      // Should still reconnect — proxy may close cleanly on orchestrator restart
      expect(result.current.connecting).toBe(true);
      expect(result.current.error).toMatch(/Reconnecting in/);
    });

    it('should not reconnect after cleanup/unmount', async () => {
      const container = document.createElement('div');

      const { result, rerender, unmount } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalledTimes(1);
      });

      // Unmount (sets cancelled = true) — cleanup clears timers
      unmount();

      // Simulate disconnect after unmount — should not schedule reconnect
      const disconnectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'disconnect'
      )?.[1];

      // The cancelled flag prevents scheduleReconnect from running
      act(() => {
        disconnectListener?.({ detail: { clean: false } });
      });

      // No new RFB should have been created
      expect(MockRFBConstructor).toHaveBeenCalledTimes(1);
    });

    it('should reset reconnect counter on successful connect', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate connect event
      const connectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'connect'
      )?.[1];

      act(() => {
        connectListener?.();
      });

      // After successful connect, error should be cleared
      expect(result.current.connected).toBe(true);
      expect(result.current.error).toBeNull();
      expect(result.current.connecting).toBe(false);
    });

    it('should clear stale DOM children on connect', async () => {
      const container = document.createElement('div');
      // Simulate noVNC leaving a canvas behind from a previous connection
      container.appendChild(document.createElement('canvas'));

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalledTimes(1);
      });

      // Container should have been cleared before creating new RFB
      expect(container.childNodes.length).toBe(0);
    });
  });

  describe('callbacks', () => {
    it('should call onConnect callback when connected', async () => {
      const onConnect = vi.fn();
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url, onConnect }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate connect event
      const connectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'connect'
      )?.[1];

      if (connectListener) {
        act(() => {
          connectListener();
        });

        expect(onConnect).toHaveBeenCalled();
      }
    });

    it('should call onDisconnect callback when disconnected', async () => {
      const onDisconnect = vi.fn();
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url, onDisconnect }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      // Simulate disconnect event
      const disconnectListener = mockRFB.addEventListener.mock.calls.find(
        (call) => call[0] === 'disconnect'
      )?.[1];

      if (disconnectListener) {
        act(() => {
          disconnectListener({ detail: { clean: true } });
        });

        expect(onDisconnect).toHaveBeenCalledWith(true);
      }
    });
  });

  describe('options', () => {
    it('should set viewOnly option on RFB', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url, viewOnly }) => useNoVNC({ url, viewOnly }),
        { initialProps: { url: undefined as string | undefined, viewOnly: false } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify', viewOnly: false });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      expect(mockRFB.viewOnly).toBe(false);
    });

    it('should set scaleViewport option on RFB', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ url }) => useNoVNC({ url, scaleViewport: false }),
        { initialProps: { url: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ url: 'ws://localhost:6080/websockify' });

      await waitFor(() => {
        expect(MockRFBConstructor).toHaveBeenCalled();
      });

      expect(mockRFB.scaleViewport).toBe(false);
    });
  });
});
