/**
 * Get the VNC proxy URL for a worker.
 * Uses the orchestrator's /vnc/{worker_id} proxy endpoint.
 */
export function getVncProxyUrl(workerId: string): string {
  // Use the same host as the current page, with ws/wss protocol
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${protocol}//${host}/vnc/${workerId}`;
}
