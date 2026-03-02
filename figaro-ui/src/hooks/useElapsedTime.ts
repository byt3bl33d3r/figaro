import { useState, useEffect } from 'react';

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

export function useElapsedTime(since: string | Date): string {
  const [elapsed, setElapsed] = useState(() => {
    const start = typeof since === 'string' ? new Date(since) : since;
    return formatElapsed(Date.now() - start.getTime());
  });

  useEffect(() => {
    const start = typeof since === 'string' ? new Date(since) : since;
    const update = () => setElapsed(formatElapsed(Date.now() - start.getTime()));
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [since]);

  return elapsed;
}
