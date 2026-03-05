/**
 * Fetch an encrypted Guacamole connection token for a worker.
 */
export async function getGuacamoleToken(workerId: string): Promise<string> {
  const res = await fetch(`/api/guacamole/token?worker_id=${encodeURIComponent(workerId)}`);
  if (!res.ok) {
    throw new Error(`Failed to get guacamole token: ${res.status}`);
  }
  const data = await res.json();
  return data.token;
}

/**
 * Build the Guacamole WebSocket URL from an encrypted token.
 */
export function getGuacamoleWsUrl(token: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${protocol}//${host}/guacamole/webSocket?token=${encodeURIComponent(token)}`;
}
