import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyDiscoverBrowser = lazy(() => import('./DiscoverBrowser'));

registerBrowser(
  {
    id: 'discover',
    name: 'Discover',
    description: 'New releases, recommendations, and music to explore',
    icon: 'Sparkles',
    category: 'discovery',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  LazyDiscoverBrowser
);
