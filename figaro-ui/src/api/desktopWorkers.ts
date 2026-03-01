import { natsManager } from './nats';

export async function registerDesktopWorker(
  workerId: string,
  novncUrl: string,
  metadata: Record<string, string>,
  vncPassword?: string,
  vncUsername?: string
): Promise<void> {
  await natsManager.request('figaro.api.desktop-workers.register', {
    worker_id: workerId,
    novnc_url: novncUrl,
    metadata,
    vnc_username: vncUsername || undefined,
    vnc_password: vncPassword || undefined,
  });
}

export async function removeDesktopWorker(workerId: string): Promise<void> {
  await natsManager.request('figaro.api.desktop-workers.remove', {
    worker_id: workerId,
  });
}

export async function updateDesktopWorker(
  workerId: string,
  newWorkerId?: string,
  novncUrl?: string,
  metadata?: Record<string, string>,
  vncPassword?: string,
  vncUsername?: string
): Promise<void> {
  await natsManager.request('figaro.api.desktop-workers.update', {
    worker_id: workerId,
    new_worker_id: newWorkerId || undefined,
    novnc_url: novncUrl || undefined,
    metadata: metadata || undefined,
    vnc_username: vncUsername || undefined,
    vnc_password: vncPassword || undefined,
  });
}
