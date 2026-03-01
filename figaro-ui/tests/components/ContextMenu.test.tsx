import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ContextMenu } from '../../src/components/ContextMenu';

describe('ContextMenu', () => {
  const defaultItems = [
    { label: 'Edit', onClick: vi.fn() },
    { label: 'Remove', onClick: vi.fn(), danger: true },
  ];

  const renderMenu = (overrides = {}) =>
    render(
      <ContextMenu
        x={100}
        y={200}
        items={defaultItems}
        onClose={vi.fn()}
        {...overrides}
      />
    );

  it('should render all menu items', () => {
    renderMenu();
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.getByText('Remove')).toBeInTheDocument();
  });

  it('should position at given coordinates', () => {
    const { container } = renderMenu();
    const menu = container.firstChild as HTMLElement;
    expect(menu.style.left).toBe('100px');
    expect(menu.style.top).toBe('200px');
  });

  it('should call onClick and onClose when item is clicked', () => {
    const onClick = vi.fn();
    const onClose = vi.fn();
    render(
      <ContextMenu
        x={0}
        y={0}
        items={[{ label: 'Action', onClick }]}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByText('Action'));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('should not call onClick when item is disabled', () => {
    const onClick = vi.fn();
    const onClose = vi.fn();
    render(
      <ContextMenu
        x={0}
        y={0}
        items={[{ label: 'Disabled', onClick, disabled: true }]}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByText('Disabled'));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('should close on Escape key', () => {
    const onClose = vi.fn();
    renderMenu({ onClose });

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('should close on click outside', () => {
    const onClose = vi.fn();
    renderMenu({ onClose });

    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('should close on window resize', () => {
    const onClose = vi.fn();
    renderMenu({ onClose });

    fireEvent.resize(window);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('should render disabled item with disabled attribute', () => {
    render(
      <ContextMenu
        x={0}
        y={0}
        items={[{ label: 'Nope', onClick: vi.fn(), disabled: true }]}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Nope')).toBeDisabled();
  });
});
