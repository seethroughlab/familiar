/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExternalAlbumCard } from '../ExternalAlbumCard';
import type { ExternalAlbum } from '../../../api/discovery';

// Stub AlbumArtwork — it touches stores/network we don't need here
vi.mock('../../AlbumArtwork', () => ({
  AlbumArtwork: () => <div data-testid="album-artwork" />,
}));

const baseAlbum: ExternalAlbum = {
  id: 'cache-row-1',
  artist_name: 'Sigur Rós',
  release_name: '( )',
  release_type: 'Album',
  release_date: '2024-06-01',
  artwork_url: 'https://example.com/cover.jpg',
  external_url: null,
  track_count: 8,
  match_score: 0.9,
  seed_artist: 'Radiohead',
  local_album_match: false,
  dismissed: false,
  discovered_at: '2024-06-15T00:00:00Z',
  purchase_links: {
    bandcamp: { name: 'Bandcamp', url: 'https://bandcamp.com/x' },
    amazon: { name: 'Amazon Music', url: 'https://amazon.com/x' },
  },
};

describe('ExternalAlbumCard', () => {
  afterEach(() => cleanup());

  describe('grid layout', () => {
    it('renders the release name, artist, and context label', () => {
      render(
        <ExternalAlbumCard album={baseAlbum} contextLabel="NEW RELEASE · Jun 2024" />,
      );
      expect(screen.getByText('( )')).toBeTruthy();
      expect(screen.getByText('Sigur Rós')).toBeTruthy();
      expect(screen.getByText('NEW RELEASE · Jun 2024')).toBeTruthy();
    });

    it('shows formatted release type and date below artist', () => {
      render(
        <ExternalAlbumCard album={baseAlbum} contextLabel="NEW RELEASE" />,
      );
      // ALBUM · Jun 2024 (uppercased type + formatted month/year)
      expect(screen.getByText(/ALBUM · Jun 2024/)).toBeTruthy();
    });

    it('shows the In library badge when local_album_match is true', () => {
      const owned: ExternalAlbum = { ...baseAlbum, local_album_match: true };
      render(<ExternalAlbumCard album={owned} contextLabel="NEW RELEASE" />);
      expect(screen.getByText(/in library/i)).toBeTruthy();
    });

    it('does NOT render dismiss button when onDismiss is not provided', () => {
      render(<ExternalAlbumCard album={baseAlbum} contextLabel="NEW RELEASE" />);
      expect(screen.queryByRole('button', { name: /dismiss/i })).toBeNull();
    });

    it('calls onDismiss with the album id when X button is clicked', () => {
      const onDismiss = vi.fn();
      render(
        <ExternalAlbumCard
          album={baseAlbum}
          contextLabel="NEW RELEASE"
          onDismiss={onDismiss}
        />,
      );
      const dismissBtn = screen.getByRole('button', { name: /dismiss/i });
      fireEvent.click(dismissBtn);
      expect(onDismiss).toHaveBeenCalledWith('cache-row-1');
    });

    it('does not render the Find dropdown when there are no purchase links', () => {
      const noLinks: ExternalAlbum = { ...baseAlbum, purchase_links: {} };
      render(<ExternalAlbumCard album={noLinks} contextLabel="NEW RELEASE" />);
      expect(screen.queryByRole('button', { name: /find/i })).toBeNull();
    });

    it('opens the purchase links popover when Find is clicked', () => {
      render(<ExternalAlbumCard album={baseAlbum} contextLabel="NEW RELEASE" />);
      fireEvent.click(screen.getByRole('button', { name: /find/i }));
      expect(screen.getByText('Bandcamp')).toBeTruthy();
      expect(screen.getByText('Amazon Music')).toBeTruthy();
    });
  });

  describe('list layout', () => {
    it('renders artist + release type/date inline', () => {
      render(
        <ExternalAlbumCard
          album={baseAlbum}
          contextLabel="NEW RELEASE"
          layout="list"
        />,
      );
      expect(screen.getByText('( )')).toBeTruthy();
      // Artist + " · ALBUM · Jun 2024" appear together in list mode
      expect(screen.getByText(/Sigur Rós/)).toBeTruthy();
    });

    it('shows in-library pill in list mode when local_album_match is true', () => {
      render(
        <ExternalAlbumCard
          album={{ ...baseAlbum, local_album_match: true }}
          contextLabel="NEW RELEASE"
          layout="list"
        />,
      );
      expect(screen.getByText(/in library/i)).toBeTruthy();
    });
  });

  describe('release date formatting edge cases', () => {
    it('falls back to NEW RELEASE label when release_date is null', () => {
      const noDate: ExternalAlbum = { ...baseAlbum, release_date: null };
      render(<ExternalAlbumCard album={noDate} contextLabel="NEW RELEASE" />);
      expect(screen.getByText('NEW RELEASE')).toBeTruthy();
    });

    it('handles invalid release_date gracefully', () => {
      const bad: ExternalAlbum = { ...baseAlbum, release_date: 'not-a-date' };
      render(<ExternalAlbumCard album={bad} contextLabel="NEW RELEASE" />);
      // Should still render the title without throwing
      expect(screen.getByText('( )')).toBeTruthy();
    });
  });
});
