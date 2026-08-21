/**
 * The catalog, loaded once per document and shared by everything that needs it.
 *
 * A module-level promise rather than a store: the listing is static for the life of the page (a
 * dropped-in folder is picked up by `reloadToken` building a fresh web view, not by a watcher), and
 * every consumer wants the same answer. Two callers must not produce two fetches, because the
 * second would publish the catalog again and the native picker would be told twice.
 */
import { useEffect, useState } from 'react';
import { loadVisualizerCatalog, publishCatalog, type CatalogEntry } from '../../services/visualizerCatalog';

let pending: Promise<CatalogEntry[]> | null = null;

export function catalogPromise(): Promise<CatalogEntry[]> {
  if (!pending) {
    pending = loadVisualizerCatalog().then((entries) => {
      publishCatalog(entries);
      return entries;
    });
  }
  return pending;
}

export function useVisualizerCatalog(): CatalogEntry[] {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  useEffect(() => {
    let alive = true;
    catalogPromise().then((loaded) => { if (alive) setEntries(loaded); });
    return () => { alive = false; };
  }, []);
  return entries;
}
