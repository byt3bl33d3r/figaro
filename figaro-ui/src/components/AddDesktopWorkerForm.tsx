import { useState, useCallback } from 'react';
import { registerDesktopWorker, updateDesktopWorker } from '../api/desktopWorkers';
import type { Worker } from '../types';

interface AddDesktopWorkerFormProps {
  onClose: () => void;
  worker?: Worker;
}

/**
 * Reconstruct a URL with embedded credentials for display in the edit form.
 */
function buildUrlWithCredentials(url: string, username?: string, password?: string): string {
  if (!username && !password) return url;
  try {
    const parsed = new URL(url);
    if (username) parsed.username = username;
    if (password) parsed.password = password;
    return parsed.toString();
  } catch {
    return url;
  }
}

/**
 * Parse credentials and host from a URL.
 * Supports: https://user:pass@host:port/path, vnc://user:pass@host:port, etc.
 * Returns the cleaned URL (without credentials) and extracted username/password.
 */
function parseUrlCredentials(rawUrl: string): { url: string; username?: string; password?: string } {
  try {
    const parsed = new URL(rawUrl);
    const username = parsed.username ? decodeURIComponent(parsed.username) : undefined;
    const password = parsed.password ? decodeURIComponent(parsed.password) : undefined;
    if (parsed.username || parsed.password) {
      parsed.username = '';
      parsed.password = '';
    }
    return { url: parsed.toString(), username, password };
  } catch {
    // Not a valid URL, return as-is
    return { url: rawUrl };
  }
}

export function AddDesktopWorkerForm({ onClose, worker }: AddDesktopWorkerFormProps) {
  const isEdit = !!worker;
  const [workerId, setWorkerId] = useState(worker?.id ?? '');
  const [novncUrl, setNovncUrl] = useState(
    isEdit && worker
      ? buildUrlWithCredentials(worker.novnc_url ?? '', worker.vnc_username, worker.vnc_password)
      : ''
  );
  const [os, setOs] = useState(worker?.metadata?.os ?? 'linux');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setIsSubmitting(true);

      try {
        const { url, username, password } = parseUrlCredentials(novncUrl.trim());
        if (isEdit && worker) {
          const newId = workerId.trim() !== worker.id ? workerId.trim() : undefined;
          await updateDesktopWorker(worker.id, newId, url, { os }, password, username);
        } else {
          await registerDesktopWorker(workerId.trim(), url, { os }, password, username);
        }
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : isEdit ? 'Failed to update desktop worker' : 'Failed to register desktop worker');
      } finally {
        setIsSubmitting(false);
      }
    },
    [workerId, novncUrl, os, onClose, isEdit, worker]
  );

  return (
    <div className="bg-cctv-panel border border-cctv-border rounded-lg mx-4 mb-4 shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-cctv-border">
        <h2 className="text-sm font-semibold text-cctv-text uppercase tracking-wider">
          {isEdit ? 'Edit Desktop Worker' : 'Add Desktop Worker'}
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
        <div className="flex gap-4">
          {/* Worker ID */}
          <div className="flex-1">
            <label className="block text-sm font-medium text-cctv-text mb-1">Worker ID</label>
            <input
              type="text"
              value={workerId}
              onChange={(e) => setWorkerId(e.target.value)}
              placeholder="e.g., desktop-01"
              required
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
            />
          </div>

          {/* noVNC URL */}
          <div className="flex-1">
            <label className="block text-sm font-medium text-cctv-text mb-1">Desktop URL</label>
            <input
              type="text"
              value={novncUrl}
              onChange={(e) => setNovncUrl(e.target.value)}
              placeholder="vnc://user:pass@host:5901"
              required
              className="w-full bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
            />
            <span className="text-[10px] text-cctv-text-dim mt-0.5 block">
              vnc:// (direct TCP) or ws:// (WebSocket) — credentials extracted automatically
            </span>
          </div>

          {/* OS */}
          <div>
            <label className="block text-sm font-medium text-cctv-text mb-1">OS</label>
            <select
              value={os}
              onChange={(e) => setOs(e.target.value)}
              className="bg-cctv-bg border border-cctv-border rounded px-3 py-2 text-sm text-cctv-text focus:outline-none focus:border-cctv-accent"
            >
              <option value="linux">Linux</option>
              <option value="macos">macOS</option>
              <option value="windows">Windows</option>
            </select>
          </div>
        </div>

        {/* Error */}
        {error && <div className="text-red-400 text-sm">{error}</div>}

        {/* Actions */}
        <div className="flex gap-2 justify-end">
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
            {isSubmitting ? (isEdit ? 'Saving...' : 'Adding...') : (isEdit ? 'Save Changes' : 'Add Worker')}
          </button>
        </div>
      </form>
    </div>
  );
}
