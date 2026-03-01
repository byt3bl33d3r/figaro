import { useEffect, useCallback } from 'react';
import { useWorkersStore } from '../stores/workers';
import { useMessagesStore } from '../stores/messages';
import { VNCViewer } from './VNCViewer';
import { WorkerStatusBadge, AgentBadge } from './StatusBadge';
import { EventItem } from './EventItem';
import { getVncProxyUrl } from '../api/vnc';

interface DesktopModalProps {
  workerId: string;
  onClose: () => void;
}

export function DesktopModal({ workerId, onClose }: DesktopModalProps) {
  const worker = useWorkersStore((state) => state.getWorker(workerId));
  const workerEvents = useMessagesStore((state) => state.getWorkerEvents(workerId));

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, []);

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  if (!worker) {
    return null;
  }

  // Filter visible events
  const visibleEvents = workerEvents
    .filter((e) => {
      if (e.type === 'message') {
        const msg = e.data as { __type__?: string; type?: string };
        if (msg.__type__ === 'content_block_stop' || msg.type === 'content_block_stop') {
          return false;
        }
      }
      return true;
    })
    .slice(-50); // Show last 50 events

  return (
    <div
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-7xl h-full max-h-[90vh] bg-cctv-panel rounded-lg overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-cctv-bg border-b border-cctv-border">
          <div className="flex items-center gap-3">
            <span className="text-cctv-text font-medium">
              Worker: {worker.id.slice(0, 8)}
            </span>
            {worker.metadata?.os && (
              <span className="text-xs text-cctv-text-dim uppercase">
                {worker.metadata.os}
              </span>
            )}
            <AgentBadge connected={worker.agent_connected} />
            <WorkerStatusBadge status={worker.status} />
          </div>
          <button
            onClick={onClose}
            className="text-cctv-text-dim hover:text-cctv-text transition-colors text-2xl leading-none"
            title="Close (Esc)"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex overflow-hidden">
          {/* VNC Viewer */}
          <div className="flex-1 bg-black">
            <VNCViewer
              url={getVncProxyUrl(worker.id)}
              username={worker.vnc_username}
              password={worker.vnc_password}
              viewOnly={false}
              className="w-full h-full"
            />
          </div>

          {/* Event History */}
          <div className="w-80 border-l border-cctv-border flex flex-col">
            <div className="px-3 py-2 border-b border-cctv-border bg-cctv-bg">
              <span className="text-xs text-cctv-text-dim uppercase tracking-wider">
                Recent Activity
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {visibleEvents.length === 0 ? (
                <div className="p-4 text-center text-cctv-text-dim text-sm">
                  No activity yet
                </div>
              ) : (
                visibleEvents.map((event) => (
                  <EventItem key={event.id} event={event} />
                ))
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-2 bg-cctv-bg border-t border-cctv-border text-xs text-cctv-text-dim">
          <span className="mr-4">Press Esc to close</span>
          {worker.capabilities.length > 0 && (
            <span>
              Capabilities: {worker.capabilities.join(', ')}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
