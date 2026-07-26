import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyArtistCleanupBrowser = lazy(() => import('./ArtistCleanupBrowser'));

registerBrowser(
  {
    id: 'artist-cleanup',
    name: 'Artist Cleanup',
    description: 'Merge duplicate artists',
    icon: 'Combine',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  LazyArtistCleanupBrowser
);
