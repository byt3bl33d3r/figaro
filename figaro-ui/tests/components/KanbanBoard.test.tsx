import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { KanbanBoard } from '../../src/components/KanbanBoard';
import { KanbanColumn } from '../../src/components/KanbanColumn';
import { KanbanCard } from '../../src/components/KanbanCard';
import { useWorkersStore } from '../../src/stores/workers';
import { useSupervisorsStore } from '../../src/stores/supervisors';
import { useTasksStore } from '../../src/stores/tasks';
import type { Worker, Supervisor, ActiveTask } from '../../src/types';

const createWorker = (id: string, status: 'idle' | 'busy' = 'idle'): Worker => ({
  id,
  status,
  capabilities: [],
  novnc_url: `ws://host:6080/websockify`,
  agent_connected: true,
});

const createSupervisor = (id: string, status: 'idle' | 'busy' = 'idle'): Supervisor => ({
  id,
  status,
  capabilities: [],
});

const createTask = (
  id: string,
  agentId: string,
  agentType: 'worker' | 'supervisor' = 'worker',
): ActiveTask => ({
  task_id: id,
  prompt: `Do something for task ${id}`,
  status: 'assigned',
  agent_id: agentId,
  agent_type: agentType,
  assigned_at: new Date().toISOString(),
  options: {},
});

describe('KanbanBoard', () => {
  const onWorkerClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useWorkersStore.setState({ workers: new Map(), selectedWorkerId: null });
    useSupervisorsStore.setState({ supervisors: new Map() });
    useTasksStore.setState({ tasks: new Map() });
  });

  it('should show empty state when no agents connected', () => {
    render(<KanbanBoard onWorkerClick={onWorkerClick} />);
    expect(screen.getByText('No agents connected')).toBeInTheDocument();
  });

  it('should render worker columns', () => {
    useWorkersStore.getState().setWorkers([createWorker('worker-1'), createWorker('worker-2')]);

    render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    expect(screen.getByText('worker-1')).toBeInTheDocument();
    expect(screen.getByText('worker-2')).toBeInTheDocument();
  });

  it('should render supervisor columns', () => {
    useSupervisorsStore.getState().setSupervisors([createSupervisor('supervisor-1')]);

    render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    expect(screen.getByText('supervisor-1')).toBeInTheDocument();
  });

  it('should render supervisors before workers', () => {
    useSupervisorsStore.getState().setSupervisors([createSupervisor('supervisor-1')]);
    useWorkersStore.getState().setWorkers([createWorker('worker-1')]);

    const { container } = render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    const columns = container.querySelectorAll('.min-w-\\[280px\\]');
    const firstColumnText = columns[0]?.textContent || '';
    const secondColumnText = columns[1]?.textContent || '';

    expect(firstColumnText).toContain('supervisor-1');
    expect(secondColumnText).toContain('worker-1');
  });

  it('should gray out workers without agent connected', () => {
    const disconnectedWorker = createWorker('worker-1');
    disconnectedWorker.agent_connected = false;
    useWorkersStore.getState().setWorkers([disconnectedWorker]);

    const { container } = render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    const column = container.querySelector('.min-w-\\[280px\\]') as HTMLElement;
    expect(column.className).toContain('opacity-50');
    expect(column.className).toContain('grayscale');
  });

  it('should not gray out workers with agent connected', () => {
    useWorkersStore.getState().setWorkers([createWorker('worker-1')]);

    const { container } = render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    const column = container.querySelector('.min-w-\\[280px\\]') as HTMLElement;
    expect(column.className).not.toContain('opacity-50');
    expect(column.className).not.toContain('grayscale');
  });

  it('should use content-start to pack grid rows at the top', () => {
    useWorkersStore.getState().setWorkers([createWorker('worker-1')]);

    const { container } = render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    const grid = container.firstChild as HTMLElement;
    expect(grid.className).toContain('content-start');
  });

  it('should not show empty state when agents exist', () => {
    useWorkersStore.getState().setWorkers([createWorker('worker-1')]);

    render(<KanbanBoard onWorkerClick={onWorkerClick} />);

    expect(screen.queryByText('No agents connected')).not.toBeInTheDocument();
  });
});

describe('KanbanColumn', () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: new Map() });
  });

  it('should display agent id and type badge', () => {
    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" />,
    );

    expect(screen.getByText('worker-1')).toBeInTheDocument();
    expect(screen.getByText('worker')).toBeInTheDocument();
  });

  it('should display supervisor type badge', () => {
    render(
      <KanbanColumn agentId="sup-1" agentType="supervisor" status="busy" />,
    );

    expect(screen.getByText('supervisor')).toBeInTheDocument();
  });

  it('should show status badge', () => {
    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="busy" />,
    );

    expect(screen.getByText('busy')).toBeInTheDocument();
  });

  it('should show empty state when no tasks', () => {
    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" />,
    );

    expect(screen.getByText('No active tasks')).toBeInTheDocument();
    expect(screen.getByText('0 tasks')).toBeInTheDocument();
  });

  it('should render tasks for the agent', () => {
    useTasksStore.getState().addTask(createTask('task-abc12345', 'worker-1'));

    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="busy" />,
    );

    expect(screen.getByText('Do something for task task-abc12345')).toBeInTheDocument();
    expect(screen.getByText('1 task')).toBeInTheDocument();
  });

  it('should show correct task count with pluralization', () => {
    useTasksStore.getState().addTask(createTask('task-1', 'worker-1'));
    useTasksStore.getState().addTask(createTask('task-2', 'worker-1'));

    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="busy" />,
    );

    expect(screen.getByText('2 tasks')).toBeInTheDocument();
  });

  it('should not show tasks for other agents', () => {
    useTasksStore.getState().addTask(createTask('task-1', 'worker-2'));

    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" />,
    );

    expect(screen.getByText('No active tasks')).toBeInTheDocument();
  });

  it('should apply grayed out styles when agent is disconnected', () => {
    const { container } = render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" agentConnected={false} />,
    );

    const column = container.firstChild as HTMLElement;
    expect(column.className).toContain('opacity-50');
    expect(column.className).toContain('grayscale');
  });

  it('should show NO AGENT badge when disconnected', () => {
    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" agentConnected={false} />,
    );

    expect(screen.getByText('NO AGENT')).toBeInTheDocument();
  });

  it('should not show NO AGENT badge when connected', () => {
    render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" agentConnected={true} />,
    );

    expect(screen.queryByText('NO AGENT')).not.toBeInTheDocument();
  });

  it('should not be grayed out by default', () => {
    const { container } = render(
      <KanbanColumn agentId="worker-1" agentType="worker" status="idle" />,
    );

    const column = container.firstChild as HTMLElement;
    expect(column.className).not.toContain('opacity-50');
  });
});

describe('KanbanCard', () => {
  const onWorkerClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should display task prompt', () => {
    const task = createTask('abcdef1234567890', 'worker-1');

    render(<KanbanCard task={task} onWorkerClick={onWorkerClick} />);

    expect(screen.getByText('Do something for task abcdef1234567890')).toBeInTheDocument();
  });

  it('should display truncated task id', () => {
    const task = createTask('abcdef1234567890', 'worker-1');

    render(<KanbanCard task={task} />);

    expect(screen.getByText('abcdef12')).toBeInTheDocument();
  });

  it('should display task status badge', () => {
    const task = createTask('task-1', 'worker-1');

    render(<KanbanCard task={task} />);

    expect(screen.getByText('assigned')).toBeInTheDocument();
  });

  it('should be clickable for worker tasks with onWorkerClick', () => {
    const task = createTask('task-1', 'worker-1', 'worker');

    render(<KanbanCard task={task} onWorkerClick={onWorkerClick} />);

    fireEvent.click(screen.getByText('Do something for task task-1'));
    expect(onWorkerClick).toHaveBeenCalledWith('worker-1');
  });

  it('should not be clickable for supervisor tasks', () => {
    const task = createTask('task-1', 'sup-1', 'supervisor');

    render(<KanbanCard task={task} onWorkerClick={onWorkerClick} />);

    fireEvent.click(screen.getByText('Do something for task task-1'));
    expect(onWorkerClick).not.toHaveBeenCalled();
  });

  it('should not be clickable without onWorkerClick', () => {
    const task = createTask('task-1', 'worker-1', 'worker');

    const { container } = render(<KanbanCard task={task} />);

    // Should not have cursor-pointer class
    const card = container.firstChild as HTMLElement;
    expect(card.className).not.toContain('cursor-pointer');
  });
});
