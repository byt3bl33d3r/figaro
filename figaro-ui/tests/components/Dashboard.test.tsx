import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Dashboard } from '../../src/components/Dashboard';
import { useWorkersStore } from '../../src/stores/workers';
import { useHelpRequestsStore } from '../../src/stores/helpRequests';

// Mock child components to isolate Dashboard behavior
vi.mock('../../src/hooks/useNats', () => ({
  useNats: () => ({ status: 'connected' }),
}));

vi.mock('../../src/components/StatusBadge', () => ({
  ConnectionStatusBadge: ({ status }: { status: string }) => (
    <span data-testid="connection-badge">{status}</span>
  ),
}));

vi.mock('../../src/components/DesktopGrid', () => ({
  DesktopGrid: ({ onWorkerClick }: { onWorkerClick: (id: string) => void }) => (
    <div data-testid="desktop-grid" onClick={() => onWorkerClick('w1')}>DesktopGrid</div>
  ),
}));

vi.mock('../../src/components/KanbanBoard', () => ({
  KanbanBoard: ({ onWorkerClick }: { onWorkerClick: (id: string) => void }) => (
    <div data-testid="kanban-board" onClick={() => onWorkerClick('w1')}>KanbanBoard</div>
  ),
}));

vi.mock('../../src/components/Sidebar', () => ({
  Sidebar: () => <div data-testid="sidebar">Sidebar</div>,
}));

vi.mock('../../src/components/DesktopModal', () => ({
  DesktopModal: ({ workerId, onClose }: { workerId: string; onClose: () => void }) => (
    <div data-testid="desktop-modal" onClick={onClose}>{workerId}</div>
  ),
}));

vi.mock('../../src/components/HelpRequestNotification', () => ({
  HelpRequestNotification: () => <div data-testid="help-notification" />,
}));

vi.mock('../../src/components/HelpRequestModal', () => ({
  HelpRequestModal: () => <div data-testid="help-modal" />,
}));

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkersStore.setState({ workers: new Map(), selectedWorkerId: null });
    useHelpRequestsStore.setState({ activeRequestId: null });
  });

  it('should render the header with title', () => {
    render(<Dashboard />);
    expect(screen.getByText('Figaro Dashboard')).toBeInTheDocument();
  });

  it('should render Grid and Board toggle buttons', () => {
    render(<Dashboard />);
    expect(screen.getByText('Grid')).toBeInTheDocument();
    expect(screen.getByText('Board')).toBeInTheDocument();
  });

  it('should show DesktopGrid by default', () => {
    render(<Dashboard />);
    expect(screen.getByTestId('desktop-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('kanban-board')).not.toBeInTheDocument();
  });

  it('should switch to KanbanBoard when Board button is clicked', () => {
    render(<Dashboard />);

    fireEvent.click(screen.getByText('Board'));

    expect(screen.getByTestId('kanban-board')).toBeInTheDocument();
    expect(screen.queryByTestId('desktop-grid')).not.toBeInTheDocument();
  });

  it('should switch back to DesktopGrid when Grid button is clicked', () => {
    render(<Dashboard />);

    fireEvent.click(screen.getByText('Board'));
    expect(screen.getByTestId('kanban-board')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Grid'));
    expect(screen.getByTestId('desktop-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('kanban-board')).not.toBeInTheDocument();
  });

  it('should display worker count', () => {
    useWorkersStore.getState().setWorkers([
      { id: 'w1', status: 'idle', capabilities: [], agent_connected: true },
      { id: 'w2', status: 'busy', capabilities: [], agent_connected: true },
    ]);

    render(<Dashboard />);
    expect(screen.getByText('2 workers connected')).toBeInTheDocument();
  });

  it('should display singular worker text', () => {
    useWorkersStore.getState().setWorkers([
      { id: 'w1', status: 'idle', capabilities: [], agent_connected: true },
    ]);

    render(<Dashboard />);
    expect(screen.getByText('1 worker connected')).toBeInTheDocument();
  });

  it('should open desktop modal when worker is clicked in grid view', () => {
    render(<Dashboard />);

    fireEvent.click(screen.getByTestId('desktop-grid'));
    expect(screen.getByTestId('desktop-modal')).toBeInTheDocument();
    expect(screen.getByText('w1')).toBeInTheDocument();
  });

  it('should open desktop modal when worker is clicked in board view', () => {
    render(<Dashboard />);

    fireEvent.click(screen.getByText('Board'));
    fireEvent.click(screen.getByTestId('kanban-board'));

    expect(screen.getByTestId('desktop-modal')).toBeInTheDocument();
  });

  it('should close modal when onClose is called', () => {
    render(<Dashboard />);

    // Open modal
    fireEvent.click(screen.getByTestId('desktop-grid'));
    expect(screen.getByTestId('desktop-modal')).toBeInTheDocument();

    // Close modal
    fireEvent.click(screen.getByTestId('desktop-modal'));
    expect(screen.queryByTestId('desktop-modal')).not.toBeInTheDocument();
  });
});
