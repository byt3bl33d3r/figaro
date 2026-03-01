import type { StreamEvent, SDKMessage, TaskAssignedPayload, TaskCompletePayload, ErrorPayload, SupervisorTaskSubmittedPayload, HelpRequestRespondedPayload, TaskHealingPayload } from '../types';
import { useHelpRequestsStore } from '../stores/helpRequests';

interface EventItemProps {
  event: StreamEvent;
  onWorkerClick?: (workerId: string) => void;
}

// Content block types from SDK serialization
interface TextBlock {
  text: string;
}

interface ToolUseBlock {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

function isTextBlock(block: unknown): block is TextBlock {
  return typeof block === 'object' && block !== null && 'text' in block && typeof (block as TextBlock).text === 'string';
}

function isToolUseBlock(block: unknown): block is ToolUseBlock {
  return typeof block === 'object' && block !== null && 'name' in block && 'id' in block && 'input' in block;
}

/**
 * Extract text content from SDK message content field.
 * Content can be a string or an array of blocks (TextBlock, ToolUseBlock, etc.)
 */
function extractTextContent(content: unknown): string | null {
  if (!content) return null;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    const textParts = content
      .filter(isTextBlock)
      .map((block) => block.text);
    return textParts.length > 0 ? textParts.join('\n') : null;
  }
  return null;
}

/**
 * Extract tool use blocks from SDK message content field.
 */
function extractToolUseBlocks(content: unknown): ToolUseBlock[] {
  if (!content || !Array.isArray(content)) return [];
  return content.filter(isToolUseBlock);
}

/**
 * Check if an event should be displayed in the stream.
 * We only show:
 * 1. Task assigned (includes the user's task prompt)
 * 2. AssistantMessage with text content or tool use
 * 3. Task complete
 * 4. Errors
 * 5. Supervisor-related events
 *
 * Note: UserMessage is NOT shown because the SDK sends it with every
 * conversation turn. The initial task prompt is shown in task_assigned instead.
 */
export function shouldShowEvent(event: StreamEvent): boolean {
  // Show task lifecycle events
  if (event.type === 'task_assigned' || event.type === 'task_complete' || event.type === 'error' || event.type === 'help_response' || event.type === 'task_healing') {
    return true;
  }

  // Show supervisor lifecycle events
  if (event.type === 'task_submitted_to_supervisor' || event.type === 'supervisor_task_complete') {
    return true;
  }

  // Show message events with AssistantMessage content
  if (event.type === 'message' || event.type === 'supervisor_message') {
    const message = event.data as SDKMessage;
    const msgType = message.__type__ || message.type || 'unknown';

    // Show AssistantMessage with text content or tool use
    if (msgType === 'AssistantMessage') {
      const text = extractTextContent(message.content);
      const tools = extractToolUseBlocks(message.content);
      return (text !== null && text.length > 0) || tools.length > 0;
    }

    // Don't show UserMessage - the SDK sends it every turn
    // The initial task prompt is shown in the task_assigned event instead
    return false;
  }

  return false;
}

export function EventItem({ event, onWorkerClick }: EventItemProps) {
  // Don't render if this event shouldn't be shown
  if (!shouldShowEvent(event)) {
    return null;
  }

  const timestamp = event.timestamp.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  const handleWorkerClick = () => {
    if (event.worker_id && onWorkerClick) {
      onWorkerClick(event.worker_id);
    }
  };

  // Check if this is a supervisor event
  const isSupervisorEvent = event.type === 'supervisor_message' || event.type === 'task_submitted_to_supervisor' || event.type === 'supervisor_task_complete';
  const supervisorId = (event.data as { supervisor_id?: string })?.supervisor_id;

  return (
    <div className={`px-3 py-2 hover:bg-cctv-border/30 transition-colors text-sm ${isSupervisorEvent ? 'border-l-2 border-purple-500' : ''}`}>
      <div className="flex items-start gap-2">
        <span className="text-cctv-text-dim text-xs shrink-0">{timestamp}</span>
        {isSupervisorEvent && supervisorId && (
          <span className="text-purple-400 text-xs shrink-0">
            [S:{supervisorId.slice(0, 6)}]
          </span>
        )}
        {!isSupervisorEvent && event.worker_id && (
          <button
            onClick={handleWorkerClick}
            className="text-cctv-accent hover:text-cctv-accent-dim text-xs shrink-0 hover:underline"
          >
            [{event.worker_id.slice(0, 8)}]
          </button>
        )}
        <div className="flex-1 min-w-0">
          <EventContent event={event} />
        </div>
      </div>
    </div>
  );
}

function EventContent({ event }: { event: StreamEvent }) {
  switch (event.type) {
    case 'message':
      return <MessageContent message={event.data as SDKMessage} workerId={event.worker_id} />;
    case 'supervisor_message':
      return <MessageContent message={event.data as SDKMessage} isSupervisor workerId={event.worker_id} />;
    case 'task_submitted_to_supervisor':
      const supervisorSubmitted = event.data as SupervisorTaskSubmittedPayload;
      const supervisorPrompt = supervisorSubmitted.prompt || '';
      const supervisorPromptText = supervisorPrompt.length > 150
        ? supervisorPrompt.slice(0, 150) + '...'
        : supervisorPrompt;
      return (
        <span className="text-purple-400">
          <span className="font-semibold">Supervisor Task:</span> {supervisorPromptText || `${supervisorSubmitted.task_id?.slice(0, 8) || 'unknown'}...`}
        </span>
      );
    case 'supervisor_task_complete':
      const supervisorComplete = event.data as TaskCompletePayload;
      return (
        <span className="text-purple-400">
          Supervisor task complete: {supervisorComplete.task_id.slice(0, 8)}
        </span>
      );
    case 'task_assigned':
      const assigned = event.data as TaskAssignedPayload;
      const prompt = assigned.prompt || '';
      const promptText = prompt.length > 150
        ? prompt.slice(0, 150) + '...'
        : prompt;
      return (
        <span className="text-cctv-warning">
          <span className="font-semibold">Task:</span> {promptText || `${assigned.task_id?.slice(0, 8) || 'unknown'}...`}
        </span>
      );
    case 'task_complete':
      const complete = event.data as TaskCompletePayload;
      return (
        <span className="text-cctv-accent">
          Task complete: {complete.task_id.slice(0, 8)}
        </span>
      );
    case 'error':
      const error = event.data as ErrorPayload;
      return (
        <span className="text-cctv-error">
          Error: {error.error}
        </span>
      );
    case 'help_response': {
      const helpResponse = event.data as HelpRequestRespondedPayload;
      const answers = helpResponse.answers || {};
      const questions = helpResponse.questions || [];
      const answerEntries = Object.entries(answers);
      return (
        <div className="text-amber-400">
          <span className="font-semibold">Help response</span>
          <span className="text-cctv-text-dim"> via {helpResponse.source}</span>
          {answerEntries.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {answerEntries.map(([question, answer]) => {
                const q = questions.find((q) => q.question === question);
                const label = q?.header || question;
                return (
                  <div key={question} className="text-cctv-text text-xs">
                    <span className="text-cctv-text-dim">{label}:</span> {answer}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      );
    }
    case 'task_healing': {
      const healing = event.data as TaskHealingPayload;
      const summary = healing.error_summary ?? 'Unknown error';
      const errorText = summary.length > 120
        ? summary.slice(0, 120) + '...'
        : summary;
      return (
        <span className="text-orange-400">
          <span className="font-semibold">Self-Healing</span>
          <span className="text-cctv-text-dim"> attempt #{healing.attempt}</span>
          {' '}&mdash; {errorText}
        </span>
      );
    }
    case 'system':
      const systemData = event.data as { message: string };
      return (
        <span className="text-cctv-text-dim italic">
          {systemData.message}
        </span>
      );
    default:
      return null;
  }
}

function MessageContent({ message, isSupervisor = false, workerId }: { message: SDKMessage; isSupervisor?: boolean; workerId?: string }) {
  const msgType = message.__type__ || message.type || 'unknown';
  const pendingRequests = useHelpRequestsStore((state) => state.getPendingRequests());
  const setActiveRequestId = useHelpRequestsStore((state) => state.setActiveRequestId);

  // AssistantMessage - show text and/or tool use
  if (msgType === 'AssistantMessage') {
    const text = extractTextContent(message.content);
    const tools = extractToolUseBlocks(message.content);

    return (
      <div className="space-y-1">
        {text && (
          <span className={`whitespace-pre-wrap break-words block ${isSupervisor ? 'text-purple-200' : 'text-cctv-text'}`}>
            {text}
          </span>
        )}
        {tools.map((tool) => (
          <span key={tool.id} className={`block ${isSupervisor ? 'text-purple-400' : 'text-cctv-accent-dim'}`}>
            <span className="font-semibold">Tool:</span> {tool.name}
            {tool.name === 'AskUserQuestion' && !!tool.input?.questions && (
              <span className="text-amber-400 ml-1">
                — {(tool.input.questions as Array<{question: string}>)[0]?.question}
              </span>
            )}
            {tool.name === 'AskUserQuestion' && workerId && (() => {
              const matchingRequest = pendingRequests.find((r) => r.worker_id === workerId);
              if (!matchingRequest) return null;
              return (
                <button
                  onClick={() => setActiveRequestId(matchingRequest.request_id)}
                  className="ml-2 px-2 py-0.5 text-xs font-medium bg-amber-500/20 text-amber-400 rounded hover:bg-amber-500/30 transition-colors"
                >
                  Answer
                </button>
              );
            })()}
          </span>
        ))}
      </div>
    );
  }

  return null;
}
