import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ScheduleFormModal } from '../../src/components/ScheduleFormModal';
import type { ScheduledTask } from '../../src/types';
import * as scheduledTasksApi from '../../src/api/scheduledTasks';

// Mock the scheduledTasks API module
vi.mock('../../src/api/scheduledTasks', () => ({
  createScheduledTask: vi.fn(),
  updateScheduledTask: vi.fn(),
}));

// Mock the scheduledTasks store
vi.mock('../../src/stores/scheduledTasks', () => ({
  useScheduledTasksStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      addTask: vi.fn(),
      updateTask: vi.fn(),
    })
  ),
}));

const mockCreateScheduledTask = vi.mocked(scheduledTasksApi.createScheduledTask);
const mockUpdateScheduledTask = vi.mocked(scheduledTasksApi.updateScheduledTask);

const createMockScheduledTask = (overrides: Partial<ScheduledTask> = {}): ScheduledTask => ({
  schedule_id: 'sched-1',
  name: 'Test Task',
  prompt: 'Do something',
  start_url: 'https://example.com',
  interval_seconds: 3600,
  enabled: true,
  created_at: '2024-01-01T00:00:00Z',
  last_run_at: null,
  next_run_at: '2024-01-01T01:00:00Z',
  run_count: 0,
  options: {},
  parallel_workers: 1,
  max_runs: null,
  notify_on_complete: false,
  self_learning: false,
  self_healing: false,
  self_learning_max_runs: null,
  self_learning_run_count: 0,
  ...overrides,
});

/** Opens the expanded prompt editor, types a value, and closes it. */
async function fillPrompt(value: string) {
  // Click the description preview area to open the expanded editor
  fireEvent.click(screen.getByText('Describe what the agent should do...'));
  // The expanded editor renders a textarea
  const textarea = screen.getByTestId('prompt-editor');
  fireEvent.change(textarea, { target: { value } });
  // Close the editor
  fireEvent.click(screen.getByText('Done'));
}

describe('ScheduleFormModal - self-healing', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders self-healing checkbox', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    expect(screen.getByLabelText(/Self-Healing/)).toBeInTheDocument();
  });

  it('self-healing defaults to checked when creating a new scheduled task', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it('self-healing is pre-populated when editing a task with self_healing=true', () => {
    const editTask = createMockScheduledTask({ self_healing: true });

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it('self-healing is unchecked when editing a task with self_healing=false', () => {
    const editTask = createMockScheduledTask({ self_healing: false });

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it('self-healing included in create payload when checked', async () => {
    const createdTask = createMockScheduledTask({ self_healing: true });
    mockCreateScheduledTask.mockResolvedValueOnce(createdTask);

    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Daily price check'), {
      target: { value: 'Test Task' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://example.com'), {
      target: { value: 'https://example.com' },
    });
    await fillPrompt('Do something');

    // Self-healing defaults to checked, no need to click

    // Submit the form
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_healing: true,
        })
      );
    });
  });

  it('self-healing included in create payload as false when unchecked', async () => {
    const createdTask = createMockScheduledTask({ self_healing: false });
    mockCreateScheduledTask.mockResolvedValueOnce(createdTask);

    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Daily price check'), {
      target: { value: 'Test Task' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://example.com'), {
      target: { value: 'https://example.com' },
    });
    await fillPrompt('Do something');

    // Uncheck self-healing (now defaults to checked)
    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    fireEvent.click(checkbox);

    // Submit
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_healing: false,
        })
      );
    });
  });

  it('self-healing included in update payload when toggled', async () => {
    const editTask = createMockScheduledTask({ self_healing: false });
    const updatedTask = createMockScheduledTask({ self_healing: true });
    mockUpdateScheduledTask.mockResolvedValueOnce(updatedTask);

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    // Toggle self-healing on
    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    fireEvent.click(checkbox);

    // Submit the form
    fireEvent.click(screen.getByText('Save Changes'));

    await waitFor(() => {
      expect(mockUpdateScheduledTask).toHaveBeenCalledWith(
        'sched-1',
        expect.objectContaining({
          self_healing: true,
        })
      );
    });
  });

  it('self-healing included in update payload when toggled off', async () => {
    const editTask = createMockScheduledTask({ self_healing: true });
    const updatedTask = createMockScheduledTask({ self_healing: false });
    mockUpdateScheduledTask.mockResolvedValueOnce(updatedTask);

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    // Toggle self-healing off
    const checkbox = screen.getByLabelText(/Self-Healing/) as HTMLInputElement;
    fireEvent.click(checkbox);

    // Submit the form
    fireEvent.click(screen.getByText('Save Changes'));

    await waitFor(() => {
      expect(mockUpdateScheduledTask).toHaveBeenCalledWith(
        'sched-1',
        expect.objectContaining({
          self_healing: false,
        })
      );
    });
  });

  it('renders self-healing description text', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    expect(
      screen.getByText('Automatically retry failed tasks with supervisor analysis')
    ).toBeInTheDocument();
  });

  it('self-learning defaults to checked when creating a new scheduled task', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const checkbox = screen.getByLabelText(/Self-Learning/) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it('shows max learning runs field when self-learning is enabled', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Self-learning defaults to checked, so the field should be visible
    expect(screen.getByText('Max Learning Runs (optional)')).toBeInTheDocument();
    expect(screen.getByText(/Stop optimizing prompt after/)).toBeInTheDocument();
  });

  it('hides max learning runs field when self-learning is unchecked', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Uncheck self-learning
    const checkbox = screen.getByLabelText(/Self-Learning/) as HTMLInputElement;
    fireEvent.click(checkbox);

    expect(screen.queryByText(/Stop optimizing prompt after/)).not.toBeInTheDocument();
  });

  it('includes self_learning_max_runs in create payload', async () => {
    const createdTask = createMockScheduledTask({ self_learning: true, self_learning_max_runs: 5 });
    mockCreateScheduledTask.mockResolvedValueOnce(createdTask);

    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Daily price check'), {
      target: { value: 'Test Task' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://example.com'), {
      target: { value: 'https://example.com' },
    });
    await fillPrompt('Do something');

    // Set max learning runs - there are multiple "Unlimited" placeholders (Max Runs and Max Learning Runs)
    // Use getAllByPlaceholderText and target the second one (Max Learning Runs)
    const unlimitedInputs = screen.getAllByPlaceholderText('Unlimited');
    const maxLearningRunsInput = unlimitedInputs[unlimitedInputs.length - 1];
    fireEvent.change(maxLearningRunsInput, { target: { value: '5' } });

    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_learning_max_runs: 5,
        })
      );
    });
  });

  it('sends null self_learning_max_runs when field is empty', async () => {
    const createdTask = createMockScheduledTask({ self_learning: true });
    mockCreateScheduledTask.mockResolvedValueOnce(createdTask);

    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Daily price check'), {
      target: { value: 'Test Task' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://example.com'), {
      target: { value: 'https://example.com' },
    });
    await fillPrompt('Do something');

    // Don't set max learning runs (leave empty = unlimited)
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_learning_max_runs: null,
        })
      );
    });
  });

  it('pre-populates max learning runs when editing', () => {
    const editTask = createMockScheduledTask({ self_learning: true, self_learning_max_runs: 10 });

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    const unlimitedInputs = screen.getAllByPlaceholderText('Unlimited');
    const maxLearningRunsInput = unlimitedInputs[unlimitedInputs.length - 1] as HTMLInputElement;
    expect(maxLearningRunsInput.value).toBe('10');
  });
});
