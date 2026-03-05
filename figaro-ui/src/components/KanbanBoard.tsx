import { useWorkersStore } from '../stores/workers';
import { useSupervisorsStore } from '../stores/supervisors';
import { KanbanColumn } from './KanbanColumn';

interface KanbanBoardProps {
  onWorkerClick: (workerId: string) => void;
  onWorkerHistoryClick?: (workerId: string) => void;
}

export function KanbanBoard({ onWorkerClick, onWorkerHistoryClick }: KanbanBoardProps) {
  const workers = useWorkersStore((state) => state.getWorkersList());
  const supervisors = useSupervisorsStore((state) => state.getSupervisorsList());

  if (workers.length === 0 && supervisors.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-cctv-text-dim">
        <div className="text-center">
          <div className="text-4xl mb-4">&#128203;</div>
          <div className="text-lg mb-2">No agents connected</div>
          <div className="text-sm">Waiting for workers or supervisors to register...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-4 p-4 h-full items-start content-start overflow-y-auto" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
      {supervisors.map((supervisor) => (
        <KanbanColumn
          key={supervisor.id}
          agentId={supervisor.id}
          agentType="supervisor"
          status={supervisor.status}
          onColumnClick={onWorkerHistoryClick}
        />
      ))}
      {workers.map((worker) => (
        <KanbanColumn
          key={worker.id}
          agentId={worker.id}
          agentType="worker"
          status={worker.status}
          agentConnected={worker.agent_connected}
          onWorkerClick={onWorkerClick}
          onColumnClick={onWorkerHistoryClick}
        />
      ))}
    </div>
  );
}
