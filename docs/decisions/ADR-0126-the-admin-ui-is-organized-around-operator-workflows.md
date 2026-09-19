# ADR-0126: The Admin UI Is Organized Around Operator Workflows

Status: accepted

Date: 2026-09-17

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md),
[ADR-0080](ADR-0080-the-web-app-is-navigated-from-a-top-bar.md) and
[ADR-0081](ADR-0081-the-admin-app-has-one-component-tree.md). Those records correctly removed the player
and reduced the application to administration; this record revisits the information architecture after
the remaining administration surface grew.

Implementation:
- **2026-09-19, `familiar` — built.** By point:
  1. `DESTINATIONS` in `packages/frontend/src/app/routes.ts` is Overview, Library, Analysis, Server;
     `TopBar.tsx` renders four at `w-[4.5rem]` on a phone, checked at 390px.
  2. `panels/server/ProviderCards.tsx` is one card per provider — health (the old `DiscoverySources`
     rules and tests, moved), the key with its environment variable named, and the provider's own
     management panel inside the card. `ApiKeyStatus` and `DiscoverySources` are gone.
     `DataManagement`'s heading is "Transfer" and it sits under Server → People; Server → Backup is
     the S3 installation backup alone.
  3. `screens/overview/attention.ts` derives the three answers, pure and tested against the NAS's
     recorded shapes and a synthetic failing server; `OverviewPage.tsx` renders them, the attention
     list, the Sync action, then the totals. Every item's `to` is checked against `App.tsx` by
     test. Loading is distinguished from failure — the first cut said "Could not read the server"
     for the half-second before the first answer, which the demo-server screenshot caught.
  4. Library: Sync, Duplicates, Artists, Artwork, Organiser. No Review.
  5. Analysis: `screens/analysis/StatusSection.tsx` (phase queues from `health/workers`, the worker,
     failures, a link to Library → Sync) and `ConfigurationSection.tsx` (CLAP, community cache with
     its own health line, AcoustID naming, a link to the provider card).
  6. Server: Health (`SystemStatus` plus the library path, read-only, `MUSIC_LIBRARY_PATH` named),
     Jobs, Providers, Backup, People, Access, Diagnostics — `screens/server/sections.tsx`.
  7. `screens/SectionLayout.tsx`: the rail is a column on a desktop and a scrolling row on a phone,
     over one `SECTIONS` registry.
  8. `isUnder()` in `routes.ts` is the one ancestor rule, used by the bar and the rails;
     `navigationIntegrity.test.ts` now checks every rail section and every redirect target.
  9. On a phone the three tiles and the Sync button sit above the 844px fold; the first total starts
     at it.
  10. "Tools" and "Settings" are gone. Environment-only values (keys, the library path) say so and
      name the variable.
  Also: `healthApi`/`backgroundApi` moved to the generated client (`api/system.ts`) under ADR-0129,
  because the hand-written `WorkerStatus` had no `phase_queues`; `docs/CONFIGURATION.md:32` no
  longer claims the panel sets paths and keys; README screenshots regenerated against the demo.
  **Still open from the follow-ups:** a pending-review screen; a persisted duplicates count (the
  Overview shows no duplicates item); `analysis_progress` is untyped in the schema and narrowed
  by hand in `StatusSection.tsx`; `health/system` and `library/stats` still disagree on pending.

## Context

The top bar has three destinations: Library, Tools and Server (`packages/frontend/src/app/routes.ts:42-44`).
The grouping follows where code or data is owned — something acts on the library, runs against it, or
configures the server. An operator arrives with a different question: what needs attention, how do I
repair the collection, where is analysis stuck, and where do I change a setting.

**An earlier draft of this record answered that with Overview, Library and Settings, grouped from the three
pages' section headings.** A panel-level audit contradicted it. The web app has fifteen panels and five
tool screens; listed by what each reads and writes rather than by the heading it sits under, five of the
draft's groups cut across the units an operator actually reasons about. That audit is the evidence for
this record, so it is recorded here.

| Panel | What it is | Reads / writes | Today |
|---|---|---|---|
| `Dashboard` | Collection totals, artwork coverage, listening | `library/stats`, `artwork/coverage`, `tracks/stats/plays` | Library |
| `LibrarySync` | Start, watch, cancel a sync | `library/sync`, `library/sync/status` | Library › Scan |
| `AnalysisSettings` | CLAP embeddings on/off | `clap_embeddings_enabled` | Library › Scan |
| `DuplicatesPage` | Preview duplicate groups | `POST library/deduplicate/preview` | Tools |
| `ArtworkPage` | Albums with generated or missing art | `artwork/coverage`, refetch | Tools |
| `OrganizePage` | File-layout preview, never applied | `organizer/*` | Tools |
| `ArtistsPage` | Merge artists the scanner split | `admin/artists/*` | Tools |
| `DataManagement` | Export/import play history, favourites, playlists | `export-import/backup`, `restore/*` | Tools › Data |
| `CommunityCache` | Use / contribute to the community cache; name recordings via AcoustID | `community_cache_*` | Tools › Data |
| `SystemStatus` | Service health, phase queues, update channel, diagnostics export | `health/system`, `health/workers`, `update_channel` | Server › Health |
| `DiscoverySources` | Whether each provider is working | `health/discovery-sources` | Server › Discovery |
| `BackgroundJobs` | `library_sync` and `artwork_fetch` jobs in flight | `background/jobs` | Server › Discovery |
| `BackupSettings` / `BackupRestore` | S3 whole-installation backup: pg_dump, settings, audio | `s3_backup_*`, `s3-backup/*` | Server › Backup |
| `ApiKeyStatus` | Whether AcoustID and Last.fm keys are set — read-only | `*_configured` | Server › Access |
| `ServerTokenSettings` | The token this client presents | local storage | Server › Access |
| `ProfileSettings` | Name and avatar | `profiles/*` | Server › Profiles |
| `LastfmSettings` | Connect / disconnect Last.fm | `lastfm/*` | Server › Integrations |
| `SoulseekSettings` | slskd URL and key | `soulseek_url`, `soulseek_api_key` | Server › Integrations |
| `DebugSettings` / `RemoteLogsPanel` | Console capture, remote logs | `frontend-logs/*` | Server › Diagnostics |

The five splits, against the earlier draft's groups:

1. **A provider was four panels in three groups.** Last.fm's key status (`ApiKeyStatus`), its connection
   (`LastfmSettings`), whether it works (`DiscoverySources`) and its nightly run (`BackgroundJobs`) went to
   "People and access", "Integrations" and "System". `DiscoverySources.tsx`'s header records why the
   configured and working questions must both be visible — the nightly job crashed nineteen nights running
   while the key looked fine — and the draft moved them further apart.
2. **The analysis pipeline was split four ways.** The CLAP toggle went to Library, the community-cache and
   AcoustID toggles were named in the draft's context and placed nowhere, the phase queues and backlog went
   to Settings › System, and the sync that triggers re-analysis went back to Library.
3. **"Backup" is two unrelated things.** `BackupSettings`/`BackupRestore` is the S3 installation backup;
   `DataManagement` exports a profile's play history, favourites and playlists for moving between servers
   (`export_import/backup.py:36-39`). Both are titled "Backup & Restore". The draft sent one to
   "Protection" and the other, the same component, to "Files and data".
4. **Two things it placed do not exist.** Pending review has no web component (`routes.ts:54`,
   `UNBUILT_DESTINATION_ITEMS`) and `/library/proposed-changes` is not mounted. Library paths are not
   editable in the web app at all: nothing writes `music_library_paths`, the settings response pops it
   (`backend/app/api/routes/settings.py:185`), and they come from `MUSIC_LIBRARY_PATH`. API keys are the
   same — `ApiKeyStatus` is read-only and keys are environment variables. `docs/CONFIGURATION.md:32` says
   both are in the Settings panel; it is wrong, and so was the draft's "Settings owns configuration".
5. **The server token's own comment disagreed.** `ServerTokenSettings.tsx` explains that it sits beside the
   server URL "because the two fail together: a wrong token and a wrong URL both look like 'nothing
   loads'". The draft filed it under "People and access".

The narrow-screen defects stand as first found: three collection totals become three full-width cards
before the first action, and on tool child routes the top-level destination is not marked active because
selection is exact path equality (`packages/frontend/src/app/TopBar.tsx:47`); only Library has an ancestor
rule, hand-written for `/library/`.

Two facts found while building the review mock also belong here. `GET /health/system` reports 52 tracks
pending analysis while `GET /library/stats` reports 0 for the same library — two endpoints answer "is
analysis done" differently, and an overview has to pick one. And the duplicates count comes from a `POST`
preview that takes about 40 s against 26,000 tracks, which no landing page can call on load.

## Decision

1. **The persistent destinations are Overview, Library, Analysis and Server.** Four, not three: analysis
   is the product's core and was the most fragmented unit, and its status is about the server's work
   rather than the collection's contents. Four short labels fit ADR-0080's one bar at 390px; the review
   mock shows them. "Tools" leaves because it named where code lived; "Settings" is not adopted because
   the two settings an operator most wants — library paths and API keys — are environment-only and the
   label would promise them.

2. **A unit is shown whole, in one place.** A provider is one card: credential state, connection, health
   and last run. The analysis pipeline is one destination: configuration, phase queues, backlog and the
   running job. An installation backup and a profile transfer are two different things with two names.
   Status may be *summarised* on Overview, but it is *detailed* once, and the same panel is not rendered in
   two destinations.

3. **Overview answers three questions in its first viewport:** is the system healthy, is anything
   running, and what needs attention. Collection totals and listening history are secondary and sit
   below. Every attention item links to a mounted screen; an item whose owning screen does not exist is
   not shown. Counts that cost a scan (duplicates) come from a cached or persisted figure, never from
   running the scan on load. Analysis backlog is read from the worker phase queues, the source that
   distinguishes phases.

4. **Library owns the collection's contents.** Local sections: Sync (`LibrarySync`), Duplicates, Artists,
   Artwork, Organiser. Review joins when a web screen for pending tracks and proposed changes exists;
   until then it is not a section and not a link.

5. **Analysis owns the pipeline.** Local sections: Status (phase queues, backlog, the running analysis or
   sync job, stall recoveries) and Configuration (CLAP on/off, use and contribute to the community cache,
   name recordings through AcoustID). Configuration links to the AcoustID provider card on Server; it does
   not repeat it.

6. **Server owns the installation.** Local sections:
   - Health: service states, version, update channel, library paths shown read-only with the environment
     variable named.
   - Jobs: everything `background/jobs` reports.
   - Providers: one card each for Last.fm, MusicBrainz, AcoustID, ListenBrainz, Bandcamp and Soulseek —
     key or URL state, connect where the provider has a flow, health from `health/discovery-sources`,
     last success and failure. Keys that are environment-only say so on the card.
   - Backup: S3 installation backup and restore, and nothing else under that word.
   - People: profiles, and the profile transfer (`DataManagement`, renamed to say what it moves).
   - Access: server URL and token together, as the panel's own comment argues.
   - Diagnostics: logs, console capture, diagnostics export.

7. **Desktop pages have persistent local navigation.** Every section has a route of its own and can be
   linked, reloaded and reached with browser history. Mobile uses a compact section selector over the same
   routes, not a second destination registry.

8. **Ancestor matching drives navigation state.** `/library/duplicates` selects Library and
   `/server/providers/lastfm` selects Server. Navigation integrity tests cover every routed section and
   child-page selection.

9. **Frequent actions precede descriptive metrics on narrow screens.** Compact totals share one row; the
   running state and the primary action are visible without scrolling through one card per number.

10. **Labels describe outcomes and say when a thing is not editable here.** Technical names such as CLAP,
    Redis and MCP may appear inside Analysis, Health or Diagnostics, never as the only explanation of a
    task. A value that comes from the environment is shown with its variable name rather than as a form
    that cannot save.

## Alternatives Considered

**Overview, Library and Settings — the earlier draft.** Rejected by the panel-level audit above: it split
providers, the analysis pipeline and backup across groups, placed two screens that do not exist, and
promised settings the web app cannot set.

**Keep the three destinations and add headings or accordions.** Smaller, but rejected as the target
because Tools and Server remain catch-all labels with no stable rule for the next feature, and the splits
above are in the current pages too.

**Analysis as a section of Library.** Rejected. The pipeline's status is about queues, workers and the
running job — the server's work — and putting it under Library would recreate split 2 with a different
heading. It is also the destination an operator opens when something is stuck, which is why it earns a
top-level slot over, say, Providers.

**Providers as a fifth destination.** Rejected. Six cards, visited rarely, mostly to check health that
Overview already summarises. They belong under Server, whole.

**Add more top-level destinations.** Overview, Library, Analysis, Providers, People and System would make
every category explicit. Rejected because the administration surface is not used often enough to pay for
six permanent choices, and a six-item bar does not fit at 390px without a second navigation form.

**Return to a desktop sidebar.** Rejected for the top level under ADR-0080's reasoning. A local section
rail inside a destination is not the old application-wide media sidebar and is allowed by this record.

## Consequences

- **Positive:** a newcomer can predict where a new administrative feature belongs by naming its unit —
  a provider, the pipeline, the collection, the installation.
- **Positive:** the landing page prioritises exceptions and work over inventory, and links only to
  screens that exist.
- **Positive:** long Server and Tools pages become linkable, bounded sections.
- **Tradeoff:** a four-item bar is one more than ADR-0080's original three.
- **Tradeoff:** established URLs and screenshots change. Old router paths (`/tools/*`, `/server`) redirect
  to their successors for as long as bookmarks and README links might reach them. This is a router
  concern; ADR-0079's alias rule is about API paths in `compat.py` and does not apply here.
- **Tradeoff:** Overview queries several domains and must remain a summary rather than another
  implementation-heavy dashboard.
- **Follow-up:** a web screen for pending review and proposed changes, or a supersession of ADR-0058's
  claim that the web app has one. Until then Library has no Review section.
- **Follow-up:** either make library paths and API keys writable through `PUT /settings`, or correct
  `docs/CONFIGURATION.md:32` and CLAUDE.md's "Settings > Library Management" to say they are environment
  variables. This record assumes the latter until decided.
- **Follow-up:** a persisted duplicates count, so Overview can show it without a 40 s scan.
- **Follow-up:** reconcile `health/system`'s and `library/stats`'s pending-analysis figures, or document
  which one is authoritative.
- **Follow-up (done 2026-09-17):** this record was not accepted on the text alone. A mocked Overview was
  reviewed against two states — the NAS library, idle, with real figures, and a synthetic failing server —
  at 1280px and 390px, alongside mocked Analysis and Server / Providers pages built from the same data.
  The four labels and the first viewport were confirmed as drawn; the mock is the "Overview Mock" canvas
  in the operator's claude.ai artifacts.
