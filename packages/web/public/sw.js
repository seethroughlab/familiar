/**
 * Tombstone service worker (ADR-0059).
 *
 * This is not a service worker in any useful sense — it exists to remove the one that used to be
 * here. **Do not delete it, and do not let it 404.**
 *
 * The PWA is gone, but every browser that visited before it went keeps running the old Workbox
 * worker, which serves the app shell cache-first. That means the old `index.html` and the old
 * bundle, forever: the unregistration code in `main.tsx` never executes, because the code that
 * runs is the cached code that predates it. Removing the file cannot fix that, because nothing
 * would be left to notice.
 *
 * What does work is the browser's own update check. On navigation it re-fetches this URL, byte-
 * compares it with the installed worker, and installs it if it differs. This script is that
 * difference. It claims every open client, deletes the caches Workbox left, and unregisters
 * itself — after which the next load comes from the network like an ordinary page.
 *
 * It can be deleted once no browser that installed the old worker will ever be opened again,
 * which is not a date anyone can name. It costs a few hundred bytes.
 */
self.addEventListener('install', () => {
  // Replace the old worker immediately rather than waiting for every tab to close.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Drop every cache this origin holds. These are Workbox's precache and runtime caches; the
      // downloaded-track store is IndexedDB (Dexie) and is a different storage API entirely, so
      // nothing a person downloaded is touched here.
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));

      // Take control of open tabs so they stop being served by the previous worker...
      await self.clients.claim();

      // ...then remove this registration, so the next navigation is a plain network fetch.
      await self.registration.unregister();

      // Reload open clients once, so a tab left open on the stale bundle picks up the real one
      // instead of sitting there until someone refreshes it by hand.
      const clients = await self.clients.matchAll({ type: 'window' });
      for (const client of clients) {
        client.navigate(client.url);
      }
    })(),
  );
});

// No fetch handler on purpose: with none registered, the browser goes straight to the network.
