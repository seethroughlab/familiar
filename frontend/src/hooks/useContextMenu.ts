import { useState, useCallback } from 'react';

export interface ContextMenuState<T> {
  isOpen: boolean;
  item: T | null;
  position: { x: number; y: number };
}

export function useContextMenu<T>() {
  const [state, setState] = useState<ContextMenuState<T>>({
    isOpen: false,
    item: null,
    position: { x: 0, y: 0 },
  });

  const open = useCallback((item: T, event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setState({
      isOpen: true,
      item,
      position: { x: event.clientX, y: event.clientY },
    });
  }, []);

  const close = useCallback(() => {
    setState((prev) => ({ ...prev, isOpen: false, item: null }));
  }, []);

  return { state, open, close };
}
