import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyNewReleasesDetail = lazy(() => import('./NewReleasesDetail'));

registerBrowser(
  {
    id: 'new-releases-detail',
    name: 'New Releases',
    description: 'Recent albums from artists in your library',
    icon: 'Disc3',
    category: 'discovery',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  LazyNewReleasesDetail,
);
