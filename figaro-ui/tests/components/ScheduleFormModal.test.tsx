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
  run_at: null,
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

  it('sends null self_learning_max_runs when field is cleared', async () => {
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

    // Clear the max learning runs field (default is 4, clear to get unlimited)
    const unlimitedInputs = screen.getAllByPlaceholderText('Unlimited');
    const maxLearningRunsInput = unlimitedInputs[unlimitedInputs.length - 1];
    fireEvent.change(maxLearningRunsInput, { target: { value: '' } });

    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_learning_max_runs: null,
        })
      );
    });
  });

  it('sends default self_learning_max_runs of 4 for new tasks', async () => {
    const createdTask = createMockScheduledTask({ self_learning: true, self_learning_max_runs: 4 });
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

    // Don't change max learning runs (should default to 4)
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          self_learning_max_runs: 4,
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

describe('ScheduleFormModal - run_at', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the run_at field in the form', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    expect(screen.getByText('Run At (optional)')).toBeInTheDocument();
    expect(screen.getByText('Leave empty to start immediately')).toBeInTheDocument();
  });

  it('run_at is included in the create payload when set', async () => {
    const createdTask = createMockScheduledTask({ run_at: '2024-06-15T10:00:00.000Z' });
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

    // Set run_at via the datetime-local input
    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    // Submit
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          run_at: expect.any(String),
        })
      );
      // Verify run_at is a non-null ISO string
      const callArgs = mockCreateScheduledTask.mock.calls[0][0];
      expect(callArgs.run_at).not.toBeNull();
    });
  });

  it('run_at is null in the create payload when not set', async () => {
    const createdTask = createMockScheduledTask();
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

    // Do NOT set run_at

    // Submit
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          run_at: null,
        })
      );
    });
  });

  it('one-time task: run_at set with interval 0', async () => {
    const createdTask = createMockScheduledTask({ run_at: '2024-06-15T10:00:00.000Z', interval_seconds: 0 });
    mockCreateScheduledTask.mockResolvedValueOnce(createdTask);

    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Daily price check'), {
      target: { value: 'One-Time Task' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://example.com'), {
      target: { value: 'https://example.com' },
    });
    await fillPrompt('Do something once');

    // Set run_at
    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    // Set interval to 0 for one-time
    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '0' } });

    // Submit
    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          run_at: expect.any(String),
          interval_seconds: 0,
        })
      );
    });
  });

  it('pre-populates run_at when editing a task with run_at set', () => {
    const editTask = createMockScheduledTask({ run_at: '2024-06-15T10:00:00.000Z' });

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    const runAtInput = screen.getByLabelText('Run At (optional)') as HTMLInputElement;
    expect(runAtInput.value).not.toBe('');
  });

  it('run_at field is empty when editing a task without run_at', () => {
    const editTask = createMockScheduledTask({ run_at: null });

    render(<ScheduleFormModal onClose={mockOnClose} editTask={editTask} />);

    const runAtInput = screen.getByLabelText('Run At (optional)') as HTMLInputElement;
    expect(runAtInput.value).toBe('');
  });

  it('shows one-time help text when run_at is set and interval is 0', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Set run_at
    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    // Set interval to 0
    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '0' } });

    expect(screen.getByText('One-time task at the specified date/time')).toBeInTheDocument();
  });

  it('shows deferred recurring help text when run_at is set and interval > 0', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Set run_at
    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    // Keep interval > 0 (default is 60)
    expect(screen.getByText('Recurring task starting at the specified date/time')).toBeInTheDocument();
  });

  it('changes interval label when run_at is set', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Initially the label should be "Run Every"
    expect(screen.getByText('Run Every')).toBeInTheDocument();

    // Set run_at
    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    // Now the label should change
    expect(screen.getByText('Repeat Every (0 = one-time)')).toBeInTheDocument();
  });
});

describe('ScheduleFormModal - schedule explainer', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows recurring schedule explanation by default', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('Runs immediately');
    expect(explainer.textContent).toContain('every 60 minutes');
  });

  it('updates explanation when interval changes', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Change interval to 2 hours
    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '2' } });
    const unitSelect = screen.getByDisplayValue('Minutes');
    fireEvent.change(unitSelect, { target: { value: 'hours' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('every 2 hours');
  });

  it('shows one-time explanation when run_at is set and interval is 0', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '0' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('Runs once on');
  });

  it('shows deferred recurring explanation when run_at is set with interval', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const runAtInput = screen.getByLabelText('Run At (optional)');
    fireEvent.change(runAtInput, { target: { value: '2024-06-15T10:00' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('First run on');
    expect(explainer.textContent).toContain('then every 60 minutes');
  });

  it('shows max runs in explanation when set', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const maxRunsInput = screen.getAllByPlaceholderText('Unlimited')[0];
    fireEvent.change(maxRunsInput, { target: { value: '5' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('stop after 5 runs');
  });

  it('shows singular unit for interval of 1', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '1' } });
    const unitSelect = screen.getByDisplayValue('Minutes');
    fireEvent.change(unitSelect, { target: { value: 'hours' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('every hour');
  });

  it('shows fallback message when no schedule is configured', () => {
    render(<ScheduleFormModal onClose={mockOnClose} />);

    // Set interval to 0 without run_at
    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '0' } });

    const explainer = screen.getByTestId('schedule-explainer');
    expect(explainer.textContent).toContain('Set an interval or a specific date/time');
  });
});
