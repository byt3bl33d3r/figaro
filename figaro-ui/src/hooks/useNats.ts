import { useEffect } from 'react';
import { natsManager } from '../api/nats';
import { useConnectionStore } from '../stores/connection';

export function useNats() {
  const { status, error, reconnectAttempt } = useConnectionStore();

  useEffect(() => {
    natsManager.connect();

    return () => {
      // Don't disconnect on unmount - keep connection alive
      // natsManager.disconnect();
    };
  }, []);

  const sendTask = async (
    prompt: string,
    options: Record<string, unknown> = {}
  ) => {
    try {
      await natsManager.request('figaro.api.tasks.create', { prompt, options });
    } catch (err) {
      console.error('Failed to submit task:', err);
    }
  };

  return {
    status,
    error,
    reconnectAttempt,
    sendTask,
    disconnect: natsManager.disconnect.bind(natsManager),
    connect: natsManager.connect.bind(natsManager),
  };
}

// Keep backward compatibility alias
export { useNats as useWebSocket };
