import { useCallback, useState } from 'react';
import { useWorkersStore } from '../stores/workers';
import { useMessagesStore } from '../stores/messages';
import { EventStream } from './EventStream';
import { ChatInput } from './ChatInput';
import { ScheduleButton } from './ScheduleButton';
import { ScheduledTasksList } from './ScheduledTasksList';

export function Sidebar() {
  const selectWorker = useWorkersStore((state) => state.selectWorker);
  const setFilterWorkerId = useMessagesStore((state) => state.setFilterWorkerId);
  const [showScheduled, setShowScheduled] = useState(false);

  const handleWorkerClick = useCallback(
    (workerId: string) => {
      selectWorker(workerId);
      setFilterWorkerId(workerId);
    },
    [selectWorker, setFilterWorkerId]
  );

  return (
    <aside className="w-80 xl:w-96 flex flex-col bg-cctv-panel border-l border-cctv-border">
      {/* Header with tabs and schedule button */}
      <div className="px-4 py-3 border-b border-cctv-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowScheduled(false)}
            className={`text-sm font-semibold uppercase tracking-wider transition-colors ${
              !showScheduled ? 'text-cctv-text' : 'text-cctv-text-dim hover:text-cctv-text'
            }`}
          >
            Events
          </button>
          <span className="text-cctv-text-dim">/</span>
          <button
            onClick={() => setShowScheduled(true)}
            className={`text-sm font-semibold uppercase tracking-wider transition-colors ${
              showScheduled ? 'text-cctv-text' : 'text-cctv-text-dim hover:text-cctv-text'
            }`}
          >
            Scheduled
          </button>
        </div>
        <ScheduleButton />
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden relative">
        <div className={`h-full ${showScheduled ? 'hidden' : ''}`}>
          <EventStream onWorkerClick={handleWorkerClick} />
        </div>
        <div className={`h-full overflow-y-auto ${showScheduled ? '' : 'hidden'}`}>
          <ScheduledTasksList />
        </div>
      </div>

      {/* Chat Input */}
      <ChatInput />
    </aside>
  );
}
