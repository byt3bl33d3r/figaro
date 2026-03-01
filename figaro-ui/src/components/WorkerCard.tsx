import type { Worker } from '../types';
import { VNCViewer } from './VNCViewer';
import { WorkerStatusBadge, AgentBadge } from './StatusBadge';
import { getVncProxyUrl } from '../api/vnc';

interface WorkerCardProps {
  worker: Worker;
  onClick: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}

export function WorkerCard({ worker, onClick, onContextMenu }: WorkerCardProps) {
  return (
    <div
      className="group bg-cctv-panel border border-cctv-border rounded-lg overflow-hidden cursor-pointer hover:border-cctv-accent/50 transition-colors"
      onClick={onClick}
      onContextMenu={(e) => {
        if (onContextMenu) {
          e.preventDefault();
          onContextMenu(e);
        }
      }}
    >
      {/* VNC Preview */}
      <div className="relative aspect-video bg-black">
        <VNCViewer
          url={getVncProxyUrl(worker.id)}
          username={worker.vnc_username}
          password={worker.vnc_password}
          viewOnly={true}
          className="w-full h-full"
        />
        {/* Hover overlay */}
        <div className="absolute inset-0 bg-cctv-bg/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <span className="text-cctv-accent text-sm">Click to expand</span>
        </div>
      </div>

      {/* Worker Info */}
      <div className="p-3 border-t border-cctv-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-cctv-text truncate">
              {worker.id.slice(0, 8)}
            </span>
            {worker.metadata?.os && (
              <span className="text-[10px] text-cctv-text-dim uppercase">
                {worker.metadata.os}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <AgentBadge connected={worker.agent_connected} />
            <WorkerStatusBadge status={worker.status} />
          </div>
        </div>
        {worker.capabilities.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {worker.capabilities.slice(0, 3).map((cap) => (
              <span
                key={cap}
                className="px-1.5 py-0.5 text-[10px] bg-cctv-border rounded text-cctv-text-dim"
              >
                {cap}
              </span>
            ))}
            {worker.capabilities.length > 3 && (
              <span className="px-1.5 py-0.5 text-[10px] text-cctv-text-dim">
                +{worker.capabilities.length - 3}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
