/**
 * NATS subject constants and builder functions for Figaro.
 *
 * Ported from figaro-nats/src/figaro_nats/subjects.py
 */

export const Subjects = {
  // Registration & Presence (Core NATS)
  REGISTER_WORKER: "figaro.register.worker" as const,
  REGISTER_SUPERVISOR: "figaro.register.supervisor" as const,
  REGISTER_GATEWAY: "figaro.register.gateway" as const,

  deregister(clientType: string, clientId: string): string {
    return `figaro.deregister.${clientType}.${clientId}`;
  },

  heartbeat(clientType: string, clientId: string): string {
    return `figaro.heartbeat.${clientType}.${clientId}`;
  },

  // Wildcard for subscribing to all heartbeats
  HEARTBEAT_ALL: "figaro.heartbeat.>" as const,

  // Task Assignment (Core NATS - point-to-point)
  workerTask(workerId: string): string {
    return `figaro.worker.${workerId}.task`;
  },

  supervisorTask(supervisorId: string): string {
    return `figaro.supervisor.${supervisorId}.task`;
  },

  // Task Events (JetStream TASKS stream - figaro.task.>)
  taskAssigned(taskId: string): string {
    return `figaro.task.${taskId}.assigned`;
  },

  taskMessage(taskId: string): string {
    return `figaro.task.${taskId}.message`;
  },

  taskComplete(taskId: string): string {
    return `figaro.task.${taskId}.complete`;
  },

  taskError(taskId: string): string {
    return `figaro.task.${taskId}.error`;
  },

  // Subscribe to all events for a specific task
  taskAll(taskId: string): string {
    return `figaro.task.${taskId}.>`;
  },

  // Subscribe to all task events (for JetStream stream)
  TASK_EVENTS_ALL: "figaro.task.>" as const,

  // Help Requests (Core NATS)
  HELP_REQUEST: "figaro.help.request" as const,

  helpResponse(requestId: string): string {
    return `figaro.help.${requestId}.response`;
  },

  // Broadcasts (Core NATS)
  BROADCAST_WORKERS: "figaro.broadcast.workers" as const,
  BROADCAST_SUPERVISORS: "figaro.broadcast.supervisors" as const,
  BROADCAST_ALL: "figaro.broadcast.>" as const,

  // API (NATS request/reply for service-to-service calls)
  API_DELEGATE: "figaro.api.delegate" as const,
  API_WORKERS: "figaro.api.workers" as const,
  API_TASKS: "figaro.api.tasks" as const,
  API_TASK_GET: "figaro.api.tasks.get" as const,
  API_TASK_SEARCH: "figaro.api.tasks.search" as const,
  API_SUPERVISOR_STATUS: "figaro.api.supervisor.status" as const,
  API_SCHEDULED_TASKS: "figaro.api.scheduled-tasks" as const,
  API_SCHEDULED_TASK_GET: "figaro.api.scheduled-tasks.get" as const,
  API_SCHEDULED_TASK_CREATE: "figaro.api.scheduled-tasks.create" as const,
  API_SCHEDULED_TASK_UPDATE: "figaro.api.scheduled-tasks.update" as const,
  API_SCHEDULED_TASK_DELETE: "figaro.api.scheduled-tasks.delete" as const,
  API_SCHEDULED_TASK_TOGGLE: "figaro.api.scheduled-tasks.toggle" as const,
  API_SCHEDULED_TASK_TRIGGER: "figaro.api.scheduled-tasks.trigger" as const,
  API_TASK_CREATE: "figaro.api.tasks.create" as const,
  API_HELP_REQUESTS_LIST: "figaro.api.help-requests.list" as const,
  API_HELP_REQUEST_RESPOND: "figaro.api.help-requests.respond" as const,
  API_HELP_REQUEST_DISMISS: "figaro.api.help-requests.dismiss" as const,
  API_VNC: "figaro.api.vnc" as const,
  API_DESKTOP_WORKERS_REGISTER: "figaro.api.desktop-workers.register" as const,
  API_DESKTOP_WORKERS_REMOVE: "figaro.api.desktop-workers.remove" as const,
  API_DESKTOP_WORKERS_UPDATE: "figaro.api.desktop-workers.update" as const,

  // Gateway -- channel-agnostic (Core NATS)
  gatewaySend(channel: string): string {
    return `figaro.gateway.${channel}.send`;
  },

  gatewayTask(channel: string): string {
    return `figaro.gateway.${channel}.task`;
  },

  gatewayQuestion(channel: string): string {
    return `figaro.gateway.${channel}.question`;
  },

  gatewayRegister(channel: string): string {
    return `figaro.gateway.${channel}.register`;
  },
} as const;
