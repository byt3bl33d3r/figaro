import { useState, useCallback, useRef, useEffect } from 'react';
import { useWorkersStore } from '../stores/workers';
import { useSupervisorsStore } from '../stores/supervisors';
import { natsManager } from '../api/nats';
import type { TaskTarget } from '../types';

export function ChatInput() {
  const [message, setMessage] = useState('');
  const [selectedWorkerId, setSelectedWorkerId] = useState<string>('');
  const [taskTarget, setTaskTarget] = useState<TaskTarget>('auto');
  const workers = useWorkersStore((state) => state.getWorkersList());
  const hasSupervisor = useSupervisorsStore((state) => state.hasSupervisor());
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [message]);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!message.trim()) return;

      const options: Record<string, unknown> = { target: taskTarget };
      if (taskTarget === 'worker' && selectedWorkerId) {
        options.worker_id = selectedWorkerId;
      }
      natsManager
        .request('figaro.api.tasks.create', { prompt: message.trim(), options })
        .catch((err) => console.error('Failed to submit task:', err));
      setMessage('');
    },
    [message, selectedWorkerId, taskTarget]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e);
      }
    },
    [handleSubmit]
  );

  const idleWorkers = workers.filter((w) => w.status === 'idle');
  const hasIdleWorker = idleWorkers.length > 0 || workers.length === 0;
  // For 'auto' mode, we can submit if either supervisor or worker is available
  const canSubmit =
    taskTarget === 'supervisor'
      ? hasSupervisor
      : taskTarget === 'auto'
        ? hasSupervisor || hasIdleWorker
        : hasIdleWorker;

  return (
    <form onSubmit={handleSubmit} className="border-t border-cctv-border bg-cctv-panel p-3">
      {/* Target selector (Worker vs Supervisor) */}
      <div className="mb-2 flex gap-2">
        <select
          value={taskTarget}
          onChange={(e) => setTaskTarget(e.target.value as TaskTarget)}
          className="bg-cctv-bg border border-cctv-border rounded px-2 py-1.5 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
        >
          <option value="auto">Auto (Supervisor decides)</option>
          <option value="supervisor" disabled={!hasSupervisor}>
            Via Supervisor {!hasSupervisor && '(unavailable)'}
          </option>
          <option value="worker">Direct to Worker</option>
        </select>

        {/* Worker selector (only shown when targeting worker) */}
        {taskTarget === 'worker' && (
          <select
            value={selectedWorkerId}
            onChange={(e) => setSelectedWorkerId(e.target.value)}
            className="flex-1 bg-cctv-bg border border-cctv-border rounded px-2 py-1.5 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
          >
            <option value="">Any idle worker</option>
            {workers.map((w) => (
              <option key={w.id} value={w.id} disabled={w.status === 'busy'}>
                {w.id.slice(0, 8)} ({w.status})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Message input */}
      <div className="flex gap-2">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={canSubmit ? 'Type a task...' : (taskTarget === 'supervisor' ? 'No supervisor available...' : 'All workers busy...')}
          disabled={!canSubmit}
          rows={1}
          className="flex-1 bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim resize-none focus:outline-none focus:border-cctv-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!message.trim() || !canSubmit}
          className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Send
        </button>
      </div>

      {/* Help text */}
      <div className="mt-2 text-xs text-cctv-text-dim">
        Press Enter to send, Shift+Enter for new line
      </div>
    </form>
  );
}
