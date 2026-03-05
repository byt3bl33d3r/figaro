import { useState, useCallback } from 'react';
import { useNats } from '../hooks/useNats';
import { useWorkersStore } from '../stores/workers';
import { useHelpRequestsStore } from '../stores/helpRequests';
import { ConnectionStatusBadge } from './StatusBadge';
import { DesktopGrid } from './DesktopGrid';
import { Sidebar } from './Sidebar';
import { DesktopModal } from './DesktopModal';
import { HelpRequestNotification } from './HelpRequestNotification';
import { HelpRequestModal } from './HelpRequestModal';
import { KanbanBoard } from './KanbanBoard';
import { TaskHistoryModal } from './TaskHistoryModal';

export function Dashboard() {
  const { status } = useNats();
  const workerCount = useWorkersStore((state) => state.workers.size);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [workerHistoryId, setWorkerHistoryId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'board'>('grid');
  const activeRequestId = useHelpRequestsStore((state) => state.activeRequestId);
  const setActiveRequestId = useHelpRequestsStore((state) => state.setActiveRequestId);

  const handleWorkerClick = useCallback((workerId: string) => {
    setSelectedWorkerId(workerId);
  }, []);

  const handleCloseModal = useCallback(() => {
    setSelectedWorkerId(null);
  }, []);

  const handleWorkerHistoryClick = useCallback((workerId: string) => {
    setWorkerHistoryId(workerId);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-cctv-bg">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 bg-cctv-panel border-b border-cctv-border">
        <div className="flex items-center gap-4">
          <ConnectionStatusBadge status={status} />
          <h1 className="text-lg font-semibold text-cctv-text">
            Figaro Dashboard
          </h1>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex rounded border border-cctv-border overflow-hidden">
            <button
              onClick={() => setViewMode('grid')}
              className={`px-3 py-1 text-xs uppercase tracking-wider transition-colors ${viewMode === 'grid' ? 'bg-cctv-accent/20 text-cctv-accent' : 'text-cctv-text-dim hover:text-cctv-text'}`}
            >
              Grid
            </button>
            <button
              onClick={() => setViewMode('board')}
              className={`px-3 py-1 text-xs uppercase tracking-wider transition-colors ${viewMode === 'board' ? 'bg-cctv-accent/20 text-cctv-accent' : 'text-cctv-text-dim hover:text-cctv-text'}`}
            >
              Board
            </button>
          </div>
          <span className="text-sm text-cctv-text-dim">
            {workerCount} worker{workerCount !== 1 ? 's' : ''} connected
          </span>
          <HelpRequestNotification onSelectWorker={handleWorkerClick} />
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        <main className="flex-1 overflow-auto">
          {viewMode === 'grid' ? (
            <DesktopGrid onWorkerClick={handleWorkerClick} />
          ) : (
            <KanbanBoard onWorkerClick={handleWorkerClick} onWorkerHistoryClick={handleWorkerHistoryClick} />
          )}
        </main>

        {/* Sidebar */}
        <Sidebar />
      </div>

      {/* Fullscreen Modal */}
      {selectedWorkerId && (
        <DesktopModal
          workerId={selectedWorkerId}
          onClose={handleCloseModal}
        />
      )}

      {/* Task History Modal */}
      {workerHistoryId && (
        <TaskHistoryModal
          workerId={workerHistoryId}
          onClose={() => setWorkerHistoryId(null)}
        />
      )}

      {/* Help Request Modal */}
      {activeRequestId && (
        <HelpRequestModal
          requestId={activeRequestId}
          onClose={() => setActiveRequestId(null)}
        />
      )}
    </div>
  );
}
