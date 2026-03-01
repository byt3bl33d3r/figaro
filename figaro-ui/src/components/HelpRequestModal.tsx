import { useState, useCallback, useEffect } from 'react';
import { natsManager } from '../api/nats';
import { useHelpRequestsStore } from '../stores/helpRequests';

interface Props {
  requestId: string;
  onClose: () => void;
}

export function HelpRequestModal({ requestId, onClose }: Props) {
  const getRequest = useHelpRequestsStore((state) => state.getRequest);
  const updateRequestStatus = useHelpRequestsStore((state) => state.updateRequestStatus);

  const request = getRequest(requestId);

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);

  // Countdown timer
  useEffect(() => {
    if (!request || request.status !== 'pending') return;

    const createdAt = new Date(request.created_at).getTime();
    const timeoutMs = request.timeout_seconds * 1000;

    const updateRemaining = () => {
      const now = Date.now();
      const elapsed = now - createdAt;
      const remaining = Math.max(0, Math.floor((timeoutMs - elapsed) / 1000));
      setTimeRemaining(remaining);
    };

    updateRemaining();
    const interval = setInterval(updateRemaining, 1000);

    return () => clearInterval(interval);
  }, [request]);

  const formatTime = useCallback((seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }, []);

  const handleOptionChange = useCallback(
    (questionText: string, optionLabel: string, multiSelect: boolean, checked: boolean) => {
      setAnswers((prev) => {
        if (!multiSelect) {
          return { ...prev, [questionText]: optionLabel };
        }
        // Multi-select: manage comma-separated list
        const current = prev[questionText] ? prev[questionText].split(', ') : [];
        let updated: string[];
        if (checked) {
          // If selecting a non-Other option, just add it
          if (optionLabel === 'Other') {
            updated = current.filter((l) => !l.startsWith('Other'));
            const otherText = otherTexts[questionText];
            updated.push(otherText ? `Other: ${otherText}` : 'Other');
          } else {
            updated = [...current.filter((l) => l !== optionLabel), optionLabel];
          }
        } else {
          if (optionLabel === 'Other') {
            updated = current.filter((l) => !l.startsWith('Other'));
          } else {
            updated = current.filter((l) => l !== optionLabel);
          }
        }
        return { ...prev, [questionText]: updated.join(', ') };
      });
    },
    [otherTexts]
  );

  const handleOtherTextChange = useCallback(
    (questionText: string, text: string, multiSelect: boolean) => {
      setOtherTexts((prev) => ({ ...prev, [questionText]: text }));
      // Update the answer to reflect the new other text
      setAnswers((prev) => {
        const currentAnswer = prev[questionText] || '';
        if (!multiSelect) {
          // Single select: if Other is selected, update it
          if (currentAnswer === 'Other' || currentAnswer.startsWith('Other:')) {
            return { ...prev, [questionText]: text ? `Other: ${text}` : 'Other' };
          }
          return prev;
        }
        // Multi-select: update the Other entry in the comma list
        const parts = currentAnswer.split(', ').filter(Boolean);
        const hasOther = parts.some((p) => p === 'Other' || p.startsWith('Other:'));
        if (hasOther) {
          const updated = parts
            .filter((p) => !p.startsWith('Other'))
            .concat(text ? `Other: ${text}` : 'Other');
          return { ...prev, [questionText]: updated.join(', ') };
        }
        return prev;
      });
    },
    []
  );

  const isOtherSelected = useCallback(
    (questionText: string, multiSelect: boolean): boolean => {
      const answer = answers[questionText] || '';
      if (!multiSelect) {
        return answer === 'Other' || answer.startsWith('Other:');
      }
      return answer.split(', ').some((p) => p === 'Other' || p.startsWith('Other:'));
    },
    [answers]
  );

  const isOptionSelected = useCallback(
    (questionText: string, optionLabel: string, multiSelect: boolean): boolean => {
      const answer = answers[questionText] || '';
      if (!multiSelect) {
        return answer === optionLabel;
      }
      return answer.split(', ').includes(optionLabel);
    },
    [answers]
  );

  const handleSubmit = useCallback(async () => {
    setError(null);
    setIsSubmitting(true);

    try {
      await natsManager.request('figaro.api.help-requests.respond', {
        request_id: requestId,
        answers,
        source: 'ui',
      });
      updateRequestStatus(requestId, 'responded', 'ui');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit response');
    } finally {
      setIsSubmitting(false);
    }
  }, [requestId, answers, updateRequestStatus, onClose]);

  const handleDismiss = useCallback(async () => {
    setError(null);
    setIsDismissing(true);

    try {
      await natsManager.request('figaro.api.help-requests.dismiss', {
        request_id: requestId,
      });
      updateRequestStatus(requestId, 'cancelled', 'ui');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dismiss request');
    } finally {
      setIsDismissing(false);
    }
  }, [requestId, updateRequestStatus, onClose]);

  const allQuestionsAnswered =
    request?.questions.every((q) => {
      const answer = answers[q.question];
      return answer && answer.trim().length > 0;
    }) ?? false;

  // Request not found or no longer pending
  if (!request || request.status !== 'pending') {
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[60]">
        <div className="bg-cctv-panel border border-cctv-border rounded-lg w-full max-w-lg mx-4 shadow-xl">
          <div className="p-6 text-center">
            <p className="text-cctv-text-dim mb-4">
              This help request is no longer available.
            </p>
            <button
              onClick={onClose}
              className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[60]">
      <div className="bg-cctv-panel border border-cctv-border rounded-lg w-full max-w-2xl mx-4 shadow-xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-cctv-border shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-cctv-text">Help Request</h2>
            <div className="flex items-center gap-3 mt-1 text-xs text-cctv-text-dim">
              <span>
                Worker: <span className="text-cctv-text font-mono">{request.worker_id.slice(0, 8)}</span>
              </span>
              <span>
                Task: <span className="text-cctv-text font-mono">{request.task_id.slice(0, 8)}</span>
              </span>
              {timeRemaining !== null && (
                <span className={timeRemaining <= 30 ? 'text-red-400' : ''}>
                  Time remaining: {formatTime(timeRemaining)}
                </span>
              )}
            </div>
          </div>
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

        {/* Questions */}
        <div className="p-4 space-y-6 overflow-y-auto">
          {request.questions.map((question, qIndex) => (
            <div key={qIndex}>
              {/* Question header tag */}
              <span className="inline-block bg-cctv-accent/20 text-cctv-accent text-xs font-medium px-2 py-0.5 rounded mb-2">
                {question.header}
              </span>
              {/* Question text */}
              <p className="text-sm text-cctv-text mb-3">{question.question}</p>

              {/* Options */}
              <div className="space-y-2 ml-1">
                {question.options.map((option, oIndex) => (
                  <label
                    key={oIndex}
                    className="flex items-start gap-2 cursor-pointer group"
                  >
                    <input
                      type={question.multiSelect ? 'checkbox' : 'radio'}
                      name={`question-${qIndex}`}
                      checked={isOptionSelected(question.question, option.label, question.multiSelect)}
                      onChange={(e) =>
                        handleOptionChange(
                          question.question,
                          option.label,
                          question.multiSelect,
                          e.target.checked
                        )
                      }
                      className="mt-0.5 w-4 h-4 rounded border-cctv-border bg-cctv-bg text-cctv-accent focus:ring-cctv-accent focus:ring-offset-0"
                    />
                    <div>
                      <span className="text-sm text-cctv-text group-hover:text-cctv-accent transition-colors">
                        {option.label}
                      </span>
                      {option.description && (
                        <p className="text-xs text-cctv-text-dim mt-0.5">
                          {option.description}
                        </p>
                      )}
                    </div>
                  </label>
                ))}

                {/* Other option */}
                <label className="flex items-start gap-2 cursor-pointer group">
                  <input
                    type={question.multiSelect ? 'checkbox' : 'radio'}
                    name={`question-${qIndex}`}
                    checked={isOtherSelected(question.question, question.multiSelect)}
                    onChange={(e) =>
                      handleOptionChange(
                        question.question,
                        'Other',
                        question.multiSelect,
                        e.target.checked
                      )
                    }
                    className="mt-0.5 w-4 h-4 rounded border-cctv-border bg-cctv-bg text-cctv-accent focus:ring-cctv-accent focus:ring-offset-0"
                  />
                  <div className="flex-1">
                    <span className="text-sm text-cctv-text group-hover:text-cctv-accent transition-colors">
                      Other
                    </span>
                    {isOtherSelected(question.question, question.multiSelect) && (
                      <input
                        type="text"
                        value={otherTexts[question.question] || ''}
                        onChange={(e) =>
                          handleOtherTextChange(
                            question.question,
                            e.target.value,
                            question.multiSelect
                          )
                        }
                        placeholder="Specify..."
                        autoFocus
                        className="mt-1 w-full bg-cctv-bg border border-cctv-border rounded px-3 py-1.5 text-sm text-cctv-text placeholder-cctv-text-dim focus:outline-none focus:border-cctv-accent"
                      />
                    )}
                  </div>
                </label>
              </div>
            </div>
          ))}

          {/* Error */}
          {error && <div className="text-red-400 text-sm">{error}</div>}
        </div>

        {/* Actions */}
        <div className="flex gap-2 justify-between px-4 py-3 border-t border-cctv-border shrink-0">
          <button
            type="button"
            onClick={handleDismiss}
            disabled={isDismissing || isSubmitting}
            className="px-4 py-2 text-sm text-red-400 hover:text-red-300 disabled:opacity-50 transition-colors"
          >
            {isDismissing ? 'Dismissing...' : 'Dismiss'}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-cctv-text hover:text-cctv-text-dim transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting || !allQuestionsAnswered}
              className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim disabled:opacity-50 transition-colors"
            >
              {isSubmitting ? 'Submitting...' : 'Submit Response'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
