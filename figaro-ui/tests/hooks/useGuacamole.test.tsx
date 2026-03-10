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
  const mockDisplay = {
    getElement: vi.fn(() => mockDisplayElement),
    getWidth: vi.fn(() => 1024),
    getHeight: vi.fn(() => 768),
    scale: vi.fn(),
    getScale: vi.fn(() => 1),
    onresize: null as ((width: number, height: number) => void) | null,
  };
  const mockClient = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    getDisplay: vi.fn(() => mockDisplay),
    sendMouseState: vi.fn(),
    sendKeyEvent: vi.fn(),
    onstatechange: null as ((state: number) => void) | null,
    onerror: null as ((status: { code: number; message?: string }) => void) | null,
  };

  return {
    default: {
      WebSocketTunnel: vi.fn(),
      Client: vi.fn(() => mockClient),
      Mouse: vi.fn(() => {
        const mouse = {
          onmousedown: null as ((state: Record<string, unknown>) => void) | null,
          onmouseup: null as ((state: Record<string, unknown>) => void) | null,
          onmousemove: null as ((state: Record<string, unknown>) => void) | null,
        };
        return mouse;
      }),
      Keyboard: vi.fn(() => ({
        onkeydown: null,
        onkeyup: null,
        reset: vi.fn(),
      })),
      // Expose for test access
      __mockClient: mockClient,
      __mockDisplay: mockDisplay,
      __mockDisplayElement: mockDisplayElement,
    },
  };
});

import Guacamole from 'guacamole-common-js';
import { useGuacamole } from '../../src/hooks/useGuacamole';

// Access mock internals
const mockGuacamole = Guacamole as unknown as {
  Client: ReturnType<typeof vi.fn>;
  Mouse: ReturnType<typeof vi.fn>;
  Keyboard: ReturnType<typeof vi.fn>;
  WebSocketTunnel: ReturnType<typeof vi.fn>;
  __mockClient: {
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    sendMouseState: ReturnType<typeof vi.fn>;
    onstatechange: ((state: number) => void) | null;
    onerror: ((status: { code: number; message?: string }) => void) | null;
  };
  __mockDisplay: {
    getElement: ReturnType<typeof vi.fn>;
    getWidth: ReturnType<typeof vi.fn>;
    getHeight: ReturnType<typeof vi.fn>;
    scale: ReturnType<typeof vi.fn>;
    getScale: ReturnType<typeof vi.fn>;
    onresize: ((width: number, height: number) => void) | null;
  };
  __mockDisplayElement: HTMLDivElement;
};

describe('useGuacamole', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGuacamole.__mockClient.onstatechange = null;
    mockGuacamole.__mockClient.onerror = null;
    mockGuacamole.__mockDisplay.onresize = null;
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

  describe('display scaling', () => {
    it('should rescale when remote display resizes', async () => {
      const container = document.createElement('div');
      Object.defineProperty(container, 'clientWidth', { value: 800, configurable: true });
      Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true });

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

      // onresize handler should have been set on the display
      expect(mockGuacamole.__mockDisplay.onresize).toBeTypeOf('function');

      // Clear scale calls from initial connect
      mockGuacamole.__mockDisplay.scale.mockClear();

      // Simulate remote display resize
      act(() => {
        mockGuacamole.__mockDisplay.onresize?.(1920, 1080);
      });

      // scale() should have been called again to fit the new resolution
      expect(mockGuacamole.__mockDisplay.scale).toHaveBeenCalled();
    });

    it('should center display element with margin auto', async () => {
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

      // Display element should have centering margin
      expect(mockGuacamole.__mockDisplayElement.style.margin).toBe('0px auto');
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

  describe('mouse coordinate scaling', () => {
    it('should scale mouse coordinates by display scale factor', async () => {
      const container = document.createElement('div');
      Object.defineProperty(container, 'clientWidth', { value: 512, configurable: true });
      Object.defineProperty(container, 'clientHeight', { value: 384, configurable: true });

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId, viewOnly: false }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      // Display is 1024x768, container is 512x384 → scale = 0.5
      mockGuacamole.__mockDisplay.getScale.mockReturnValue(0.5);

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      // Simulate connected (state 3) — sets up mouse handlers
      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(3);
      });

      // Get the mock Mouse instance
      const mockMouse = mockGuacamole.Mouse.mock.results[
        mockGuacamole.Mouse.mock.results.length - 1
      ].value;

      // Simulate a mouse click at (256, 192) in DOM space
      // With scale 0.5, this should map to (512, 384) in remote desktop space
      const mouseState = {
        x: 256, y: 192,
        left: true, middle: false, right: false,
        up: false, down: false,
      };

      act(() => {
        mockMouse.onmousedown?.(mouseState);
      });

      expect(mockGuacamole.__mockClient.sendMouseState).toHaveBeenCalledWith(
        expect.objectContaining({ x: 512, y: 384 }),
      );
    });

    it('should not mutate the original mouse state object', async () => {
      const container = document.createElement('div');
      Object.defineProperty(container, 'clientWidth', { value: 512, configurable: true });
      Object.defineProperty(container, 'clientHeight', { value: 384, configurable: true });

      const { result, rerender } = renderHook(
        ({ workerId }) => useGuacamole({ workerId, viewOnly: false }),
        { initialProps: { workerId: undefined as string | undefined } }
      );

      Object.defineProperty(result.current.containerRef, 'current', {
        value: container,
        writable: true,
      });

      mockGuacamole.__mockDisplay.getScale.mockReturnValue(0.5);

      rerender({ workerId: 'worker-1' });

      await waitFor(() => {
        expect(mockGuacamole.Client).toHaveBeenCalled();
      });

      act(() => {
        mockGuacamole.__mockClient.onstatechange?.(3);
      });

      const mockMouse = mockGuacamole.Mouse.mock.results[
        mockGuacamole.Mouse.mock.results.length - 1
      ].value;

      // Simulate mouse move — the original state must not be mutated
      // because Guacamole.Mouse uses it internally for position tracking
      const mouseState = {
        x: 100, y: 200,
        left: false, middle: false, right: false,
        up: false, down: false,
      };

      act(() => {
        mockMouse.onmousemove?.(mouseState);
      });

      // Original state must be unchanged
      expect(mouseState.x).toBe(100);
      expect(mouseState.y).toBe(200);

      // The scaled copy should have been sent
      expect(mockGuacamole.__mockClient.sendMouseState).toHaveBeenCalledWith(
        expect.objectContaining({ x: 200, y: 400 }),
      );
    });
  });
});
