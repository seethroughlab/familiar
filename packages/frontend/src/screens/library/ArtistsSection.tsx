/** Library → Artists (ADR-0126 point 4): merge artists the scanner split. */
import { SectionPage } from '../AdminPage';
import { ArtistsPage } from '../ArtistsPage';

export function ArtistsSection() {
  return (
    <SectionPage title="Artists" subtitle="Merge duplicate artists and fix name variants">
      <ArtistsPage />
    </SectionPage>
  );
}
