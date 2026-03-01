import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DesktopGrid } from '../../src/components/DesktopGrid';
import { useWorkersStore } from '../../src/stores/workers';
import type { Worker } from '../../src/types';
import * as desktopWorkersApi from '../../src/api/desktopWorkers';

// Mock VNCViewer since it relies on noVNC internals
vi.mock('../../src/components/VNCViewer', () => ({
  VNCViewer: () => <div data-testid="vnc-viewer" />,
}));

// Mock the desktop workers API
vi.mock('../../src/api/desktopWorkers', () => ({
  registerDesktopWorker: vi.fn(),
  removeDesktopWorker: vi.fn(),
  updateDesktopWorker: vi.fn(),
}));

const mockRemove = vi.mocked(desktopWorkersApi.removeDesktopWorker);
const mockUpdate = vi.mocked(desktopWorkersApi.updateDesktopWorker);

const createWorker = (id: string, agentConnected = false): Worker => ({
  id,
  status: 'idle',
  capabilities: [],
  novnc_url: `ws://host:6080/websockify`,
  agent_connected: agentConnected,
  metadata: { os: 'linux' },
});

describe('DesktopGrid', () => {
  const onWorkerClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useWorkersStore.setState({ workers: new Map(), selectedWorkerId: null });
  });

  it('should show empty state when no workers', () => {
    render(<DesktopGrid onWorkerClick={onWorkerClick} />);
    expect(screen.getByText('No workers connected')).toBeInTheDocument();
  });

  it('should render worker cards', () => {
    const w = createWorker('desktop-01');
    useWorkersStore.getState().setWorkers([w]);

    render(<DesktopGrid onWorkerClick={onWorkerClick} />);
    expect(screen.getByText('desktop-')).toBeInTheDocument();
  });

  describe('context menu', () => {
    it('should open context menu on right-click', () => {
      const w = createWorker('desktop-01');
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      // Right-click the worker card
      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });

      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Remove')).toBeInTheDocument();
    });

    it('should disable Remove when agent is connected', () => {
      const w = createWorker('desktop-01', true);
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });

      expect(screen.getByText('Remove')).toBeDisabled();
    });

    it('should enable Remove when agent is not connected', () => {
      const w = createWorker('desktop-01', false);
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });

      expect(screen.getByText('Remove')).not.toBeDisabled();
    });

    it('should call removeDesktopWorker when Remove is clicked', async () => {
      mockRemove.mockResolvedValueOnce(undefined);
      const w = createWorker('desktop-01');
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      fireEvent.click(screen.getByText('Remove'));

      await waitFor(() => {
        expect(mockRemove).toHaveBeenCalledWith('desktop-01');
      });
    });

    it('should close context menu on Escape', () => {
      const w = createWorker('desktop-01');
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      expect(screen.getByText('Edit')).toBeInTheDocument();

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByText('Edit')).not.toBeInTheDocument();
    });
  });

  describe('edit mode', () => {
    it('should open edit form when Edit is clicked from context menu', () => {
      const w = createWorker('desktop-01');
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      fireEvent.click(screen.getByText('Edit'));

      // The edit form should appear with the correct heading
      expect(screen.getByText('Edit Desktop Worker')).toBeInTheDocument();
      expect(screen.getByText('Save Changes')).toBeInTheDocument();
    });

    it('should pre-populate form fields in edit mode', () => {
      const w = createWorker('desktop-01');
      w.novnc_url = 'ws://myhost:6080/websockify';
      w.metadata = { os: 'macos' };
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      fireEvent.click(screen.getByText('Edit'));

      const idInput = screen.getByDisplayValue('desktop-01');
      expect(idInput).toBeInTheDocument();

      const urlInput = screen.getByDisplayValue('ws://myhost:6080/websockify');
      expect(urlInput).toBeInTheDocument();

      // OS should be pre-selected
      const osSelect = screen.getByDisplayValue('macOS');
      expect(osSelect).toBeInTheDocument();
    });

    it('should call updateDesktopWorker on edit form submit', async () => {
      mockUpdate.mockResolvedValueOnce(undefined);
      const w = createWorker('desktop-01');
      w.novnc_url = 'ws://host:6080/websockify';
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      // Open context menu -> Edit
      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      fireEvent.click(screen.getByText('Edit'));

      // Change the URL
      const urlInput = screen.getByDisplayValue('ws://host:6080/websockify');
      fireEvent.change(urlInput, { target: { value: 'ws://newhost:6080/websockify' } });

      // Submit the form
      fireEvent.click(screen.getByText('Save Changes'));

      await waitFor(() => {
        expect(mockUpdate).toHaveBeenCalledWith(
          'desktop-01',
          undefined,
          'ws://newhost:6080/websockify',
          { os: 'linux' },
          undefined,
          undefined,
        );
      });
    });

    it('should send new_worker_id when ID is changed in edit mode', async () => {
      mockUpdate.mockResolvedValueOnce(undefined);
      const w = createWorker('desktop-01');
      w.novnc_url = 'ws://host:6080/websockify';
      useWorkersStore.getState().setWorkers([w]);

      render(<DesktopGrid onWorkerClick={onWorkerClick} />);

      const card = screen.getByText('desktop-').closest('[class*="bg-cctv-panel"]')!;
      fireEvent.contextMenu(card, { clientX: 150, clientY: 250 });
      fireEvent.click(screen.getByText('Edit'));

      // Change the worker ID (rename)
      const idInput = screen.getByDisplayValue('desktop-01');
      fireEvent.change(idInput, { target: { value: 'desktop-renamed' } });

      fireEvent.click(screen.getByText('Save Changes'));

      await waitFor(() => {
        expect(mockUpdate).toHaveBeenCalledWith(
          'desktop-01',
          'desktop-renamed',
          'ws://host:6080/websockify',
          { os: 'linux' },
          undefined,
          undefined,
        );
      });
    });
  });
});
