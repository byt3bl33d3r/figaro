import { useState, useCallback } from 'react';
import { useWorkersStore } from '../stores/workers';
import { WorkerCard } from './WorkerCard';
import { AddDesktopWorkerForm } from './AddDesktopWorkerForm';
import { ContextMenu } from './ContextMenu';
import { removeDesktopWorker } from '../api/desktopWorkers';
import type { Worker } from '../types';

interface DesktopGridProps {
  onWorkerClick: (workerId: string) => void;
}

interface ContextMenuState {
  x: number;
  y: number;
  worker: Worker;
}

export function DesktopGrid({ onWorkerClick }: DesktopGridProps) {
  const workers = useWorkersStore((state) => state.getWorkersList());
  const [showAddForm, setShowAddForm] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [editingWorker, setEditingWorker] = useState<Worker | null>(null);

  const handleContextMenu = useCallback((e: React.MouseEvent, worker: Worker) => {
    setContextMenu({ x: e.clientX, y: e.clientY, worker });
  }, []);

  const handleRemove = useCallback(async (worker: Worker) => {
    try {
      await removeDesktopWorker(worker.id);
    } catch {
      // removal failed silently — broadcast will reflect actual state
    }
  }, []);

  if (workers.length === 0) {
    return (
      <div className="flex flex-col h-full">
        {/* Header with add button */}
        <div className="flex items-center justify-end px-4 pt-4">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-cctv-text-dim hover:text-cctv-accent border border-cctv-border hover:border-cctv-accent/50 rounded transition-colors"
            title="Add desktop worker"
          >
            <span className="text-lg leading-none">+</span>
            <span>Add Desktop</span>
          </button>
        </div>

        {showAddForm && <AddDesktopWorkerForm onClose={() => setShowAddForm(false)} />}

        <div className="flex items-center justify-center flex-1 text-cctv-text-dim">
          <div className="text-center">
            <div className="text-4xl mb-4">&#128736;</div>
            <div className="text-lg mb-2">No workers connected</div>
            <div className="text-sm">Waiting for workers to register...</div>
          </div>
        </div>
      </div>
    );
  }

  // Determine grid columns based on worker count
  const gridCols = workers.length <= 2
    ? 'grid-cols-1 md:grid-cols-2'
    : workers.length <= 4
    ? 'grid-cols-2'
    : workers.length <= 6
    ? 'grid-cols-2 lg:grid-cols-3'
    : 'grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';

  return (
    <div className="flex flex-col h-full">
      {/* Header with add button */}
      <div className="flex items-center justify-end px-4 pt-4">
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-cctv-text-dim hover:text-cctv-accent border border-cctv-border hover:border-cctv-accent/50 rounded transition-colors"
          title="Add desktop worker"
        >
          <span className="text-lg leading-none">+</span>
          <span>Add Desktop</span>
        </button>
      </div>

      {(showAddForm || editingWorker) && (
        <AddDesktopWorkerForm
          worker={editingWorker ?? undefined}
          onClose={() => {
            setShowAddForm(false);
            setEditingWorker(null);
          }}
        />
      )}

      <div className={`grid ${gridCols} gap-4 p-4`}>
        {workers.map((worker) => (
          <WorkerCard
            key={worker.id}
            worker={worker}
            onClick={() => onWorkerClick(worker.id)}
            onContextMenu={(e) => handleContextMenu(e, worker)}
          />
        ))}
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            {
              label: 'Edit',
              onClick: () => {
                setEditingWorker(contextMenu.worker);
                setShowAddForm(false);
              },
            },
            {
              label: 'Remove',
              danger: true,
              disabled: contextMenu.worker.agent_connected,
              onClick: () => handleRemove(contextMenu.worker),
            },
          ]}
        />
      )}
    </div>
  );
}
