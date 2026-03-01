import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EventItem, shouldShowEvent } from '../../src/components/EventItem';
import type { StreamEvent, SDKMessage } from '../../src/types';

describe('shouldShowEvent', () => {
  const baseEvent: Omit<StreamEvent, 'type' | 'data'> = {
    id: 'event-1',
    worker_id: 'worker-1',
    timestamp: new Date('2024-01-15T10:00:00Z'),
  };

  describe('task_assigned events', () => {
    it('should show task_assigned events', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-1', prompt: 'Do something' },
      };

      expect(shouldShowEvent(event)).toBe(true);
    });
  });

  describe('task_complete events', () => {
    it('should show task_complete events', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_complete',
        data: { task_id: 'task-1', worker_id: 'worker-1' },
      };

      expect(shouldShowEvent(event)).toBe(true);
    });
  });

  describe('error events', () => {
    it('should show error events', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'error',
        data: { error: 'Something went wrong' },
      };

      expect(shouldShowEvent(event)).toBe(true);
    });
  });

  describe('message events', () => {
    it('should show AssistantMessage with text content', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: 'Hello, I am an assistant',
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(true);
    });

    it('should show AssistantMessage with text blocks', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: [{ text: 'Hello from text block' }],
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(true);
    });

    it('should show AssistantMessage with tool use blocks', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: [
            {
              id: 'tool-1',
              name: 'Read',
              input: { file_path: '/etc/passwd' },
            },
          ],
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(true);
    });

    it('should not show AssistantMessage with empty content', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: '',
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(false);
    });

    it('should not show AssistantMessage with null content', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: null,
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(false);
    });

    it('should not show UserMessage', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'UserMessage',
          content: 'User said something',
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(false);
    });

    it('should not show unknown message types', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'SomeOtherMessage',
          content: 'Content',
        } as SDKMessage,
      };

      expect(shouldShowEvent(event)).toBe(false);
    });
  });

  describe('unknown event types', () => {
    it('should not show unknown event types', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'status' as any,
        data: { status: 'idle' },
      };

      expect(shouldShowEvent(event)).toBe(false);
    });
  });
});

describe('EventItem', () => {
  const baseEvent: Omit<StreamEvent, 'type' | 'data'> = {
    id: 'event-1',
    worker_id: 'worker-1',
    timestamp: new Date('2024-01-15T10:00:00Z'),
  };

  describe('rendering', () => {
    it('should render task_assigned event with prompt', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-1', prompt: 'Do something useful' },
      };

      render(<EventItem event={event} />);

      expect(screen.getByText(/Task:/)).toBeInTheDocument();
      expect(screen.getByText(/Do something useful/)).toBeInTheDocument();
    });

    it('should truncate long prompts in task_assigned', () => {
      const longPrompt = 'A'.repeat(200);
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-1', prompt: longPrompt },
      };

      render(<EventItem event={event} />);

      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument();
    });

    it('should render task_complete event', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_complete',
        data: { task_id: 'task-12345678-abcd', worker_id: 'worker-1' },
      };

      render(<EventItem event={event} />);

      expect(screen.getByText(/Task complete/)).toBeInTheDocument();
      expect(screen.getByText(/task-123/)).toBeInTheDocument();
    });

    it('should render error event', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'error',
        data: { error: 'Something went wrong' },
      };

      render(<EventItem event={event} />);

      expect(screen.getByText(/Error:/)).toBeInTheDocument();
      expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    });

    it('should render AssistantMessage with text', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: 'Hello from assistant',
        } as SDKMessage,
      };

      render(<EventItem event={event} />);

      expect(screen.getByText('Hello from assistant')).toBeInTheDocument();
    });

    it('should render AssistantMessage with tool use', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'AssistantMessage',
          content: [
            {
              id: 'tool-1',
              name: 'Read',
              input: { file_path: '/etc/passwd' },
            },
          ],
        } as SDKMessage,
      };

      render(<EventItem event={event} />);

      expect(screen.getByText(/Tool:/)).toBeInTheDocument();
      expect(screen.getByText('Read')).toBeInTheDocument();
    });

    it('should not render UserMessage', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'message',
        data: {
          task_id: 'task-1',
          worker_id: 'worker-1',
          __type__: 'UserMessage',
          content: 'User message content',
        } as SDKMessage,
      };

      const { container } = render(<EventItem event={event} />);

      expect(container.firstChild).toBeNull();
    });

    it('should display worker id button', () => {
      const event: StreamEvent = {
        ...baseEvent,
        worker_id: 'worker-12345678-abcd',
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-12345678-abcd', prompt: 'Task' },
      };

      render(<EventItem event={event} />);

      expect(screen.getByRole('button', { name: /\[worker-1/ })).toBeInTheDocument();
    });

    it('should display timestamp', () => {
      const event: StreamEvent = {
        ...baseEvent,
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-1', prompt: 'Task' },
      };

      render(<EventItem event={event} />);

      // Timestamp format is HH:MM:SS
      expect(screen.getByText(/\d{2}:\d{2}:\d{2}/)).toBeInTheDocument();
    });
  });

  describe('worker click handler', () => {
    it('should call onWorkerClick when worker id is clicked', () => {
      const onWorkerClick = vi.fn();
      const event: StreamEvent = {
        ...baseEvent,
        worker_id: 'worker-123',
        type: 'task_assigned',
        data: { task_id: 'task-1', worker_id: 'worker-123', prompt: 'Task' },
      };

      render(<EventItem event={event} onWorkerClick={onWorkerClick} />);

      const workerButton = screen.getByRole('button');
      fireEvent.click(workerButton);

      expect(onWorkerClick).toHaveBeenCalledWith('worker-123');
    });

    it('should not call onWorkerClick if no worker_id', () => {
      const onWorkerClick = vi.fn();
      const event: StreamEvent = {
        id: 'event-1',
        worker_id: undefined,
        timestamp: new Date('2024-01-15T10:00:00Z'),
        type: 'error',
        data: { error: 'Global error' },
      };

      render(<EventItem event={event} onWorkerClick={onWorkerClick} />);

      // No worker button should be rendered
      expect(screen.queryByRole('button')).toBeNull();
    });
  });
});
