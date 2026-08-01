# ADR-0014: The Generated Surface Widens to Management

Status: accepted

Date: 2026-08-01

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md).
Depends on [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

Implementation:
- Accepted and executed 2026-08-01. Eleven tags; **33 operations** added to the generated client.
  `Proposed Changes` renamed to `proposed-changes` first, before anything generated from it.
- Point 6 earned its place immediately. The lint refused the widened surface over
  `PendingTrackResponse.review_info`, a bare `dict[str, Any]` that would have generated as `Any`.
  It was typed rather than allowlisted, as that point requires — `ReviewInfo` and `TrackQuality` in
  `backend/app/api/routes/pending_review.py`, every field optional because the values are read back
  out of a JSONB column older than the model and a row written by an earlier scanner must still
  deserialise. `reviewInfo` now generates as `Components.Schemas.ReviewInfo`.
- Backend: 64 tests over the three tags pass. Swift: 378 tests, both targets building.

## Context

[ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) point 2 defines the generated Swift
surface as eight tags — `tracks`, `library`, `playlists`, `smart-playlists`, `profiles`, `favorites`,
`chat` and `queue` — enforced from both ends: the filter in
`Sources/FamiliarAPI/openapi-generator-config.yaml` and the backend lint in
`backend/scripts/lint_openapi.py`, so the two cannot drift silently.

[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) puts pending review, proposed changes and
mixtapes on the Mac. None of those three is reachable from Swift today, so that ADR cannot be
executed without changing this one. Measured against the current schema:

| tag | endpoints | generated today |
|---|---|---|
| `pending-review` | 16 | no |
| `Proposed Changes` | 12 | no |
| `mixtapes` | 5 | no — and listed in `NOT_GENERATED` |
| `smart-playlists` | 10 | **yes** |

Two details matter more than the counts.

**`mixtapes` is excluded on purpose, with a recorded reason.** `NOT_GENERATED` at
`backend/scripts/lint_openapi.py:56` is `{"ambient", "mixtapes", "outputs"}`, and the comment above it
cites ADR-0001 point 5 for mixtapes. That justification is exactly what ADR-0013 revisits, so removing
it from that set is a change of decision rather than a tidy-up, and the comment must be updated to say
so rather than quietly losing an entry.

**`Proposed Changes` is the only tag with a space and capital letters.** Every other tag in the schema
is lower-case kebab-case. The generator derives Swift names from operationIds rather than tags, so
this is not fatal, but it is the sort of inconsistency that produces one oddly-named thing nobody
later understands — and it is far cheaper to fix before anything generates from it than after.

The `library` tag is already instructive here. `lint_openapi.py` notes that it "stays whole despite
mixing ~18 listening operations with ~17 management ones (import, dedup, scan, review)", accepting
"dead generated code rather than a defect", and closes with *"Revisit if they resist typing."* Under
ADR-0013 those seventeen stop being dead: they are part of what the review surfaces need.

## Decision

1. **Generate three more tags: `pending-review`, `proposed-changes` and `mixtapes`.** The filter in
   `Sources/FamiliarAPI/openapi-generator-config.yaml` goes from eight tags to eleven.

2. **Rename the backend tag `Proposed Changes` to `proposed-changes` first**, in its route module, so
   the schema is regenerated with it before any Swift is generated from it. Kebab-case matches every
   other tag; doing it first means no generated name is ever built on the old spelling.

3. **`mixtapes` leaves `NOT_GENERATED`; `ambient` and `outputs` stay**, with their existing reasons
   intact — ambient is out of v1 and iOS-only in nature, casting is outside ADR-0001 point 4's scope.
   The comment gains a line recording that mixtapes left because ADR-0013 brought it into scope, so
   the set continues to explain itself.

4. **The lint keeps enforcing both ends.** `NOT_GENERATED` and the generator filter are updated in the
   same change, and the lint's own expectations move with them. A widened surface that only one side
   knows about is the drift ADR-0007 exists to prevent.

5. **Nothing else is added.** In particular `s3-backup`, `export-import`, `spotify`, `analysis`,
   `settings` and `admin` stay out: ADR-0013 point 4 keeps them web-only, so generating them would
   produce exactly the dead code the `library` note tolerates only because tag granularity gives no
   choice.

6. **No new exceptions to ADR-0007's rules.** If any of the three carries an operationId over 60
   characters, an undeclared error response, or a non-JSON media type declared as JSON, the backend is
   corrected rather than the lint relaxed. This is the moment those endpoints are first held to the
   contract, and some of them predate it.

## Alternatives Considered

**Hand-write Swift clients for the three tags.** Avoids touching the generated surface at all, and for
33 endpoints it is not unthinkable. Rejected because it reintroduces precisely what ADR-0007 removed:
a hand-maintained contract that drifts silently, where a renamed response field becomes a runtime
failure on a device instead of a compile error.

**Generate every tag and stop filtering.** Simplest rule, no list to maintain, no drift possible.
Rejected because the filter is doing real work — `ambient` and `outputs` are out of scope by
decision, not by accident, and the recorded reasons in `NOT_GENERATED` are more valuable than the
convenience. It would also generate S3 backup and Spotify import, which ADR-0013 point 4 explicitly
keeps web-only.

**Split the `library` tag into listening and management halves.** Tempting while nearby, and it would
turn the "~18 listening, ~17 management" note into a real boundary. Rejected as a separate concern
that would balloon this change: it touches every `library` route's decorator and every generated call
site in the Swift app, for no benefit to the three features ADR-0013 wants. Worth doing on its own if
those seventeen ever do resist typing.

**Leave `Proposed Changes` spelled as it is.** It works; the generator keys names off operationIds.
Rejected because it costs one line to fix now and is awkward forever afterwards — and a schema where
one tag is shaped unlike all the others invites the next person to match the wrong pattern.

## Consequences

- **Positive:** Pending review, proposed changes and mixtapes become reachable from Swift with a
  compile-time-checked contract, on the same terms as everything else the app talks to.
- **Positive:** The schema's one inconsistent tag name is fixed while the cost is a rename.
- **Positive:** Seventeen `library` management operations that were generated as dead code start
  earning their place.
- **Tradeoff:** The generated client grows by 33 operations plus their types, lengthening build time
  and adding surface that only the Mac uses — the iOS target compiles it and never calls it.
- **Tradeoff:** Endpoints written before ADR-0007's rules now have to satisfy them, which may mean
  backend corrections that look unrelated to bringing a feature to the Mac.
- **Follow-up:** If the `library` tag's management half ever does resist typing, split it — the note
  in `lint_openapi.py` already anticipates this and should be updated to point here.
