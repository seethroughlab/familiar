/**
 * LibraryBrowser - Thin wrapper that receives a browserId from the route
 * and renders LibraryView with the correct browser selected.
 */
import { LibraryView } from './LibraryView';

interface Props {
  browserId: string;
}

export function LibraryBrowser({ browserId }: Props) {
  return <LibraryView browserId={browserId} />;
}
