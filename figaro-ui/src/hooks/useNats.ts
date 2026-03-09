import { useEffect } from 'react';
import { natsManager } from '../api/nats';
import { useConnectionStore } from '../stores/connection';

export function useNats() {
  const { status } = useConnectionStore();

  useEffect(() => {
    natsManager.connect();
  }, []);

  return { status };
}
