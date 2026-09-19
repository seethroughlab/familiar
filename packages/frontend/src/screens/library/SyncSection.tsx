/**
 * Library → Sync (ADR-0126 point 4): scan the collection, watch it, cancel it.
 *
 * Only the sync. Analysis configuration used to sit beside it under "Scan & analysis"; it is
 * the pipeline's concern and lives under Analysis → Configuration now (point 5).
 */
import { SectionPage } from '../AdminPage';
import { LibrarySync } from '../../panels/library/LibrarySync';

export function SyncSection() {
  return (
    <SectionPage
      title="Sync"
      subtitle="Scan the library for new, changed and missing files; re-analysis runs as part of it"
    >
      <LibrarySync />
    </SectionPage>
  );
}
