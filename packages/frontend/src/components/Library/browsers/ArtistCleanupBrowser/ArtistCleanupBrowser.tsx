/**
 * ArtistCleanupBrowser — full-page home for merging duplicate artists.
 *
 * Relocated out of Settings (it's an action queue, not a setting). Renders the existing
 * canonical-artist merge panel inside a standard browser page container.
 */
import type { BrowserProps } from '../../types';
import { ArtistMergePanel } from './ArtistMergePanel';

function ArtistCleanupBrowser(_props: BrowserProps) {
  return (
    <div className="p-4 max-w-4xl mx-auto">
      <ArtistMergePanel />
    </div>
  );
}

export default ArtistCleanupBrowser;
