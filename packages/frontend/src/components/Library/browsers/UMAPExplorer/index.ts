import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyUMAPExplorer = lazy(() => import('./UMAPExplorer'));

registerBrowser(
  {
    id: 'umap-explorer',
    name: '3D Explorer',
    description: 'Explore your entire library in 3D space based on audio similarity',
    icon: 'Box',
    category: 'spatial',
    requiresFeatures: false,
    requiresEmbeddings: true,
  },
  LazyUMAPExplorer
);
