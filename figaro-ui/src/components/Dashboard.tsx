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

export function Dashboard() {
  const { status } = useNats();
  const workerCount = useWorkersStore((state) => state.workers.size);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const activeRequestId = useHelpRequestsStore((state) => state.activeRequestId);
  const setActiveRequestId = useHelpRequestsStore((state) => state.setActiveRequestId);

  const handleWorkerClick = useCallback((workerId: string) => {
    setSelectedWorkerId(workerId);
  }, []);

  const handleCloseModal = useCallback(() => {
    setSelectedWorkerId(null);
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
          <span className="text-sm text-cctv-text-dim">
            {workerCount} worker{workerCount !== 1 ? 's' : ''} connected
          </span>
          <HelpRequestNotification onSelectWorker={handleWorkerClick} />
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Desktop Grid */}
        <main className="flex-1 overflow-auto">
          <DesktopGrid onWorkerClick={handleWorkerClick} />
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
