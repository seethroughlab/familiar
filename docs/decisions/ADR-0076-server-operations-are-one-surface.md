# ADR-0076: Server Operations Are One Surface

Status: proposed

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md) and
[ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), whose point 2 named *Server* as one of
the administration tool's three destinations. The API has no such grouping.

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
`updates` and `download` were never in. Every change in this ADR is therefore **class F** — free,
landing in `familiar` alone, with no regeneration, no coordination and no alias. It is the largest
legibility gain available at the lowest cost in the whole restructure, which is why it goes first.

**Two defects get fixed on the way past.** `health.router` is the only router registered without
`DEFAULT_ERROR_RESPONSES` (`main.py:511` against `512-546`), so four operations document a different
error contract from the other 256 — not by decision but because it is first in a list of 36 lines.
And `admin` is a tag on exactly one file, `admin_artists.py`, whose three operations are artist
merging; the name promises a namespace that two-thirds of the API would qualify for and only this
one uses.

## Decision

1. **`health`, `diagnostics`, `background` and `updates` merge into one tag, `system`, at
   `/system/…`.** Twelve operations describing the state of the running server, in one place, matching
   the destination that consumes them.

2. **`GET /api/v1/health` stays registered at its current path forever**, unschemad, per
   `ADR-0079` point 7. Container probes and platform health checks are not clients, are not
   versioned, and must not be part of any coordinated anything.

3. **`s3-backup` and `export-import` become `backup` and `transfer`.** Backup and restore — including
   `export-import`'s backup/restore operations — are one tag; moving a profile or a library between
   servers is another. The line is durability versus portability, and it is the line a user is
   already on when they choose a screen.

4. **`download` becomes `exports`, at `/exports/…`.** The tag named a transport; the operations
   produce ZIPs of playlists, track sets and analysis reports. Paths move under `ADR-0079`, though
   the alias burden is small: no Swift calls them.

5. **`admin` becomes `artists`, at `/artists/…`.** Three artist-merge operations named for what they
   act on. The `/admin/` prefix is retired rather than reassigned — under `ADR-0058` most of this API
   is administration, so a prefix claiming the word is worse than no prefix.

6. **`Library Organization` becomes `organizer`, and the router nests where its paths already are.**
   `main.py:523` registers it at app level with prefix `/library/organize` while every other
   `/library/*` route nests under `library.router`. It becomes its own top-level prefix `/organize`,
   which is what it always was in everything but the URL.

7. **One aggregated router removes the error-response inconsistency by construction.** Per
   `ADR-0072` point 6, `routes/__init__.py` exports a single `api_router` and `main.py` includes it
   once with `DEFAULT_ERROR_RESPONSES`. `health` cannot be the exception because there is no longer a
   list to be first in.

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

- **Positive** — the largest reorganisation in the set costs nothing: no regeneration, no
  coordination, no alias, no risk to installed applications.
- **Positive** — 32 tags become materially fewer, and three single-purpose tags stop being three.
- **Positive** — the `health` error-contract inconsistency and the `Library Organization` tag are
  both fixed by construction rather than by remembering.
- **Tradeoff** — `/download/*` and `/admin/artists/*` paths move, so they need aliases, even though
  no known client calls them. The alias is cheap; assuming there is no client is not, since these
  are the endpoints a self-hoster is most likely to have scripted.
- **Tradeoff** — merging four tags into `system` means a reader who knew where `/background/jobs` was
  has to look somewhere new. That is the point, but it is still a cost paid by the people most
  familiar with the codebase.
- **Follow-up** — after this lands, `docs/REST-API.md` describes an API that no longer exists in any
  of these areas. It is hand-written, unchecked, and covers 33 of 260 operations; reducing it to an
  orientation page that points at `/docs` belongs with this phase.
