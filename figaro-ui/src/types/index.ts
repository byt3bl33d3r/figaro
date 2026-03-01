// Worker types
export type WorkerStatus = 'idle' | 'busy';

export interface Worker {
  id: string;
  status: WorkerStatus;
  capabilities: string[];
  novnc_url?: string;
  vnc_username?: string;
  vnc_password?: string;
  agent_connected: boolean;
  metadata?: Record<string, string>;
}

// Supervisor types
export interface Supervisor {
  id: string;
  status: WorkerStatus;
  capabilities: string[];
}

// Task target (where to route the task)
// - 'worker': Direct to worker (no clarification)
// - 'supervisor': Route via supervisor for clarification/optimization
// - 'auto': Supervisor decides if clarification needed (uses supervisor if available, falls back to worker)
export type TaskTarget = 'worker' | 'supervisor' | 'auto';

// Task types
export type TaskStatus = 'pending' | 'assigned' | 'running' | 'completed' | 'failed';

export interface Task {
  task_id: string;
  prompt: string;
  options: Record<string, unknown>;
  status: TaskStatus;
  result?: unknown;
  worker_id?: string;
  session_id?: string;
  messages: SDKMessage[];
}

// WebSocket message types
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface RegisterPayload {
  client_type: 'ui' | 'worker' | 'supervisor';
  worker_id?: string;
  capabilities?: string[];
  novnc_url?: string;
}

export interface WorkersPayload {
  workers: Worker[];
}

export interface SupervisorsPayload {
  supervisors: Supervisor[];
}

export interface TaskPayload {
  task_id: string;
  prompt: string;
  options?: Record<string, unknown>;
}

export interface TaskAssignedPayload {
  task_id: string;
  worker_id: string;
  prompt: string;
}

export interface TaskCompletePayload {
  task_id: string;
  worker_id: string;
  result?: unknown;
}

export interface StatusPayload {
  worker_id: string;
  status: WorkerStatus;
}

export interface ErrorPayload {
  task_id: string;
  error: string;
}

// Claude SDK message types (subset of relevant fields)
export interface SDKMessage {
  task_id: string;
  worker_id?: string;
  supervisor_id?: string;
  __type__?: string;
  type?: string;
  // Direct fields from serialized SDK dataclasses (AssistantMessage, UserMessage, etc.)
  content?: ContentBlock[] | string;
  model?: string;
  // ResultMessage fields (result is a string for ResultMessage)
  result?: string | { output?: string; error?: string; is_error?: boolean };
  is_error?: boolean;
  duration_ms?: number;
  // Legacy/nested message format
  message?: {
    role?: string;
    content?: ContentBlock[];
    model?: string;
    stop_reason?: string;
  };
  content_block?: ContentBlock;
  delta?: {
    type?: string;
    text?: string;
    partial_json?: string;
  };
  index?: number;
  timestamp?: string;
}

export interface ContentBlock {
  type: string;
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
  id?: string;
}

// Event stream types (combined SDK messages + system events)
export interface StreamEvent {
  id: string;
  timestamp: Date;
  worker_id?: string;
  supervisor_id?: string;
  type: 'message' | 'task_assigned' | 'task_complete' | 'error' | 'status' | 'system' | 'supervisor_message' | 'supervisor_task_complete' | 'supervisor_error' | 'task_submitted_to_supervisor' | 'help_response' | 'task_healing';
  data: SDKMessage | TaskAssignedPayload | TaskCompletePayload | ErrorPayload | StatusPayload | SupervisorTaskSubmittedPayload | HelpRequestRespondedPayload | TaskHealingPayload | { message: string };
}

// Supervisor-specific payloads
export interface SupervisorTaskSubmittedPayload {
  task_id: string;
  supervisor_id: string;
  prompt: string;
}

// WebSocket message envelope
export interface WSMessage {
  type: string;
  payload: Record<string, unknown>;
}

// API response types
export interface TaskCreateRequest {
  prompt: string;
  options?: Record<string, unknown>;
}

export interface TaskResponse {
  task_id: string;
  prompt: string;
  options: Record<string, unknown>;
  status: string;
  result?: unknown;
  worker_id?: string;
  session_id?: string;
  messages: SDKMessage[];
}

// Scheduled task types
export interface ScheduledTask {
  schedule_id: string;
  name: string;
  prompt: string;
  start_url: string;
  interval_seconds: number;
  enabled: boolean;
  created_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  run_count: number;
  options: Record<string, unknown>;
  parallel_workers: number;
  max_runs: number | null;
  notify_on_complete: boolean;
  self_learning: boolean;
  self_healing: boolean;
  self_learning_max_runs: number | null;
  self_learning_run_count: number;
}

export interface ScheduledTaskCreate {
  name: string;
  prompt: string;
  start_url: string;
  interval_seconds: number;
  options?: Record<string, unknown>;
  parallel_workers?: number;
  max_runs?: number | null;
  notify_on_complete?: boolean;
  self_learning?: boolean;
  self_healing?: boolean;
  self_learning_max_runs?: number | null;
}

export interface ScheduledTaskUpdate {
  name?: string;
  prompt?: string;
  start_url?: string;
  interval_seconds?: number;
  enabled?: boolean;
  options?: Record<string, unknown>;
  parallel_workers?: number;
  max_runs?: number | null;
  notify_on_complete?: boolean;
  self_learning?: boolean;
  self_healing?: boolean;
  self_learning_max_runs?: number | null;
}

// Scheduled task WebSocket payloads
export interface ScheduledTaskExecutedPayload {
  schedule_id: string;
  task_id: string;
  worker_id: string;
}

export interface ScheduledTaskSkippedPayload {
  schedule_id: string;
  reason: string;
}

export interface TaskHealingPayload {
  task_id: string;
  schedule_id: string;
  attempt: number;
  error_summary: string;
  new_task_id?: string;
}

// Help request types (for human-in-the-loop assistance)
export type HelpRequestStatus = 'pending' | 'responded' | 'timeout' | 'cancelled';

export interface QuestionOption {
  label: string;
  description: string;
}

export interface Question {
  question: string;
  header: string;
  options: QuestionOption[];
  multiSelect: boolean;
}

export interface HelpRequest {
  request_id: string;
  worker_id: string;
  task_id: string;
  questions: Question[];
  context?: Record<string, unknown>;
  created_at: string;
  timeout_seconds: number;
  status: HelpRequestStatus;
  answers?: Record<string, string>;
  responded_at?: string;
  response_source?: string;
}

export interface HelpRequestCreatedPayload {
  request_id: string;
  worker_id: string;
  task_id: string;
  questions: Question[];
  context?: Record<string, unknown>;
  created_at: string;
  timeout_seconds: number;
  status?: HelpRequestStatus;
}

export interface HelpRequestRespondedPayload {
  request_id: string;
  worker_id: string;
  task_id: string;
  source: string;
  answers?: Record<string, string>;
  questions?: Question[];
}

export interface HelpRequestTimeoutPayload {
  request_id: string;
  worker_id: string;
  task_id: string;
}
