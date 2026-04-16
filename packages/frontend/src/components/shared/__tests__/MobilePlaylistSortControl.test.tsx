/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MobilePlaylistSortControl } from '../MobilePlaylistSortControl';
import type { ColumnConfig } from '../../../stores/columnStore';

vi.mock('../../../stores/columnStore', () => ({
  getVisibleColumns: (cols: ColumnConfig[]) => cols.filter((c) => c.visible).map((c) => c.id),
}));

vi.mock('../../Library/columnDefinitions', () => ({
  getColumnDef: (id: string) => {
    const map: Record<string, { label: string; sortField: string }> = {
      artist: { label: 'Artist', sortField: 'artist' },
      album: { label: 'Album', sortField: 'album' },
      duration: { label: 'Duration', sortField: 'duration' },
    };
    return map[id];
  },
}));

const columns: ColumnConfig[] = [
  { id: 'artist', visible: true },
  { id: 'album', visible: true },
  { id: 'duration', visible: true },
  { id: 'year', visible: false },
];

describe('MobilePlaylistSortControl', () => {
  afterEach(() => cleanup());

  it('shows "Sort" label when nothing is selected', () => {
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy={null}
        sortOrder="asc"
        toggleSort={vi.fn()}
        clearSort={vi.fn()}
      />
    );
    expect(screen.getByRole('button', { name: /sort/i })).toBeTruthy();
  });

  it('shows the active column label when sorting', () => {
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy="artist"
        sortOrder="asc"
        toggleSort={vi.fn()}
        clearSort={vi.fn()}
      />
    );
    expect(screen.getByRole('button', { name: /artist/i })).toBeTruthy();
  });

  it('opens the menu and lists Default + Title + visible sortable columns', () => {
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy={null}
        sortOrder="asc"
        toggleSort={vi.fn()}
        clearSort={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /sort/i }));
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent);
    expect(items).toEqual(['Default order', 'Title', 'Artist', 'Album', 'Duration']);
  });

  it('hides hidden columns from the menu', () => {
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy={null}
        sortOrder="asc"
        toggleSort={vi.fn()}
        clearSort={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /sort/i }));
    expect(screen.queryByRole('menuitem', { name: /year/i })).toBeNull();
  });

  it('calls toggleSort when a menu item is tapped', () => {
    const toggleSort = vi.fn();
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy={null}
        sortOrder="asc"
        toggleSort={toggleSort}
        clearSort={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /sort/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /album/i }));
    expect(toggleSort).toHaveBeenCalledWith('album');
  });

  it('calls clearSort and closes when Default order is tapped', () => {
    const clearSort = vi.fn();
    render(
      <MobilePlaylistSortControl
        columns={columns}
        sortBy="artist"
        sortOrder="asc"
        toggleSort={vi.fn()}
        clearSort={clearSort}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /artist/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /default order/i }));
    expect(clearSort).toHaveBeenCalled();
    expect(screen.queryByRole('menu')).toBeNull();
  });
});
