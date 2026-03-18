import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyProposedChangesBrowser = lazy(() => import('./ProposedChangesBrowser'));

registerBrowser(
  {
    id: 'proposed-changes',
    name: 'Proposed Changes',
    description: 'Review metadata corrections',
    icon: 'FileEdit',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  LazyProposedChangesBrowser
);
