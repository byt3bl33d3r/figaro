import { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { createScheduledTask, updateScheduledTask } from '../api/scheduledTasks';
import { useScheduledTasksStore } from '../stores/scheduledTasks';
import type { ScheduledTask } from '../types';

type IntervalUnit = 'minutes' | 'hours' | 'days' | 'weeks';

interface Props {
  onClose: () => void;
  editTask?: ScheduledTask;
}

function parseInterval(seconds: number): { value: string; unit: IntervalUnit } {
  if (seconds >= 604800 && seconds % 604800 === 0) {
    return { value: String(seconds / 604800), unit: 'weeks' };
  }
  if (seconds >= 86400 && seconds % 86400 === 0) {
    return { value: String(seconds / 86400), unit: 'days' };
  }
  if (seconds >= 3600 && seconds % 3600 === 0) {
    return { value: String(seconds / 3600), unit: 'hours' };
  }
  return { value: String(seconds / 60), unit: 'minutes' };
}

export function ScheduleFormModal({ onClose, editTask }: Props) {
  const initialInterval = editTask ? parseInterval(editTask.interval_seconds) : { value: '60', unit: 'minutes' as IntervalUnit };

  const [name, setName] = useState(editTask?.name ?? '');
  const [startUrl, setStartUrl] = useState(editTask?.start_url ?? '');
  const [prompt, setPrompt] = useState(editTask?.prompt ?? '');
  const [intervalValue, setIntervalValue] = useState(initialInterval.value);
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(initialInterval.unit);
  const [parallelWorkers, setParallelWorkers] = useState(editTask?.parallel_workers?.toString() ?? '1');
  const [maxRuns, setMaxRuns] = useState(editTask?.max_runs?.toString() ?? '');
  const [notifyOnComplete, setNotifyOnComplete] = useState(editTask?.notify_on_complete ?? false);
  const [selfLearning, setSelfLearning] = useState(editTask?.self_learning ?? true);
  const [selfHealing, setSelfHealing] = useState(editTask?.self_healing ?? true);
  const [selfLearningMaxRuns, setSelfLearningMaxRuns] = useState(editTask?.self_learning_max_runs?.toString() ?? '4');
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addTask = useScheduledTasksStore((state) => state.addTask);
  const updateTask = useScheduledTasksStore((state) => state.updateTask);

  const getIntervalSeconds = useCallback(() => {
    const value = parseInt(intervalValue) || 1;
    switch (intervalUnit) {
      case 'minutes':
        return value * 60;
      case 'hours':
        return value * 3600;
      case 'days':
        return value * 86400;
      case 'weeks':
        return value * 604800;
      default:
        return value * 60;
    }
  }, [intervalValue, intervalUnit]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setIsSubmitting(true);

      const parsedParallelWorkers = parseInt(parallelWorkers) || 1;
      const parsedMaxRuns = maxRuns ? parseInt(maxRuns) : null;
      const parsedSelfLearningMaxRuns = selfLearningMaxRuns ? parseInt(selfLearningMaxRuns) : null;

      try {
        if (editTask) {
          // Update existing task
          const updated = await updateScheduledTask(editTask.schedule_id, {
            name,
            prompt,
            start_url: startUrl,
            interval_seconds: getIntervalSeconds(),
            parallel_workers: parsedParallelWorkers,
            max_runs: parsedMaxRuns,
            notify_on_complete: notifyOnComplete,
            self_learning: selfLearning,
            self_healing: selfHealing,
            self_learning_max_runs: parsedSelfLearningMaxRuns,
          });
          updateTask(updated);
        } else {
          // Create new task
          const task = await createScheduledTask({
            name,
            prompt,
            start_url: startUrl,
            interval_seconds: getIntervalSeconds(),
            parallel_workers: parsedParallelWorkers,
            max_runs: parsedMaxRuns,
            notify_on_complete: notifyOnComplete,
            self_learning: selfLearning,
            self_healing: selfHealing,
            self_learning_max_runs: parsedSelfLearningMaxRuns,
          });
          addTask(task);
        }
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to ${editTask ? 'update' : 'create'} scheduled task`);
      } finally {
        setIsSubmitting(false);
      }
    },
    [name, startUrl, prompt, getIntervalSeconds, parallelWorkers, maxRuns, notifyOnComplete, selfLearning, selfHealing, selfLearningMaxRuns, addTask, updateTask, onClose, editTask]
  );

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-cctv-panel border border-cctv-border rounded-lg w-full max-w-lg mx-4 shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-cctv-border">
          <h2 className="text-lg font-semibold text-cctv-text">
            {editTask ? 'Edit Scheduled Task' : 'Schedule Recurring Task'}
          </h2>
          <button
            onClick={onClose}
            className="text-cctv-text-dim hover:text-cctv-text transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Task Name */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">Task Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Daily price check"
              required
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
            />
          </div>

          {/* Start URL */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">Start URL</label>
            <input
              type="url"
              value={startUrl}
              onChange={(e) => setStartUrl(e.target.value)}
              placeholder="https://example.com"
              required
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
            />
          </div>

          {/* Task Description */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">
              Task Description
              <span className="text-xs text-cctv-text-dim ml-2">click to expand editor</span>
            </label>
            <div
              onClick={() => setPromptEditorOpen(true)}
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text cursor-pointer hover:border-cctv-accent transition-colors min-h-[4.5rem] max-h-32 overflow-y-auto"
            >
              {prompt ? (
                <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-headings:my-1">
                  <ReactMarkdown>{prompt}</ReactMarkdown>
                </div>
              ) : (
                <span className="text-cctv-text-dim">Describe what the agent should do...</span>
              )}
            </div>
            {/* Hidden input for form validation */}
            <input type="text" value={prompt} required className="sr-only" tabIndex={-1} onChange={() => {}} />
          </div>

          {/* Fullscreen Prompt Editor Modal */}
          {promptEditorOpen && (
            <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-[60]" onClick={() => setPromptEditorOpen(false)}>
              <div className="bg-cctv-panel border border-cctv-border rounded-lg w-full max-w-5xl mx-4 h-[80vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
                {/* Editor Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-cctv-border shrink-0">
                  <h3 className="text-lg font-semibold text-cctv-text">Task Description</h3>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-cctv-text-dim">Supports Markdown</span>
                    <button
                      type="button"
                      onClick={() => setPromptEditorOpen(false)}
                      className="text-cctv-text-dim hover:text-cctv-text transition-colors"
                    >
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* Editor Body: side-by-side edit + preview */}
                <div className="flex-1 flex min-h-0">
                  {/* Edit pane */}
                  <div className="flex-1 flex flex-col border-r border-cctv-border min-w-0">
                    <div className="px-3 py-1.5 border-b border-cctv-border shrink-0">
                      <span className="text-xs font-medium text-cctv-text-dim uppercase tracking-wide">Edit</span>
                    </div>
                    <textarea
                      data-testid="prompt-editor"
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      placeholder="Describe what the agent should do...&#10;&#10;Supports **Markdown** formatting."
                      autoFocus
                      className="flex-1 w-full bg-cctv-bg px-4 py-3 text-sm text-cctv-text placeholder-cctv-text-dim resize-none focus:outline-none font-mono"
                    />
                  </div>

                  {/* Preview pane */}
                  <div className="flex-1 flex flex-col min-w-0">
                    <div className="px-3 py-1.5 border-b border-cctv-border shrink-0">
                      <span className="text-xs font-medium text-cctv-text-dim uppercase tracking-wide">Preview</span>
                    </div>
                    <div className="flex-1 overflow-y-auto px-4 py-3">
                      {prompt ? (
                        <div className="prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown>{prompt}</ReactMarkdown>
                        </div>
                      ) : (
                        <span className="text-sm text-cctv-text-dim italic">Nothing to preview</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Editor Footer */}
                <div className="flex justify-end px-4 py-3 border-t border-cctv-border shrink-0">
                  <button
                    type="button"
                    onClick={() => setPromptEditorOpen(false)}
                    className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim transition-colors"
                  >
                    Done
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Interval */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">Run Every</label>
            <div className="flex gap-2">
              <input
                type="number"
                min="1"
                value={intervalValue}
                onChange={(e) => setIntervalValue(e.target.value)}
                required
                className="flex-1 bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
              />
              <select
                value={intervalUnit}
                onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
                className="bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
              >
                <option value="minutes">Minutes</option>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
                <option value="weeks">Weeks</option>
              </select>
            </div>
          </div>

          {/* Parallel Workers */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">Parallel Workers</label>
            <input
              type="number"
              min="1"
              max="10"
              value={parallelWorkers}
              onChange={(e) => setParallelWorkers(e.target.value)}
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
            />
            <p className="text-xs text-cctv-text-dim mt-1">
              Number of workers to run this task on simultaneously
            </p>
          </div>

          {/* Max Runs */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">Max Runs (optional)</label>
            <input
              type="number"
              min="1"
              value={maxRuns}
              onChange={(e) => setMaxRuns(e.target.value)}
              placeholder="Unlimited"
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
            />
            <p className="text-xs text-cctv-text-dim mt-1">
              Auto-pause after this many runs (leave empty for unlimited)
            </p>
          </div>

          {/* Notify on Complete */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-cctv-text cursor-pointer">
              <input
                type="checkbox"
                checked={notifyOnComplete}
                onChange={(e) => setNotifyOnComplete(e.target.checked)}
                className="w-4 h-4 rounded border-cctv-border bg-cctv-bg text-cctv-accent focus:ring-cctv-accent focus:ring-offset-0"
              />
              Notify on completion via Gateway
            </label>
            <p className="text-xs text-cctv-text-dim mt-1 ml-6">
              Send a notification to configured gateway channels when this task completes or fails
            </p>
          </div>

          {/* Self-Learning */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-cctv-text cursor-pointer">
              <input
                type="checkbox"
                checked={selfLearning}
                onChange={(e) => setSelfLearning(e.target.checked)}
                className="w-4 h-4 rounded border-cctv-border bg-cctv-bg text-cctv-accent focus:ring-cctv-accent focus:ring-offset-0"
              />
              Self-Learning
            </label>
            <p className="text-xs text-cctv-text-dim mt-1 ml-6">
              Automatically optimize prompt after each run
            </p>
          </div>

          {/* Max Learning Runs (shown when self-learning is enabled) */}
          {selfLearning && (
            <div className="ml-6">
              <label className="block text-sm font-medium text-cctv-text mb-1">Max Learning Runs (optional)</label>
              <input
                type="number"
                min="1"
                value={selfLearningMaxRuns}
                onChange={(e) => setSelfLearningMaxRuns(e.target.value)}
                placeholder="Unlimited"
                className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
              />
              <p className="text-xs text-cctv-text-dim mt-1">
                Stop optimizing prompt after this many learning runs (leave empty for unlimited)
              </p>
            </div>
          )}

          {/* Self-Healing */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-cctv-text cursor-pointer">
              <input
                type="checkbox"
                checked={selfHealing}
                onChange={(e) => setSelfHealing(e.target.checked)}
                className="w-4 h-4 rounded border-cctv-border bg-cctv-bg text-cctv-accent focus:ring-cctv-accent focus:ring-offset-0"
              />
              Self-Healing
            </label>
            <p className="text-xs text-cctv-text-dim mt-1 ml-6">
              Automatically retry failed tasks with supervisor analysis
            </p>
          </div>

          {/* Error */}
          {error && <div className="text-red-400 text-sm">{error}</div>}

          {/* Actions */}
          <div className="flex gap-2 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-cctv-text hover:text-cctv-text-dim transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim disabled:opacity-50 transition-colors"
            >
              {isSubmitting ? (editTask ? 'Saving...' : 'Creating...') : (editTask ? 'Save Changes' : 'Create Schedule')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
