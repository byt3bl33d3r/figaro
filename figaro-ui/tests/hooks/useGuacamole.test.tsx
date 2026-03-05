import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Mock the guacamole API
vi.mock('../../src/api/guacamole', () => ({
  getGuacamoleToken: vi.fn().mockResolvedValue('mock-token'),
  getGuacamoleWsUrl: vi.fn().mockReturnValue('ws://localhost/guacamole/webSocket?token=mock-token'),
}));

// Shared mock state — declared inline so the hoisted vi.mock factory can use vi.fn() directly
vi.mock('guacamole-common-js', () => {
  const mockDisplayElement = document.createElement('div');
  const mockClient = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    getDisplay: vi.fn(() => ({
      getElement: vi.fn(() => mockDisplayElement),
      getWidth: vi.fn(() => 1024),
      getHeight: vi.fn(() => 768),
      scale: vi.fn(),
    })),
    sendMouseState: vi.fn(),
    sendKeyEvent: vi.fn(),
    onstatechange: null as ((state: number) => void) | null,
    onerror: null as ((status: { code: number; message?: string }) => void) | null,
  };

  return {
    default: {
      WebSocketTunnel: vi.fn(),
      Client: vi.fn(() => mockClient),
      Mouse: vi.fn(() => ({
        onmousedown: null,
        onmouseup: null,
        onmousemove: null,
      })),
      Keyboard: vi.fn(() => ({
        onkeydown: null,
        onkeyup: null,
        reset: vi.fn(),
      })),
      // Expose for test access
      __mockClient: mockClient,
    },
  };
});

import Guacamole from 'guacamole-common-js';
import { useGuacamole } from '../../src/hooks/useGuacamole';

// Access mock internals
const mockGuacamole = Guacamole as unknown as {
  Client: ReturnType<typeof vi.fn>;
  Keyboard: ReturnType<typeof vi.fn>;
  WebSocketTunnel: ReturnType<typeof vi.fn>;
  __mockClient: {
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    onstatechange: ((state: number) => void) | null;
    onerror: ((status: { code: number; message?: string }) => void) | null;
  };
};

describe('useGuacamole', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGuacamole.__mockClient.onstatechange = null;
    mockGuacamole.__mockClient.onerror = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('initial state', () => {
    it('should return initial state when workerId is undefined', () => {
      const { result } = renderHook(() =>
        useGuacamole({ workerId: undefined })
      );

      expect(result.current.connected).toBe(false);
      expect(result.current.connecting).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should have container ref', () => {
      const { result } = renderHook(() =>
        useGuacamole({ workerId: undefined })
      );

      expect(result.current.containerRef).toBeDefined();
      expect(result.current.containerRef.current).toBeNull();
    });
  });

  describe('connection lifecycle', () => {
    it('should start connecting when workerId is provided', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(result.current.connecting).toBe(true);
      });
    });

    it('should create tunnel and client after fetching token', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      expect(mockGuacamole.__mockClient.connect).toHaveBeenCalled();
    });
  });

  describe('actions', () => {
    it('should disconnect when called', () => {
      const { result } = renderHook(() =>
        useGuacamole({ workerId: undefined })
      );

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.connected).toBe(false);
      expect(result.current.connecting).toBe(false);
    });
  });

  describe('reconnection', () => {
    it('should schedule reconnect after disconnect', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      // Simulate disconnect (state 5)
      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(5);
      });

      expect(result.current.connecting).toBe(true);
      expect(result.current.error).toMatch(/Reconnecting in/);
    });

    it('should not reconnect after cleanup/unmount', async () => {
      const container = document.createElement('div');

      const { result, rerender, unmount } = renderHook(
        ({ workerId }) => useGuacamole({ workerId }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalledTimes(1);
      });

      unmount();

      // Simulate disconnect after unmount
      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(5);
      });

      // No new client should have been created
      expect(mockGuacamole.Client).toHaveBeenCalledTimes(1);
    });

    it('should reset reconnect counter on successful connect', async () => {
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      // Simulate connected (state 3)
      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(3);
      });

      expect(result.current.connected).toBe(true);
      expect(result.current.error).toBeNull();
      expect(result.current.connecting).toBe(false);
    });
  });

  describe('keyboard cleanup', () => {
    it('should null out keyboard handlers on unmount to stop blocking input', async () => {
      const container = document.createElement('div');

      const { result, rerender, unmount } = renderHook(
        ({ workerId }) => useGuacamole({ workerId, viewOnly: false }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      // Simulate connected (state 3) — this creates the Keyboard instance
      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(3);
      });

      // Keyboard should have been created with document
      expect(mockGuacamole.Keyboard).toHaveBeenCalledWith(document);
      const mockKeyboard = mockGuacamole.Keyboard.mock.results[
        mockGuacamole.Keyboard.mock.results.length - 1
      ].value;

      // Handlers should be set while connected
      expect(mockKeyboard.onkeydown).toBeTypeOf('function');
      expect(mockKeyboard.onkeyup).toBeTypeOf('function');

      // Unmount the hook (simulates closing the modal)
      unmount();

      // Handlers must be nulled out so the lingering document listeners
      // stop calling preventDefault() on every keystroke
      expect(mockKeyboard.onkeydown).toBeNull();
      expect(mockKeyboard.onkeyup).toBeNull();
      expect(mockKeyboard.reset).toHaveBeenCalled();
    });
  });

  describe('callbacks', () => {
    it('should call onConnect callback when connected', async () => {
      const onConnect = vi.fn();
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId, onConnect }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(3);
      });

      expect(onConnect).toHaveBeenCalled();
    });

    it('should call onDisconnect callback when disconnected', async () => {
      const onDisconnect = vi.fn();
      const container = document.createElement('div');

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId, onDisconnect }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(5);
      });

      expect(onDisconnect).toHaveBeenCalled();
    });
  });
});
