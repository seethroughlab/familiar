# ADR-0077: A Surface With No Caller Is Deleted, Not Documented

Status: accepted

Date: 2026-08-18

Extends [ADR-0057](ADR-0057-the-web-app-keeps-only-what-has-no-native-answer.md), whose point 5 says
a capability and its affordances leave together. This says the same about an endpoint and its
clients, in the other direction.

Implementation:

- **Shipped 2026-08-28**, `familiar` on `adr-0077-delete-uncalled-surfaces` and `familiar-apple` on
  `adr-0077-drop-uncalled-surfaces`. **Fourteen operations left the schema, and no operation was
  added** — verified by diffing `backend/openapi.json` against its previous revision, not by
  counting the intended deletions.
- Points 2 and 3 took `routes/bandcamp.py`, `routes/ambient.py` and the nine zone endpoints.
  `services/bandcamp.py` and `services/ambient.py` were left untouched, as point 2 requires — their
  MCP and recommendation importers are what point 6 records as where the capability went.
- **Point 2's "judged separately" was applied to zones and came out the other way.** `Zone`, the
  manager's six zone methods and the `zones` dict were deleted from `services/outputs.py` too:
  unlike bandcamp and ambient, nothing reached them but the routes, so leaving the service would
  have left precisely the dead code point 1 objects to.
- The generated Swift client came back **byte-identical** ("File Client.swift already up to date"),
  which is the sharpest confirmation that all fourteen were outside the generated surface.
- Point 5's wrappers went with one correction the compiler caught: `ImportResultCategory` was
  declared beside the deleted export/import wrappers but used by the *kept* restore types, so it
  moved rather than went. `api/backup.ts` fell from 612 lines to 190, keeping only `backupApi`.
- Point 5 named `routes.ts:76` as a comment describing dead code. That comment, and two more in
  `Admin/LibraryPage.tsx` and `Admin/OrganizePage.tsx`, now record the deletion instead — the
  `pending-review` gap they document is still real, only the wrapper is gone.
- **Follow-on this surfaced, not acted on:** deleting `s3BackupApi` and `libraryExportApi` leaves
  `/s3-backup/*` and `/export-import/library/*` with no caller in either repository, and there is
  no S3 backup UI anywhere. By point 1 they are now deletion candidates in their own right. They
  are out of this ADR's scope, which named exactly what goes.

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

**`ambient` — three routes whose only caller has since been deleted.** This was written while
`api/ambient.ts` still existed, imported solely by
`packages/frontend/src/player/ambient/AmbientCoordinator.ts` and in the unreachable set
`docs/REMOVING-THE-WEB-PLAYER.md` measured. The player's removal took both, so **the three routes now
have no client anywhere in either repository** — no Swift caller either, the tag being outside the
generated surface. Again the service is not the route: `app/services/ambient` is imported by
`routes/queue.py:36`, `services/offline_manifest.py`, `services/playlist_generation.py`,
`services/collection_suggestions.py` and the MCP discovery handler, and by six test modules.
**The routes go; the service stays.**

**`outputs` zones — nine operations, one of them unreachable by construction.**
`routes/outputs.py:212` declares `GET /{output_id}` with `output_id: UUID` and
`routes/outputs.py:304` declares `GET /zones`; FastAPI matches in declaration order, so
`/outputs/zones` is parsed as an output id and returns 422. The generator config already documents
the nine as dead and unpersisted.

**A first draft of this ADR got the generator config backwards, and the correction changes what
point 3 can promise.** That draft said `filter.operations` *names the nine zone operations to keep
them out of Swift*. It does the opposite: the block names the nine `outputs` operations that are
**wanted**, and the zones are excluded by omission. The consequence is that deleting the zones does
not free `outputs` to become an ordinary `filter.tags` entry. Six of the remaining fifteen are
ungenerated for reasons of their own — `outputs_create_output` and `outputs_delete_output`, because
discovery auto-registers what it finds; `outputs_discover_sonos`, `_upnp` and `_chromecast`, because
`discover_all` covers them; and `outputs_discover_airplay`, because `ADR-0031` point 3 leaves AirPlay
to the OS route picker. The filter keys are a union, so naming the tag re-admits all six.

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
   reachable. **`outputs` does not thereby become a `filter.tags` entry**, for the reason recorded
   in `## Context`, and `filter.operations` keeps naming operations — it must, both for the six
   remaining `outputs` exclusions and for `ADR-0086`'s five `videos` operations. What the deletion
   buys is smaller and still worth having: the config stops having to explain nine operations that
   exist only to be excluded, and `GET /outputs/zones` stops being advertised.

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
- **Positive** — the generator config's longest comment shrinks to the six exclusions that remain
  real. It does not disappear, and `outputs` does not join the ordinary mechanism; anyone reading
  this expecting that should read point 3.
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
