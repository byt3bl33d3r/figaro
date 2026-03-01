import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { EventStream } from '../../src/components/EventStream';
import { useMessagesStore } from '../../src/stores/messages';
import { useWorkersStore } from '../../src/stores/workers';
import { useSupervisorsStore } from '../../src/stores/supervisors';
import { useConnectionStore } from '../../src/stores/connection';

/**
 * Regression test: user-created tasks must appear in the Event UI exactly once.
 *
 * The full flow is: user submits a task via ChatInput → orchestrator assigns
 * it to a worker → JetStream publishes a "task_assigned" event → NatsManager
 * calls messagesStore.addEvent({ type: 'task_assigned', ... }) → EventStream
 * renders it via EventItem.
 *
 * This test exercises the store → EventStream rendering path to ensure
 * task_assigned events (user tasks) are visible and not duplicated.
 */

describe('EventStream – user tasks appear', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useMessagesStore.setState({ events: [], filterWorkerId: null });
    useWorkersStore.setState({ workers: new Map(), selectedWorkerId: null });
    useSupervisorsStore.setState({ supervisors: new Map() });
    useConnectionStore.setState({ status: 'connected', reconnectAttempts: 0 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Helper: advance past the 500ms settle timer so EventStream exits loading state. */
  async function settleEventStream() {
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
  }

  it('should display a user task_assigned event with its prompt', async () => {
    useMessagesStore.getState().addEvent({
      worker_id: 'worker-abc123',
      type: 'task_assigned',
      data: { task_id: 'task-001', worker_id: 'worker-abc123', prompt: 'Navigate to example.com and click login' },
    });

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/Task:/)).toBeInTheDocument();
    expect(screen.getByText(/Navigate to example.com and click login/)).toBeInTheDocument();
  });

  it('should display each user task exactly once (no duplicates)', async () => {
    // Simulate a single task_assigned event — it must render exactly once
    useMessagesStore.getState().addEvent({
      worker_id: 'worker-abc123',
      type: 'task_assigned',
      data: { task_id: 'task-once', worker_id: 'worker-abc123', prompt: 'Unique task prompt' },
    });

    render(<EventStream />);
    await settleEventStream();

    const taskElements = screen.getAllByText(/Unique task prompt/);
    expect(taskElements).toHaveLength(1);
  });

  it('should display task_assigned followed by assistant messages and completion', async () => {
    const store = useMessagesStore.getState();

    store.addEvent({
      worker_id: 'worker-abc123',
      type: 'task_assigned',
      data: { task_id: 'task-002', worker_id: 'worker-abc123', prompt: 'Search for flights' },
    });

    store.addEvent({
      worker_id: 'worker-abc123',
      type: 'message',
      data: {
        task_id: 'task-002',
        worker_id: 'worker-abc123',
        __type__: 'AssistantMessage',
        content: 'I will navigate to the flights page now.',
      },
    });

    store.addEvent({
      worker_id: 'worker-abc123',
      type: 'task_complete',
      data: { task_id: 'task-002', worker_id: 'worker-abc123' },
    });

    render(<EventStream />);
    await settleEventStream();

    // All three events should be visible
    expect(screen.getByText(/Task:/)).toBeInTheDocument();
    expect(screen.getByText(/Search for flights/)).toBeInTheDocument();
    expect(screen.getByText(/I will navigate to the flights page now\./)).toBeInTheDocument();
    expect(screen.getByText(/Task complete/)).toBeInTheDocument();

    // Each event renders only once
    expect(screen.getAllByText(/Search for flights/)).toHaveLength(1);
    expect(screen.getAllByText(/Task complete/)).toHaveLength(1);
  });

  it('should display multiple user tasks from different workers', async () => {
    const store = useMessagesStore.getState();

    store.addEvent({
      worker_id: 'worker-111',
      type: 'task_assigned',
      data: { task_id: 'task-a', worker_id: 'worker-111', prompt: 'First user task' },
    });

    store.addEvent({
      worker_id: 'worker-222',
      type: 'task_assigned',
      data: { task_id: 'task-b', worker_id: 'worker-222', prompt: 'Second user task' },
    });

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/First user task/)).toBeInTheDocument();
    expect(screen.getByText(/Second user task/)).toBeInTheDocument();
    // Each appears only once
    expect(screen.getAllByText(/First user task/)).toHaveLength(1);
    expect(screen.getAllByText(/Second user task/)).toHaveLength(1);
  });

  it('should filter events to a single worker when filterWorkerId is set', async () => {
    const store = useMessagesStore.getState();

    store.addEvent({
      worker_id: 'worker-111',
      type: 'task_assigned',
      data: { task_id: 'task-a', worker_id: 'worker-111', prompt: 'Visible task' },
    });

    store.addEvent({
      worker_id: 'worker-222',
      type: 'task_assigned',
      data: { task_id: 'task-b', worker_id: 'worker-222', prompt: 'Hidden task' },
    });

    store.setFilterWorkerId('worker-111');

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/Visible task/)).toBeInTheDocument();
    expect(screen.queryByText(/Hidden task/)).toBeNull();
  });

  it('should not display UserMessage events (SDK internal turns)', async () => {
    const store = useMessagesStore.getState();

    store.addEvent({
      worker_id: 'worker-abc',
      type: 'task_assigned',
      data: { task_id: 'task-1', worker_id: 'worker-abc', prompt: 'Do something' },
    });

    // UserMessage from SDK turn (should NOT show)
    store.addEvent({
      worker_id: 'worker-abc',
      type: 'message',
      data: {
        task_id: 'task-1',
        worker_id: 'worker-abc',
        __type__: 'UserMessage',
        content: 'SDK internal user turn content',
      },
    });

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/Do something/)).toBeInTheDocument();
    expect(screen.queryByText(/SDK internal user turn content/)).toBeNull();
  });

  it('should show "No events yet" when there are no events', async () => {
    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText('No events yet')).toBeInTheDocument();
  });

  it('should display error events for failed tasks', async () => {
    const store = useMessagesStore.getState();

    store.addEvent({
      worker_id: 'worker-abc',
      type: 'task_assigned',
      data: { task_id: 'task-err', worker_id: 'worker-abc', prompt: 'Task that fails' },
    });

    store.addEvent({
      type: 'error',
      data: { task_id: 'task-err', error: 'Browser crashed unexpectedly' },
    });

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/Task that fails/)).toBeInTheDocument();
    expect(screen.getByText(/Browser crashed unexpectedly/)).toBeInTheDocument();
  });

  it('should display supervisor task submissions exactly once', async () => {
    useMessagesStore.getState().addEvent({
      supervisor_id: 'supervisor-xyz',
      type: 'task_submitted_to_supervisor',
      data: { task_id: 'task-sup', supervisor_id: 'supervisor-xyz', prompt: 'Optimize my workflow' },
    });

    render(<EventStream />);
    await settleEventStream();

    expect(screen.getByText(/Supervisor Task:/)).toBeInTheDocument();
    expect(screen.getAllByText(/Optimize my workflow/)).toHaveLength(1);
  });
});
