import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useElapsedTime } from '../../src/hooks/useElapsedTime';

describe('useElapsedTime', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-01T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should return seconds for recent timestamps', () => {
    const since = new Date('2025-01-01T11:59:30Z'); // 30s ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('30s');
  });

  it('should return minutes and seconds', () => {
    const since = new Date('2025-01-01T11:56:15Z'); // 3m 45s ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('3m 45s');
  });

  it('should return hours and minutes', () => {
    const since = new Date('2025-01-01T10:40:00Z'); // 1h 20m ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('1h 20m');
  });

  it('should accept string dates', () => {
    const since = '2025-01-01T11:59:30Z'; // 30s ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('30s');
  });

  it('should return 0s for current time', () => {
    const since = new Date('2025-01-01T12:00:00Z');
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('0s');
  });

  it('should update every second', () => {
    const since = new Date('2025-01-01T11:59:55Z'); // 5s ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('5s');

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current).toBe('8s');
  });

  it('should transition from seconds to minutes', () => {
    const since = new Date('2025-01-01T11:59:02Z'); // 58s ago
    const { result } = renderHook(() => useElapsedTime(since));

    expect(result.current).toBe('58s');

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current).toBe('1m 1s');
  });

  it('should clean up interval on unmount', () => {
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval');
    const since = new Date('2025-01-01T11:59:30Z');

    const { unmount } = renderHook(() => useElapsedTime(since));
    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
    clearIntervalSpy.mockRestore();
  });
});
