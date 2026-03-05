import type { ActiveTask } from '../types';
import { TaskStatusBadge } from './StatusBadge';
import { useElapsedTime } from '../hooks/useElapsedTime';
import { natsManager } from '../api/nats';

interface KanbanCardProps {
  task: ActiveTask;
  onWorkerClick?: (workerId: string) => void;
}

function formatCost(task: ActiveTask): string | null {
  if (task.cost_usd > 0) {
    return `$${task.cost_usd.toFixed(4)}`;
  }
  const totalTokens = task.input_tokens + task.output_tokens;
  if (totalTokens > 0) {
    return `~${totalTokens.toLocaleString()} tokens`;
  }
  return null;
}

function handleStop(taskId: string, e: React.MouseEvent): void {
  e.stopPropagation();
  natsManager.request('figaro.api.tasks.stop', { task_id: taskId }).catch((err) => {
    console.error('Failed to stop task:', err);
  });
}

export function KanbanCard({ task, onWorkerClick }: KanbanCardProps) {
  const elapsed = useElapsedTime(task.assigned_at);

  const isClickable = task.agent_type === 'worker' && onWorkerClick;
  const isStoppable = task.status === 'assigned' || task.status === 'running';
  const costLabel = formatCost(task);

  return (
    <div
      className={`p-3 bg-cctv-bg rounded border border-cctv-border ${isClickable ? 'cursor-pointer hover:border-cctv-accent/50' : ''}`}
      onClick={isClickable ? (e) => { e.stopPropagation(); onWorkerClick(task.agent_id); } : undefined}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <TaskStatusBadge status={task.status} />
          {isStoppable && (
            <button
              onClick={(e) => handleStop(task.task_id, e)}
              className="w-5 h-5 flex items-center justify-center rounded text-cctv-error/70 hover:text-cctv-error hover:bg-cctv-error/10 border border-transparent hover:border-cctv-error/30 transition-colors"
              title="Stop task"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                <rect x="3" y="3" width="10" height="10" rx="1" />
              </svg>
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {costLabel && (
            <span className="text-xs text-cctv-text-dim">{costLabel}</span>
          )}
          <span className="text-xs text-cctv-text-dim">{elapsed}</span>
        </div>
      </div>
      <p className="text-sm text-cctv-text line-clamp-3 mb-2">{task.prompt}</p>
      <span className="text-xs text-cctv-text-dim font-mono">
        {task.task_id.slice(0, 8)}
      </span>
    </div>
  );
}
