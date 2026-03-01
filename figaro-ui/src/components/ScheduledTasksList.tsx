import { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import { useScheduledTasksStore } from '../stores/scheduledTasks';
import {
  fetchScheduledTasks,
  toggleScheduledTask,
  deleteScheduledTask,
  triggerScheduledTask,
} from '../api/scheduledTasks';
import { ScheduleFormModal } from './ScheduleFormModal';
import type { ScheduledTask } from '../types';

export function ScheduledTasksList() {
  const tasks = useScheduledTasksStore((state) => state.getTasksList());
  const setTasks = useScheduledTasksStore((state) => state.setTasks);
  const updateTask = useScheduledTasksStore((state) => state.updateTask);
  const removeTask = useScheduledTasksStore((state) => state.removeTask);
  const hasFetched = useRef(false);
  const [isLoading, setIsLoading] = useState(!hasFetched.current);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [expandedTask, setExpandedTask] = useState<string | null>(null);

  useEffect(() => {
    if (hasFetched.current) return;
    hasFetched.current = true;
    fetchScheduledTasks()
      .then(setTasks)
      .catch((err) => console.error('Failed to fetch scheduled tasks:', err))
      .finally(() => setIsLoading(false));
  }, [setTasks]);

  const handleToggle = async (task: ScheduledTask) => {
    try {
      const updated = await toggleScheduledTask(task.schedule_id);
      updateTask(updated);
    } catch (err) {
      console.error('Failed to toggle scheduled task:', err);
    }
  };

  const handleTrigger = async (task: ScheduledTask) => {
    try {
      await triggerScheduledTask(task.schedule_id);
    } catch (err) {
      console.error('Failed to trigger scheduled task:', err);
    }
  };

  const handleDelete = async (scheduleId: string) => {
    if (!confirm('Delete this scheduled task?')) return;
    try {
      await deleteScheduledTask(scheduleId);
      removeTask(scheduleId);
    } catch (err) {
      console.error('Failed to delete scheduled task:', err);
    }
  };

  const formatInterval = (seconds: number) => {
    if (seconds >= 604800) {
      const weeks = seconds / 604800;
      return `${weeks}w`;
    }
    if (seconds >= 86400) {
      const days = seconds / 86400;
      return `${days}d`;
    }
    if (seconds >= 3600) {
      const hours = seconds / 3600;
      return `${hours}h`;
    }
    return `${seconds / 60}m`;
  };

  const formatNextRun = (isoString: string | null) => {
    if (!isoString) return 'Not scheduled';
    // Backend sends UTC time with timezone offset (+00:00)
    // JavaScript Date constructor handles this correctly
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffSecs = Math.round(diffMs / 1000);
    if (diffSecs < 60) return 'Any moment';
    const diffMins = Math.round(diffSecs / 60);
    if (diffMins < 60) return `in ${diffMins}m`;
    const diffHours = Math.floor(diffMins / 60);
    const remainingMins = diffMins % 60;
    if (diffHours < 24) {
      return remainingMins > 0 ? `in ${diffHours}h ${remainingMins}m` : `in ${diffHours}h`;
    }
    const diffDays = Math.floor(diffHours / 24);
    const remainingHours = diffHours % 24;
    return remainingHours > 0 ? `in ${diffDays}d ${remainingHours}h` : `in ${diffDays}d`;
  };

  if (isLoading) {
    return <div className="text-cctv-text-dim text-sm p-4">Loading...</div>;
  }

  if (tasks.length === 0) {
    return (
      <div className="text-cctv-text-dim text-sm p-4 text-center">
        No scheduled tasks yet.
        <br />
        Click "Schedule" to create one.
      </div>
    );
  }

  return (
    <div className="space-y-2 p-2">
      {tasks.map((task) => (
        <div
          key={task.schedule_id}
          className={`p-3 bg-cctv-bg rounded border ${
            task.enabled ? 'border-cctv-border' : 'border-cctv-border opacity-50'
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <div
              className="flex-1 min-w-0 cursor-pointer"
              onClick={() => setExpandedTask(expandedTask === task.schedule_id ? null : task.schedule_id)}
            >
              <div className="font-medium text-sm text-cctv-text truncate">{task.name}</div>
              <div className="text-xs text-cctv-text-dim truncate mt-0.5">{task.start_url}</div>
              <div className="text-xs text-cctv-text-dim mt-1">
                Every {formatInterval(task.interval_seconds)} | Next:{' '}
                {task.enabled ? formatNextRun(task.next_run_at) : 'Paused'}
              </div>
              {(task.run_count > 0 || task.max_runs !== null) && (
                <div className="text-xs text-cctv-accent mt-0.5">
                  Runs: {task.run_count}{task.max_runs !== null ? `/${task.max_runs}` : ''}
                  {task.max_runs !== null && task.run_count >= task.max_runs && !task.enabled && (
                    <span className="text-yellow-400 ml-1">(Auto-paused)</span>
                  )}
                </div>
              )}
              {task.parallel_workers > 1 && (
                <div className="text-xs text-blue-400 mt-0.5">
                  {task.parallel_workers} workers
                </div>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleTrigger(task)}
                className="p-1.5 rounded text-cctv-text-dim hover:text-cctv-accent hover:bg-cctv-accent/10"
                title="Run now"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13 10V3L4 14h7v7l9-11h-7z"
                  />
                </svg>
              </button>
              <button
                onClick={() => setEditingTask(task)}
                className="p-1.5 rounded text-cctv-text-dim hover:text-cctv-text hover:bg-cctv-border"
                title="Edit"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                  />
                </svg>
              </button>
              <button
                onClick={() => handleToggle(task)}
                className={`p-1.5 rounded ${
                  task.enabled
                    ? 'text-green-400 hover:bg-green-400/10'
                    : 'text-cctv-text-dim hover:bg-cctv-border'
                }`}
                title={task.enabled ? 'Pause' : 'Resume'}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  {task.enabled ? (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  ) : (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  )}
                </svg>
              </button>
              <button
                onClick={() => handleDelete(task.schedule_id)}
                className="p-1.5 rounded text-red-400 hover:bg-red-400/10"
                title="Delete"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                  />
                </svg>
              </button>
            </div>
          </div>
          {expandedTask === task.schedule_id && (
            <div className="mt-2 pt-2 border-t border-cctv-border">
              <div className="text-xs text-cctv-text prose prose-invert prose-xs max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0 [&_h1]:text-sm [&_h2]:text-xs [&_h3]:text-xs [&_h1]:my-1 [&_h2]:my-1 [&_h3]:my-1 [&_pre]:my-1 [&_pre]:text-[11px] [&_code]:text-[11px]">
                <Markdown>{task.prompt}</Markdown>
              </div>
            </div>
          )}
        </div>
      ))}

      {editingTask && (
        <ScheduleFormModal
          editTask={editingTask}
          onClose={() => setEditingTask(null)}
        />
      )}
    </div>
  );
}
