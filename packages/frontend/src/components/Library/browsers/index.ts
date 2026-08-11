/**
 * Browser registrations.
 *
 * Import this file to register all library browsers.
 * Each browser is registered with the browserRegistry.
 */

// Import and register browsers
import './TrackListBrowser';
import './ArtistCleanupBrowser';
// **Registered but not routed.** `EmbedDiscover` renders this inside the WKWebView both Apple
// clients use for Discover (ADR-0016/0017/0019), so it outlives the app route that was unmounted
// with the rest of the listening path. `PARKED_BROWSERS` records it, and
// `navigationIntegrity.test.ts` is what stops that becoming an accident.
import './DiscoverBrowser';

// Artists, Albums, Music Map, Proposed Changes, Pending Review and New Releases were deleted with
// ADR-0050: the Mac covers all six, and the web app is a management surface now. `docs/WEB-PARITY.md`
// is the record of what they did, which is the whole reason it exists.
