import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useMessagesStore } from '../stores/messages';
import { useWorkersStore } from '../stores/workers';
import { useSupervisorsStore } from '../stores/supervisors';
import { useConnectionStore } from '../stores/connection';
import { EventItem, shouldShowEvent } from './EventItem';

const PAGE_SIZE = 20;

interface EventStreamProps {
  onWorkerClick?: (workerId: string) => void;
}

export function EventStream({ onWorkerClick }: EventStreamProps) {
  const events = useMessagesStore((state) => state.getFilteredEvents());
  const filterWorkerId = useMessagesStore((state) => state.filterWorkerId);
  const setFilterWorkerId = useMessagesStore((state) => state.setFilterWorkerId);
  const workers = useWorkersStore((state) => state.getWorkersList());
  const supervisors = useSupervisorsStore((state) => state.getSupervisorsList());
  const connectionStatus = useConnectionStore((state) => state.status);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(false);
  const prevScrollHeightRef = useRef<number | null>(null);
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [displayCount, setDisplayCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);

  const visibleEvents = events.filter(shouldShowEvent);
  const startIndex = Math.max(0, visibleEvents.length - displayCount);
  const displayedEvents = visibleEvents.slice(startIndex);
  const hasMore = startIndex > 0;

  // When older events are loaded (displayCount grows), preserve scroll position
  useLayoutEffect(() => {
    if (prevScrollHeightRef.current !== null && scrollRef.current) {
      const newScrollHeight = scrollRef.current.scrollHeight;
      scrollRef.current.scrollTop = newScrollHeight - prevScrollHeightRef.current;
      prevScrollHeightRef.current = null;
    }
  }, [displayCount]);

  // During initial load, wait for events to settle (stop arriving rapidly),
  // then reveal the list scrolled to bottom. After that, auto-scroll normally.
  useEffect(() => {
    if (loading) {
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
      settleTimerRef.current = setTimeout(() => {
        setLoading(false);
        isAtBottomRef.current = true;
        settleTimerRef.current = null;
      }, 500);
    } else if (isAtBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visibleEvents.length, loading]);

  // After loading completes, scroll to bottom on the first render
  useLayoutEffect(() => {
    if (!loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [loading]);

  // Reset loading state on reconnection (events are cleared and JetStream replays)
  const prevStatusRef = useRef(connectionStatus);
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = connectionStatus;
    if (connectionStatus === 'connected' && prev !== 'connected') {
      setDisplayCount(PAGE_SIZE);
      setLoading(true);
      isAtBottomRef.current = false;
    }
  }, [connectionStatus]);

  // Reset display count and loading state when filter changes
  useEffect(() => {
    setDisplayCount(PAGE_SIZE);
    setLoading(true);
    isAtBottomRef.current = false;
  }, [filterWorkerId]);

  // Cleanup settle timer on unmount
  useEffect(() => {
    return () => {
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    };
  }, []);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    isAtBottomRef.current = scrollTop + clientHeight >= scrollHeight - 50;

    // Load more when scrolled near the top
    if (scrollTop < 100 && hasMore) {
      prevScrollHeightRef.current = scrollRef.current.scrollHeight;
      setDisplayCount((c) => c + PAGE_SIZE);
    }
  }, [hasMore]);

  return (
    <div className="flex flex-col h-full">
      {/* Filter bar */}
      <div className="px-3 py-2 border-b border-cctv-border bg-cctv-panel">
        <select
          value={filterWorkerId || ''}
          onChange={(e) => setFilterWorkerId(e.target.value || null)}
          className="w-full bg-cctv-bg border border-cctv-border rounded px-2 py-1 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
        >
          <option value="">All agents</option>
          <optgroup label="Supervisors">
            {supervisors.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id.slice(0, 8)} ({s.status}) [Supervisor]
              </option>
            ))}
          </optgroup>
          <optgroup label="Workers">
            {workers.map((w) => (
              <option key={w.id} value={w.id}>
                {w.id.slice(0, 8)} ({w.status})
              </option>
            ))}
          </optgroup>
        </select>
      </div>

      {/* Events list */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-cctv-text-dim text-sm animate-pulse">
              Loading events...
            </div>
          </div>
        ) : (
          <>
            {hasMore && (
              <div className="p-2 text-center text-cctv-text-dim text-xs animate-pulse">
                Scroll up for older events...
              </div>
            )}
            {displayedEvents.length === 0 ? (
              <div className="p-4 text-center text-cctv-text-dim text-sm">
                No events yet
              </div>
            ) : (
              displayedEvents.map((event) => (
                <EventItem
                  key={event.id}
                  event={event}
                  onWorkerClick={onWorkerClick}
                />
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
