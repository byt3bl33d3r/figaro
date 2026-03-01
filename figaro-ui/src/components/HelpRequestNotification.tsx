import { useState, useRef, useEffect } from 'react';
import { useHelpRequestsStore } from '../stores/helpRequests';
import { natsManager } from '../api/nats';
import type { HelpRequest } from '../types';

interface HelpRequestNotificationProps {
  onSelectWorker: (workerId: string) => void;
}

export function HelpRequestNotification({ onSelectWorker }: HelpRequestNotificationProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const pendingRequests = useHelpRequestsStore((state) => state.getPendingRequests());
  const allRequests = useHelpRequestsStore((state) => Array.from(state.requests.values()));
  const updateRequestStatus = useHelpRequestsStore((state) => state.updateRequestStatus);
  const setActiveRequestId = useHelpRequestsStore((state) => state.setActiveRequestId);

  // Get recent requests (pending first, then last 5 others)
  const recentNonPending = allRequests
    .filter((r) => r.status !== 'pending')
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  const displayRequests = [...pendingRequests, ...recentNonPending];
  const hasPending = pendingRequests.length > 0;

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const handleRequestClick = (request: HelpRequest) => {
    if (request.status === 'pending') {
      setActiveRequestId(request.request_id);
    } else {
      onSelectWorker(request.worker_id);
    }
    setIsOpen(false);
  };

  const handleDismissAll = async () => {
    if (pendingRequests.length === 0 || isDismissing) return;

    setIsDismissing(true);
    try {
      // Dismiss all pending requests in parallel
      await Promise.all(
        pendingRequests.map(async (request) => {
          try {
            await natsManager.request('figaro.api.help-requests.dismiss', {
              request_id: request.request_id,
            });
            updateRequestStatus(request.request_id, 'cancelled', 'ui');
          } catch (error) {
            console.error(`Failed to dismiss request ${request.request_id}:`, error);
          }
        })
      );
    } finally {
      setIsDismissing(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Notification Bell Icon */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`relative p-2 rounded-lg transition-colors ${
          hasPending
            ? 'text-amber-400 hover:bg-amber-500/10'
            : 'text-cctv-text-dim hover:bg-cctv-border hover:text-cctv-text'
        }`}
        title={hasPending ? `${pendingRequests.length} pending help request(s)` : 'Help requests'}
      >
        {/* Bell Icon */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-5 w-5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>

        {/* Badge for pending count */}
        {hasPending && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"></span>
            <span className="relative inline-flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white">
              {pendingRequests.length > 9 ? '9+' : pendingRequests.length}
            </span>
          </span>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 bg-cctv-panel border border-cctv-border rounded-lg shadow-lg z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-cctv-border">
            <h3 className="text-sm font-medium text-cctv-text">
              Help Requests
              {hasPending && (
                <span className="ml-2 px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded">
                  {pendingRequests.length} pending
                </span>
              )}
            </h3>
          </div>

          {/* Request List */}
          <div className="max-h-96 overflow-y-auto">
            {displayRequests.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-cctv-text-dim">
                No help requests
              </div>
            ) : (
              displayRequests.map((request) => (
                <HelpRequestItem
                  key={request.request_id}
                  request={request}
                  onClick={() => handleRequestClick(request)}
                />
              ))
            )}
          </div>

          {/* Dismiss All Footer */}
          {hasPending && (
            <div className="px-4 py-3 border-t border-cctv-border">
              <button
                onClick={handleDismissAll}
                disabled={isDismissing}
                className="w-full px-3 py-2 text-sm font-medium text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isDismissing ? 'Dismissing...' : `Dismiss All (${pendingRequests.length})`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface HelpRequestItemProps {
  request: HelpRequest;
  onClick: () => void;
}

function HelpRequestItem({ request, onClick }: HelpRequestItemProps) {
  const isPending = request.status === 'pending';
  const firstQuestion = request.questions[0];

  // Calculate time ago
  const createdAt = new Date(request.created_at);
  const now = new Date();
  const diffMs = now.getTime() - createdAt.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const timeAgo = diffMins < 1 ? 'just now' :
                  diffMins < 60 ? `${diffMins}m ago` :
                  `${Math.floor(diffMins / 60)}h ago`;

  return (
    <button
      onClick={onClick}
      className={`w-full px-4 py-3 text-left hover:bg-cctv-border/50 transition-colors border-b border-cctv-border/50 last:border-b-0 ${
        isPending ? 'bg-amber-500/5' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* Status indicator + Worker ID */}
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
              request.status === 'pending' ? 'bg-amber-400 animate-pulse' :
              request.status === 'responded' ? 'bg-green-400' :
              request.status === 'timeout' ? 'bg-red-400' :
              'bg-gray-400'
            }`} />
            <span className="text-xs font-medium text-cctv-text truncate">
              Worker {request.worker_id.slice(0, 8)}
            </span>
            <StatusBadge status={request.status} />
          </div>

          {/* Question preview */}
          {firstQuestion && (
            <p className="text-xs text-cctv-text-dim truncate">
              {firstQuestion.header}: {firstQuestion.question}
            </p>
          )}
        </div>

        {/* Time */}
        <span className="text-[10px] text-cctv-text-dim whitespace-nowrap">
          {timeAgo}
        </span>
      </div>
    </button>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-500/20 text-amber-400',
    responded: 'bg-green-500/20 text-green-400',
    timeout: 'bg-red-500/20 text-red-400',
    cancelled: 'bg-gray-500/20 text-gray-400',
  };

  return (
    <span className={`px-1.5 py-0.5 text-[10px] rounded ${colors[status] || colors.cancelled}`}>
      {status}
    </span>
  );
}
