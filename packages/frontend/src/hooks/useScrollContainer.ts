/**
 * Context providing a ref to the main scroll container (AppShell's content area).
 *
 * Mobile browsers (single-scroll) need this so child components can attach
 * virtualizers to the shared scroll container instead of needing their own.
 */
import { createContext, useContext, type RefObject } from 'react';

export const ScrollContainerContext = createContext<RefObject<HTMLDivElement | null> | null>(null);

export function useScrollContainer(): RefObject<HTMLDivElement | null> | null {
  return useContext(ScrollContainerContext);
}
