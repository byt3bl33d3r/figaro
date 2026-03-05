import { useState, useEffect, useCallback } from 'react';
import { natsManager } from '../api/nats';

interface TaskHistory {
  task_id: string;
  prompt: string;
  status: string;
  worker_id: string | null;
  result: unknown;
  options: Record<string, unknown>;
  created_at: string | null;
  completed_at: string | null;
  cost?: number;
}

interface TaskHistoryModalProps {
  workerId: string;
  onClose: () => void;
}

const statusColors: Record<string, string> = {
  completed: 'bg-green-500/20 text-green-400 border-green-500/50',
  failed: 'bg-red-500/20 text-red-400 border-red-500/50',
  running: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  assigned: 'bg-blue-500/20 text-blue-400 border-blue-500/50',
  pending: 'bg-gray-500/20 text-gray-400 border-gray-500/50',
  cancelled: 'bg-gray-500/20 text-gray-400 border-gray-500/50',
};

export function TaskHistoryModal({ workerId, onClose }: TaskHistoryModalProps) {
  const [tasks, setTasks] = useState<TaskHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchTasks() {
      try {
        const response = await natsManager.request<{ tasks: TaskHistory[] }>(
          'figaro.api.tasks',
          { worker_id: workerId }
        );
        if (!cancelled) {
          setTasks(response.tasks);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch tasks');
          setLoading(false);
        }
      }
    }

    fetchTasks();
    return () => {
      cancelled = true;
    };
  }, [workerId]);

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

  const getStatusBadgeClass = (status: string): string => {
    return statusColors[status] || statusColors.pending;
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-2xl max-h-[80vh] bg-cctv-panel rounded-lg overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-cctv-bg border-b border-cctv-border">
          <span className="text-cctv-text font-medium">
            Task History: {workerId}
          </span>
          <button
            onClick={onClose}
            className="text-cctv-text-dim hover:text-cctv-text transition-colors text-2xl leading-none"
            title="Close (Esc)"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-cctv-text-dim border-t-cctv-accent" />
            </div>
          ) : error ? (
            <div className="p-4 text-center text-red-400 text-sm">{error}</div>
          ) : tasks.length === 0 ? (
            <div className="p-4 text-center text-cctv-text-dim text-sm">
              No tasks found for this worker
            </div>
          ) : (
            <div className="divide-y divide-cctv-border">
              {tasks.map((task) => (
                <div key={task.task_id} className="px-4 py-3 hover:bg-cctv-border/20">
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <p className="text-sm text-cctv-text flex-1 break-words">
                      {task.prompt.length > 100
                        ? `${task.prompt.slice(0, 100)}...`
                        : task.prompt}
                    </p>
                    <span
                      className={`px-2 py-0.5 text-xs uppercase tracking-wider border rounded whitespace-nowrap ${getStatusBadgeClass(task.status)}`}
                    >
                      {task.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-cctv-text-dim">
                    {task.created_at && (
                      <span>Created: {new Date(task.created_at).toLocaleString()}</span>
                    )}
                    {task.completed_at && (
                      <span>Completed: {new Date(task.completed_at).toLocaleString()}</span>
                    )}
                    {task.cost != null && task.cost > 0 && (
                      <span>Cost: ${task.cost.toFixed(4)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 bg-cctv-bg border-t border-cctv-border text-xs text-cctv-text-dim">
          <span>Press Esc to close</span>
          {!loading && !error && (
            <span className="ml-4">{tasks.length} task{tasks.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      </div>
    </div>
  );
}
