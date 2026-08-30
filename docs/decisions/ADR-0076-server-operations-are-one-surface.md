# ADR-0076: Server Operations Are One Surface

Status: accepted

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md) and
[ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), whose point 2 named *Server* as one of
the administration tool's three destinations. The API has no such grouping.

Implementation:

- **Shipped 2026-08-28** on `adr-0076-server-operations`, stacked on `ADR-0073`'s branch. Eight
  `tags=` edits and one index update — **nothing else**.
- **The narrowed claim was verified rather than asserted.** Diffing `backend/openapi.json` against
  its previous revision: **zero paths added, zero removed**, 249 operations unchanged, tags 37 → 34
  (eight removed, five added). No frontend file was touched, and the generated Swift client came
  back byte-identical — none of these tags is in `filter.tags`.
- Points 6 and 7 were **already done before this ADR was implemented**, both by `ADR-0072`. That is
  the interesting part of this one's history: `0072` reached `organizer` from its tag-shape rule and
  the aggregated router from its one-registration rule, arriving at two of `0076`'s conclusions from
  different premises. An ADR whose points get solved by a neighbour is a sign the neighbour found the
  more general rule.
- **The ADR's `## Context` and `## Consequences` disagreed with each other**, and the Consequences
  were right. Anyone drafting in this series should note the shape: the cost sentence was written
  early, the tradeoff list was written late and after more investigation, and nothing reconciled
  them.

## Context

`ADR-0058` gave the web app three destinations, one of which is Server — "health, diagnostics,
profiles, Last.fm, API keys, update channel". The API those screens call is scattered across tags
that were each added when their feature was, and never grouped:

| tag | ops | |
|---|---|---|
| `health` | 4 | `/health`, `/health/db`, `/health/system`, `/health/workers` |
| `diagnostics` | 5 | export, metrics, frontend-logs ×3 |
| `background` | 1 | `/background/jobs` |
| `updates` | 2 | `/updates`, `/updates/check` |

Four tags, twelve operations, one screen. `background` and `updates` are both single-purpose tags of
one and two operations — `ADR-0072` point 7 calls that a smell, and here it is the same smell three
times. Meanwhile `s3-backup` (13) and `export-import` (9) are two tags for what a user experiences as
one thing, backup and restore, and `download` (6) is named for an HTTP verb rather than for what it
produces.

**None of this is in the generated surface.** `ADR-0014` point 5 keeps `analysis`, `settings`,
`admin`, `s3-backup` and `export-import` deliberately out, and `health`, `diagnostics`, `background`,
`updates` and `download` were never in. So no Swift regenerates and no cross-repo coordination is
needed.

**The "class F, free, no alias" claim this ADR was drafted on was wrong, and the correction is why
the path moves are gone from the Decision below.** Free was true of the *tags* and false of the
*paths*:

- The paths this ADR proposed to move — `/health/*`, `/diagnostics/*`, `/background/jobs`,
  `/updates*` to `/system/…`, `/download/*` to `/exports/…`, `/admin/artists/*` to `/artists/…` —
  are **21 operations**, and the web app calls them from **18 sites across five files**
  (`api/admin.ts`, `api/diagnosticsLogs.ts`, `api/backup.ts`, `api/download.ts`,
  `stores/connectivityStore.ts`). Under `ADR-0058` that app is the only consumer these endpoints
  have, so "no client calls them" was never true of this group.
- The ADR contradicted itself: `## Consequences` already admitted `/download/*` and
  `/admin/artists/*` "need aliases", while `## Context` said no alias was needed at all. The
  Consequences were right, and they still understated it by omitting point 1's twelve operations —
  the largest move of the three.
- **`ADR-0079` is accepted but unbuilt.** Its point 5 requires a single module holding every
  compatibility route; there is none, and `include_in_schema=False` occurs once in the codebase, on
  an unrelated trailing-slash route in `tracks/listing.py`. The aliases these moves depend on have no
  mechanism yet, which this ADR never noticed it was assuming.

**And the largest path move contradicted the ADR it extends.** `ADR-0072` point 4: *"A path moves
only when it misnames its resource — not to match a tag, and not for symmetry."* `/health/db`,
`/diagnostics/metrics`, `/background/jobs` and `/updates` each name their resource honestly; the only
argument for moving them to `/system/…` was symmetry with the new tag. That is the case point 4
exists to refuse.

**One defect this ADR claimed has already been fixed elsewhere.** `health.router` was the only router
registered without `DEFAULT_ERROR_RESPONSES`. `ADR-0072` point 6 landed the aggregated router, so
`health` now documents the same envelope as every other operation and there is no list left to be
first in. `Library Organization` likewise became `organizer` under `ADR-0072` point 3. Points 6 and 7
below are therefore **already done**, and are kept only so the record reads correctly.

What remains true is the reason the ADR was written: `background` and `updates` are single-purpose
tags of one and two operations, `ADR-0072` point 7 calls that a smell, and `admin` is a tag on one
file whose three operations are artist merging — a name promising a namespace two-thirds of the API
would qualify for and only this one uses.

## Decision

0. **This ADR changes tags and moves no path.** Every point below is a `tags=` edit. That is what
   makes it free, and it is a narrowing of what was first drafted — see `## Context`. A path move
   here would need `ADR-0079`'s alias module, which does not exist, and would reach the web app at
   18 call sites.

1. **`health`, `diagnostics`, `background` and `updates` merge into one tag, `system`.** Twelve
   operations describing the state of the running server, in one place, matching the destination that
   consumes them. **Their paths do not move**: `/health/*`, `/diagnostics/*`, `/background/jobs` and
   `/updates*` each name their resource honestly, and `ADR-0072` point 4 forbids moving a path to
   match a tag.

2. **`GET /api/v1/health` stays registered at its current path forever**, unschemad, per
   `ADR-0079` point 7. Container probes and platform health checks are not clients, are not
   versioned, and must not be part of any coordinated anything. Under point 1 this costs nothing —
   the path was never going to move — but it is worth stating, because the reason it must never move
   is independent of this ADR.

3. **`s3-backup` and `export-import` become `backup` and `transfer`.** Backup and restore — including
   `export-import`'s backup/restore operations — are one tag; moving a profile or a library between
   servers is another. The line is durability versus portability, and it is the line a user is
   already on when they choose a screen.

4. **`download` becomes `exports`.** The tag named a transport; the operations produce ZIPs of
   playlists, track sets and analysis reports. **`/download/*` stays where it is** — whether that
   prefix misnames its resource is arguable in a way `/admin/` is not, and an arguable case does not
   clear `ADR-0072` point 4's bar.

5. **`admin` becomes `artists`, and so does the path.** Three artist-merge operations named for what
   they act on. The tag moved with this ADR; **the `/admin/` prefix followed once `ADR-0079`'s alias
   module existed** — see the Implementation note. It was the one deferral here that was a genuine
   loss: unlike the
   others, `/admin/` really does misname its resource — under `ADR-0058` most of this API is
   administration, so a prefix claiming the word is worse than no prefix. It clears point 4's bar and
   is deferred only because `ADR-0079`'s mechanism is unbuilt and nine web-app call sites depend on
   it. It is recorded as a follow-up rather than dropped.

6. **`Library Organization` becomes `organizer`** — **already done**, under `ADR-0072` point 3,
   which reached the same conclusion from the tag-shape rule rather than from this ADR's grouping
   argument. The router nesting this point also proposed is a path move and is dropped under point 0;
   `/library/organize` names its resource honestly.

7. **One aggregated router removes the error-response inconsistency by construction** — **already
   done**, under `ADR-0072` point 6. `routes/__init__.py` exports a single `api_router` that
   `main.py` includes once with `DEFAULT_ERROR_RESPONSES`, so `health` cannot be the exception
   because there is no longer a list to be first in. Recorded here because this ADR is where the
   defect was found; the fix arrived with the mechanism that made it impossible.

## Alternatives Considered

**Group by destination — `library`, `tools`, `server` tags matching `ADR-0058`'s three.** Superficially
attractive: the API index would mirror the admin app exactly. Rejected because it makes the server's
contract depend on one client's information architecture. The Apple clients and the MCP server call
this API too, and a tag called `tools` means nothing to either.

**Leave `health` separate from `system`.** The one real argument against point 1: `/health` is a
well-known convention, and monitoring tools look for it. Rejected as a false conflict — point 2
keeps the conventional path permanently, and what moves is the *tag*, which no probe reads.

**Keep `s3-backup` distinct because it is a specific integration.** Rejected because the distinction
that matters to a reader is what the operation achieves, not which storage backend it uses. If a
second backup target is added, `backup` absorbs it; `s3-backup` would have needed renaming anyway.

**Merge `background` into `system` but leave `updates` alone**, on the grounds that update-checking is
a product feature rather than server state. Genuinely arguable. Rejected because `/updates` reports
whether the server has a newer version available — that is a property of the running server, and it
is displayed on the same screen as the worker status.

## Consequences

- **Positive** — once narrowed to tags, the claim the ADR was drafted on becomes true: no
  regeneration, no coordination, no alias, no path change, nothing reaching an installed
  application, and not one line of frontend touched.
- **Positive** — eight tags become four, and three single-purpose tags stop being three.
- **Positive** — the `health` error-contract inconsistency and the `Library Organization` tag are
  both already fixed, by construction, through `ADR-0072`.
- **Tradeoff** — the tag and the path now disagree in five places: `/health/*` is tagged `system`,
  `/download/*` is tagged `exports`, `/admin/artists/*` is tagged `artists`. That is not a defect —
  `ADR-0072` point 1 says the two axes answer different questions — but it is the first time in this
  restructure that they visibly diverge, and a reader who expects them to match will be surprised.
- **Tradeoff** — merging four tags into `system` means a reader who knew where `/background/jobs` was
  has to look somewhere new. That is the point, but it is still a cost paid by the people most
  familiar with the codebase.
- **Follow-up, now done (2026-08-28)** — `/admin/artists/*` became `/artists/*` once `ADR-0074` built
  `ADR-0079`'s alias module. Three operations, three web-app call sites — not the nine this bullet
  estimated, which counted grep lines rather than distinct calls. `/artists` does not collide with
  `/library/artists`: that one browses, this one merges.
- **Follow-up** — **`ADR-0079` is accepted and unbuilt**, which this ADR discovered by depending on
  it. Every remaining path move in the restructure is blocked behind that module existing.
- **Follow-up** — after this lands, `docs/REST-API.md` describes an API that no longer exists in any
  of these areas. It is hand-written, unchecked, and covers 33 of 260 operations; reducing it to an
  orientation page that points at `/docs` belongs with this phase.
