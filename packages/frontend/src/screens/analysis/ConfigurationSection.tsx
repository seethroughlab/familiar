/**
 * Analysis → Configuration (ADR-0126 point 5): everything that decides how a track is analysed.
 *
 * CLAP embeddings, the community cache (use and contribute), naming recordings through AcoustID —
 * previously on three pages. The community cache's own health sits beside its toggles, because
 * "is it on" and "is it working" are the two halves of one question; the AcoustID *key* is the
 * provider card's business and is linked, not repeated.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { AnalysisSettings } from '../../panels/library/AnalysisSettings';
import { SourceHealth } from '../../panels/server/ProviderCards';
import { CommunityCache } from '../../panels/tools/CommunityCache';
import { SectionPage } from '../AdminPage';

export function ConfigurationSection() {
  const discovery = useQuery({ queryKey: queryKeys.discoverySources.all, queryFn: systemApi.discoverySources, staleTime: 30_000 });
  const cache = discovery.data?.sources.find((s) => s.source === 'community_cache_claims');

  return (
    <SectionPage title="Configuration" subtitle="What runs on each track, and where embeddings come from">
      <AnalysisSettings />
      <CommunityCache />
      {cache && (
        <div className="bg-zinc-800/50 rounded-lg p-4 space-y-1">
          <SourceHealth source={cache} />
        </div>
      )}
      <p className="text-xs text-zinc-500">
        AcoustID's key is on its{' '}
        <Link to="/server/providers" className="text-blue-400 hover:text-blue-300">provider card</Link>.
      </p>
    </SectionPage>
  );
}
