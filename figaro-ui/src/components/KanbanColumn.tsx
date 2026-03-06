import type { WorkerStatus } from '../types';
import { useTasksStore } from '../stores/tasks';
import { WorkerStatusBadge, AgentBadge } from './StatusBadge';
import { KanbanCard } from './KanbanCard';

function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}k`;
  return tokens.toString();
}

function AgentStatsLabel({ agentId }: { agentId: string }) {
  const stats = useTasksStore((state) => state.getAgentTotalStats(agentId));
  const totalTokens = stats.input_tokens + stats.output_tokens;
  if (totalTokens === 0 && stats.cost_usd === 0) return null;

  const parts: string[] = [];
  if (stats.cost_usd > 0) parts.push(`$${stats.cost_usd.toFixed(2)}`);
  if (totalTokens > 0) parts.push(`${formatTokenCount(totalTokens)} tok`);

  return (
    <span className="text-xs text-cctv-text-dim" title={`Input: ${stats.input_tokens.toLocaleString()} | Output: ${stats.output_tokens.toLocaleString()}`}>
      {parts.join(' / ')}
    </span>
  );
}

interface KanbanColumnProps {
  agentId: string;
  agentType: 'worker' | 'supervisor';
  status: WorkerStatus;
  agentConnected?: boolean;
  onWorkerClick?: (workerId: string) => void;
  onColumnClick?: (agentId: string) => void;
}

export function KanbanColumn({ agentId, agentType, status, agentConnected = true, onWorkerClick, onColumnClick }: KanbanColumnProps) {
  const tasks = useTasksStore((state) => state.getTasksByAgentId(agentId));

  const typeBadgeStyle = agentType === 'supervisor'
    ? 'bg-purple-500/20 text-purple-400 border-purple-500/50'
    : 'bg-blue-500/20 text-blue-400 border-blue-500/50';

  const isClickable = !!onColumnClick;

  return (
    <div
      className={`min-w-[280px] flex flex-col bg-cctv-panel rounded-lg border border-cctv-border ${!agentConnected ? 'opacity-50 grayscale' : ''} ${isClickable ? 'cursor-pointer hover:border-cctv-accent/50' : ''}`}
      onClick={isClickable ? () => onColumnClick(agentId) : undefined}
    >
      {/* Header */}
      <div className="p-3 border-b border-cctv-border">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-cctv-text truncate max-w-[140px]" title={agentId}>
            {agentId}
          </span>
          <WorkerStatusBadge status={status} />
          <AgentBadge connected={agentConnected} />
        </div>
        <span className={`px-2 py-0.5 text-xs uppercase tracking-wider border rounded ${typeBadgeStyle}`}>
          {agentType}
        </span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2 min-h-[100px]">
        {tasks.length === 0 ? (
          <div className="flex items-center justify-center h-full text-xs text-cctv-text-dim py-8">
            No active tasks
          </div>
        ) : (
          tasks.map((task) => (
            <KanbanCard key={task.task_id} task={task} onWorkerClick={onWorkerClick} />
          ))
        )}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-cctv-border flex items-center justify-between">
        <span className="text-xs text-cctv-text-dim">
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </span>
        <AgentStatsLabel agentId={agentId} />
      </div>
    </div>
  );
}
