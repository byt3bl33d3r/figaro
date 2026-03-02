import type { ActiveTask } from '../types';
import { TaskStatusBadge } from './StatusBadge';
import { useElapsedTime } from '../hooks/useElapsedTime';

interface KanbanCardProps {
  task: ActiveTask;
  onWorkerClick?: (workerId: string) => void;
}

export function KanbanCard({ task, onWorkerClick }: KanbanCardProps) {
  const elapsed = useElapsedTime(task.assigned_at);

  const isClickable = task.agent_type === 'worker' && onWorkerClick;

  return (
    <div
      className={`p-3 bg-cctv-bg rounded border border-cctv-border ${isClickable ? 'cursor-pointer hover:border-cctv-accent/50' : ''}`}
      onClick={isClickable ? () => onWorkerClick(task.agent_id) : undefined}
    >
      <div className="flex items-center justify-between mb-2">
        <TaskStatusBadge status={task.status} />
        <span className="text-xs text-cctv-text-dim">{elapsed}</span>
      </div>
      <p className="text-sm text-cctv-text line-clamp-3 mb-2">{task.prompt}</p>
      <span className="text-xs text-cctv-text-dim font-mono">
        {task.task_id.slice(0, 8)}
      </span>
    </div>
  );
}
