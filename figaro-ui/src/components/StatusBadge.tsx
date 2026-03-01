import type { WorkerStatus, ConnectionStatus } from '../types';

interface WorkerStatusBadgeProps {
  status: WorkerStatus;
}

export function WorkerStatusBadge({ status }: WorkerStatusBadgeProps) {
  const statusStyles = {
    idle: 'bg-cctv-accent/20 text-cctv-accent border-cctv-accent/50',
    busy: 'bg-cctv-warning/20 text-cctv-warning border-cctv-warning/50',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs uppercase tracking-wider border rounded ${statusStyles[status]}`}
    >
      {status}
    </span>
  );
}

interface AgentBadgeProps {
  connected: boolean;
}

export function AgentBadge({ connected }: AgentBadgeProps) {
  if (connected) {
    return null;
  }

  return (
    <span className="px-2 py-0.5 text-xs uppercase tracking-wider border rounded bg-cctv-error/20 text-cctv-error border-cctv-error/50">
      NO AGENT
    </span>
  );
}

interface ConnectionStatusBadgeProps {
  status: ConnectionStatus;
}

export function ConnectionStatusBadge({ status }: ConnectionStatusBadgeProps) {
  const statusStyles = {
    connecting: 'bg-cctv-warning/20 text-cctv-warning',
    connected: 'bg-cctv-accent/20 text-cctv-accent',
    disconnected: 'bg-cctv-text-dim/20 text-cctv-text-dim',
    error: 'bg-cctv-error/20 text-cctv-error',
  };

  const statusDot = {
    connecting: 'bg-cctv-warning animate-pulse',
    connected: 'bg-cctv-accent',
    disconnected: 'bg-cctv-text-dim',
    error: 'bg-cctv-error',
  };

  return (
    <span className={`flex items-center gap-2 px-3 py-1 text-xs uppercase tracking-wider rounded ${statusStyles[status]}`}>
      <span className={`w-2 h-2 rounded-full ${statusDot[status]}`} />
      {status}
    </span>
  );
}
