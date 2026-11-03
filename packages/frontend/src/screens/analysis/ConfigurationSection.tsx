/**
 * Analysis → Configuration (ADR-0126 point 5): everything that decides how a track is analysed.
 *
 * CLAP embeddings and naming recordings through AcoustID, previously on three pages. AcoustID's
 * health sits beside its toggle, because "is it on" and "is it working" are the two halves of one
 * question; the AcoustID *key* is the provider card's business and is linked, not repeated. The
 * community cache's toggles were here until ADR-0159 removed it.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { systemApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { AnalysisSettings } from '../../panels/library/AnalysisSettings';
import { SourceHealth } from '../../panels/server/ProviderCards';
import { RecordingNames } from '../../panels/tools/RecordingNames';
import { SectionPage } from '../AdminPage';

export function ConfigurationSection() {
  const discovery = useQuery({ queryKey: queryKeys.discoverySources.all, queryFn: systemApi.discoverySources, staleTime: 30_000 });
  const acoustid = discovery.data?.sources.find((s) => s.source === 'acoustid');

  return (
    <SectionPage title="Configuration" subtitle="What runs on each track">
      <AnalysisSettings />
      <RecordingNames />
      {acoustid && (
        <div className="bg-zinc-800/50 rounded-lg p-4 space-y-1">
          <SourceHealth source={acoustid} />
        </div>
      )}
      <p className="text-xs text-zinc-500">
        AcoustID's key is on its{' '}
        <Link to="/server/providers" className="text-blue-400 hover:text-blue-300">provider card</Link>.
      </p>
    </SectionPage>
  );
}
