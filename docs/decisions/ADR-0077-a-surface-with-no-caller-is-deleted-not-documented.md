# ADR-0077: A Surface With No Caller Is Deleted, Not Documented

Status: proposed

Date: 2026-08-18

Extends [ADR-0057](ADR-0057-the-web-app-keeps-only-what-has-no-native-answer.md), whose point 5 says
a capability and its affordances leave together. This says the same about an endpoint and its
clients, in the other direction.

## Context

The restructure publishes the API's shape — ordered tags, described groups, a readable index
(`ADR-0072` point 5). That makes every operation in the schema a claim about what the software does,
and a claim with no caller behind it is the most expensive kind of documentation: it looks
maintained, it is covered by contract tests, it appears in the generated client, and nobody has
exercised it in months.

Four such surfaces were found while scoping. **The distinction that matters in every case is between
a route and the capability underneath it** — deleting an unused HTTP entry point is not the same as
deleting a feature, and conflating the two is how a cleanup breaks something.

**`bandcamp` — two routes, no callers; the service is load-bearing.** `GET /bandcamp/search` and
`GET /bandcamp/album` are called by nothing in `packages/`, nothing in `familiar-apple`, and nothing
in the backend. But `app/services/bandcamp.py` is imported by `services/recommendations.py:23` and
twice by `services/llm/handlers/discovery.py`, which is the MCP tool surface — so the capability is
alive and reached a different way. `backend/tests/test_bandcamp.py` tests the service, and its
docstring records a real defect it caught: `search_bandcamp` *"answered 'no results' for every query,
for however long it had been"*. **The routes go; the service stays.**

**`ambient` — three routes whose only caller is being deleted.** `api/ambient.ts` is imported solely
by `packages/frontend/src/player/ambient/AmbientCoordinator.ts`, and `player/ambient/` is in the
unreachable set `docs/REMOVING-THE-WEB-PLAYER.md` measured — nothing in `/embed` or `/visualizer`
reaches it. No Swift caller; the tag is excluded from the generated surface. Again the service is
not the route: `app/services/ambient.get_candidates` is imported by `routes/queue.py:36`,
`services/offline_manifest.py`, `services/playlist_generation.py` and the MCP discovery handler.
**The routes go; the service stays.**

**`outputs` zones — nine operations, one of them unreachable by construction.**
`routes/outputs.py:212` declares `GET /{output_id}` and `routes/outputs.py:304` declares
`GET /zones`; FastAPI matches in declaration order, so `/outputs/zones` is parsed as an output id and
returns 422. The generator config already documents the nine as dead and unpersisted, and names them
operation-by-operation in `filter.operations` to keep them out of Swift — a twenty-line block that
exists solely to exclude them.

**Four `queue` operations with no caller.** `queue_put_playback_session`,
`queue_list_archived_sessions`, `queue_restore_archived_session` and `queue_offline_manifest` are
called by neither the generated Swift client nor, once the player is removed, anything in this
repository. Unlike the three above, these have a plausible near-future consumer, which is why they
are treated differently below.

## Decision

1. **An operation with no caller is deleted, not documented.** Not deprecated, not left untagged, not
   moved to a section for things that might be useful. The schema describes what the software does.

2. **The route goes; the service is judged separately.** `bandcamp` and `ambient` both keep their
   service modules, because both are reached through the MCP tool surface and the recommendation
   path. Only `routes/bandcamp.py` (2 operations) and `routes/ambient.py` (3) are removed.

3. **The nine `outputs` zone operations are deleted**, including the one that has never been
   reachable. `outputs` then becomes an ordinary `filter.tags` entry and the twenty-line
   `filter.operations` block collapses to a single line — the largest single legibility gain in the
   generator config.

4. **The four uncalled `queue` operations are kept, and the reason is recorded.** They are the server
   half of `ADR-0003`'s server-owned queue and `ADR-0006`'s precomputed offline ranking, both of which
   the Apple clients are expected to consume. Deleting a server half that a client is scheduled to
   adopt is how `ADR-0036` wasted its work; deleting one that no client will ever adopt is this ADR.
   **The distinction is whether a decision exists that says the caller is coming.** For these four it
   does.

5. **Frontend wrappers with no importer go with the same rule.** `api/mapStream.ts`,
   `api/missingTracks.ts`, `api/pendingTracks.ts`, `api/importSession.ts`, and the `s3BackupApi`,
   `exportImportApi` and `libraryExportApi` exports in `api/backup.ts` have no consumer outside
   `api/`. `routes.ts:76` already records `pendingTracks` as "a wrapper nothing calls" — a comment
   describing dead code rather than deleting it.

6. **A deletion states where the capability went, if it went anywhere.** `bandcamp` search is
   reachable through MCP; ambient candidates are reachable through radio and playlist generation.
   Recording that is what makes this ADR different from a sweep, and what stops the next person
   restoring the routes because they think the feature was lost.

## Alternatives Considered

**Keep them; they are harmless and might be wanted.** The status quo, and the reason there are four
of them. Rejected because they are not harmless once the API is published as an index: each is a
claim about the product, each is generated or excluded by hand, and the `outputs` case shows the
compound cost — nine dead operations produced a twenty-line exclusion block that every reader of the
generator config now has to understand.

**Deprecate rather than delete**, marking them in the schema. Rejected for the reason
`ADR-0079` rejects visible deprecation: the schema's two audiences are a code generator and a person
orienting themselves, and a deprecated operation serves neither.

**Delete the bandcamp and ambient services too, since their routes are dead.** This is the mistake
the ADR exists to prevent, and it was nearly made here — the first pass at this restructure recorded
bandcamp as having *"the only reference anywhere"* in a single test row. It has four importers, two
of them on the MCP path.

**Delete the four `queue` operations as well, for consistency.** Rejected under point 4. Consistency
is not the goal; not shipping dead surfaces is, and a surface with a decided future consumer is not
dead. `ADR-0074` should nonetheless sequence after this one, so that the aliases it creates are not
built for operations about to be removed.

## Consequences

- **Positive** — fourteen operations leave the schema (2 bandcamp, 3 ambient, 9 outputs zones), and
  with `ADR-0070`'s two, sixteen.
- **Positive** — the generator config's hardest-to-read section disappears, and `outputs` joins the
  ordinary mechanism.
- **Positive** — an endpoint that has never worked, `GET /outputs/zones`, stops being listed as
  though it does.
- **Tradeoff** — a self-hoster who scripted `/bandcamp/search` or `/ambient/seed` loses it with no
  deprecation window. These are unschemad-alias candidates under `ADR-0079` if that risk is judged
  real; the ADR's position is that it is not, because neither has ever been documented outside the
  schema.
- **Tradeoff** — point 4 is a judgement call that will be wrong if the Apple clients never adopt the
  server-owned queue. The four operations should be revisited if `ADR-0003` has still not been
  consumed a year from now.
- **Follow-up** — the rule in point 1 wants enforcement, not just intent. A periodic check that every
  schema operation has a caller in one of the known consumers is possible for the generated surface
  and hard for the rest; worth attempting for the generated half, where `filter.tags` already
  enumerates what should be called.
