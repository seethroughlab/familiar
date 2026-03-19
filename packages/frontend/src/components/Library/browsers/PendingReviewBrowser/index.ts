import { lazy } from 'react';
import { registerBrowser } from '../../types';

const LazyPendingReviewBrowser = lazy(() => import('./PendingReviewBrowser'));

registerBrowser(
  {
    id: 'pending-review',
    name: 'Pending Review',
    description: 'Review newly discovered tracks',
    icon: 'Inbox',
    category: 'traditional',
    requiresFeatures: false,
    requiresEmbeddings: false,
  },
  LazyPendingReviewBrowser
);
