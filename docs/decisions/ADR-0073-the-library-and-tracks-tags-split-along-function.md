# ADR-0073: The Library and Tracks Tags Split Along Function

Status: proposed

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md) by applying its rule to the
two tags that most need it. Resolves the split
[ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) point 2 deferred.

## Context

Two tags hold a quarter of the API between them and describe nothing: `library` has 34 operations
and `tracks` has 28. Both are named after a resource, which under `ADR-0072` is a path's job, so
neither says what its operations are *for*.

**`ADR-0007` point 2 recorded the cost knowingly** rather than missing it:

> *"`library` stays whole even though it mixes roughly 18 listening operations with 17 management
> ones. Tags cannot express that split, and the cost of the extra 17 is dead generated code rather
> than a defect."*

`ADR-0014`'s Alternatives left the door open — splitting `library` was *"worth doing on its own if
those seventeen ever do resist typing."* They have not resisted typing; what has changed is that the
listening/management line is now the line the whole product is organised on, so the tag that
straddles it is the one obstructing the map.

The estimate was almost exact. The real split is **17 and 17**:

| → | ops | |
|---|---|---|
| `library` | 9 | albums, albums/{artist}/{album}, artists, artists/{name}, artists/{name}/image, letter-index, mood-distribution, stats, years |
| `map` | 5 | map, map/3d, map/3d/stream, map/ego, map/stream |
| `discover` | 3 | discover, discover/external-albums, artists/new-releases |
| `ingest` | 11 | sync ×3, import ×3, missing ×5 |
| `analysis` | 5 | analysis/{start,cancel,status,executor,executor/reset} |
| `duplicates` | 1 | deduplicate/preview |

`tracks` divides the same way — a stream, a play event and a metadata patch are three different
activities against one resource:

| → | ops | |
|---|---|---|
| `tracks` | 11 | list, ids, batch, detail, stream, artwork ×3, index, album-gain, lyrics |
| `plays` | 6 | started, played, skipped, rejected, report-playback-error, stats/plays |
| `metadata` | 5 | metadata GET/PATCH, bulk/metadata, bulk/common-values, lookup/metadata |
| `identification` | 3 | identify, bulk/identify ×2 |
| `discover` | 2 | discover, similar |
| `visualizers` | 1 | visualizer-ranking |

**The cost is compile-time only, and smaller than it looks.** Under `ADR-0072` this is a tag change,
so operation ids change and Swift method names with them, but **no path moves**. The generated client
calls exactly nine `library*` methods — `libraryListArtists`, `libraryGetArtistDetail`,
`libraryListAlbums`, `libraryGetAlbumDetail`, `libraryGetMusicMap`, `libraryGetDiscoverDashboard`,
`libraryStartSync`, `libraryCancelSync`, `libraryGetSyncStatusEndpoint` — and every one lands in
`library`, `map`, `discover` or `ingest`, all of which stay in the generated surface. **Nothing in
Swift calls the analysis or deduplicate operations.**

## Decision

1. **`library` becomes six tags** — `library`, `map`, `discover`, `ingest`, `analysis`,
   `duplicates` — split 17 listening / 17 management as above.

2. **`tracks` becomes six tags** — `tracks`, `plays`, `metadata`, `identification`, `discover`,
   `visualizers`.

3. **No path moves.** `/library/sync` stays at `/library/sync` under the `ingest` tag;
   `/tracks/{id}/played` stays where it is under `plays`. `ADR-0072` point 4 governs, and neither
   path misnames its resource.

4. **`analysis`, `duplicates` and `identification` leave the generated surface**, and `map`,
   `discover`, `ingest`, `plays`, `metadata` and `visualizers` join it. The net effect on
   `filter.tags` is stated explicitly in the change rather than inferred, and `VENDORED_TAGS` moves
   with it in the same commit — `ADR-0014` point 4.

5. **The five `library/analysis/*` operations join the existing `analysis` tag** rather than forming
   a new one. They are the same activity as the eight already tagged `analysis`, run over the library
   rather than one track, and two tags for one activity is what this ADR exists to stop.

6. **`deduplicate` stops being a second tag on a `library` operation.** It becomes `duplicates`,
   singular and sole, under `ADR-0072` point 2.

## Alternatives Considered

**Leave both whole and keep paying dead generated code.** What `ADR-0007` point 2 chose, for a good
reason that has expired: tags could not express the split *then* because nobody had decided where
the line was. The line is now the organising principle of the product.

**Split by path prefix instead — put management operations under `/admin/…`.** This would express the
split in the axis that is visible in a URL. Rejected under `ADR-0072` point 4: `/library/sync` is
honestly named, it syncs the library, and moving it would reach installed clients for a change that a
tag makes for free.

**Split `library` but leave `tracks` alone.** Genuinely tempting, since `tracks` is less egregious —
28 operations that really are all about tracks. Rejected because it would leave `plays` buried, and
`plays` is the tag that makes `tracks/playback.py` distinguishable from the `playback` tag that is
not playback (`ADR-0075`). Both splits also land in one regeneration, so separating them doubles the
coordination for no benefit.

**Give `visualizer-ranking` no tag of its own** and leave it in `tracks`. Rejected, but narrowly —
`ADR-0072` point 7 calls a one-operation tag a smell. The reason it earns one: it is the only
operation the embedded visualizer surface calls on its own behalf, and `ADR-0064` will add to it.

## Consequences

- **Positive** — the API's index becomes readable. Twelve tags of 1–11 operations each, named for
  activities, replace two of 34 and 28 named for resources.
- **Positive** — `ADR-0007` point 2's accepted defect is retired rather than inherited, and the
  generated Swift surface stops carrying analysis and deduplicate operations nothing calls.
- **Positive** — the `library`/`library` duplication disappears as a side effect, since point 2 of
  `ADR-0072` forbids the aggregator setting a tag at all.
- **Tradeoff** — every generated Swift method whose name begins `library` or `tracks` is renamed.
  That is a compile error in `familiar-apple` for each of the nine `library*` call sites plus the
  `tracks*` ones, in a separate repository and a separate pull request.
- **Tradeoff** — `filter.tags` grows from eleven entries to more, which makes the generated surface
  look larger even though the operation count falls. The count, not the tag list, is what to compare.
- **Follow-up** — the split must land in one commit per repository with the schema re-vendored
  between them (`ADR-0078`), or the two sides briefly disagree about what a method is called.
