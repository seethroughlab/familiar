# ADR-0072: Paths Name Resources, Tags Name Functions

Status: proposed

Date: 2026-08-18

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), which made the schema a contract
and the tag the unit that defines the generated surface. This says what a tag and a path each mean,
so that the contract can be reorganized without guessing.

## Context

The API is 260 operations across 228 paths and 32 tags. Six independent defects were found while
scoping a restructure, and they have one cause: **prefixes and tags are both being used to express
the same thing**, so whichever is convenient gets used, and neither ends up reliable.

- **`Library Organization` is a tag with a space and capital letters** (`routes/organizer.py:20`),
  the only one in the schema. `ADR-0014` point 2 renamed `Proposed Changes` for exactly this reason —
  *"a schema where one tag is shaped unlike all the others invites the next person to match the wrong
  pattern"* — and asserted at line 48 that it was **"the only tag with a space and capital letters."**
  That was already false: `Library Organization` was introduced on 2025-12-26, seven months before
  `ADR-0014` was written. An audit looking for exactly this missed it, which is the argument for a
  rule rather than another sweep.

- **The tag is half of a public Swift method name, not a documentation label.**
  `custom_generate_unique_id` (`app/main.py:329-330`) builds the operationId as
  `{first_tag}_{route.name}`, lowercasing the tag and replacing spaces with hyphens. So the malformed
  tag produces `library-organization_preview_organization` — 41 characters, tied for the
  second-longest operationId in the API, with the word "organization" in it twice. The
  lowercase-and-hyphenate on line 329 is a workaround for a tag shaped unlike the others, sitting in
  the function that exists because `ADR-0007` needed ids short enough to be Swift methods.

- **32 operations carry `["library", "library"]`**, because `routes/library.py:24` sets the tag and
  each of its ten sub-routers sets it again; FastAPI concatenates rather than deduplicates. This is
  not cosmetic: it doubles the tag in every naive count, which is how the `library` tag came to be
  described as having 66 operations during this very restructure when it has **34**.

- **`routes/analysis.py` mounts under prefix `/tracks` and tags `analysis`** (`main.py:532`), so
  `/tracks/{id}/analysis` sits in a different functional area from every other `/tracks` route, while
  a *different* module, `library_analysis.py`, is tagged `library` under `/library/analysis/*`.

- **`routes/library_deduplicate.py` carries two tags**, `["library", "deduplicate"]` — the only
  two-tag operation in the schema, and therefore the only one whose generated name depends on which
  tag happens to be first.

- **`organizer.router` is registered at app level with prefix `/library/organize`** (`main.py:523`),
  while every other `/library/*` route nests under `library.router`. The URL namespace is shared;
  the router tree and the tag are not.

- **`health.router` is the only router registered without `DEFAULT_ERROR_RESPONSES`**
  (`main.py:511`, against `512-546`), so four operations document a different error contract from the
  other 256 — not by decision, but because it is first in a list of 36 near-identical lines.

**Why this matters more than tidiness.** The two axes have different costs, and conflating them
hides that. A **tag** is compile-time coupling: it renames a generated Swift method, which surfaces
as a build error in `familiar-apple` and is fixed by recompiling. A **path** is runtime coupling: it
is what an already-installed application calls, and the repositories version independently —
`familiar-apple/CHANGELOG.md` says so directly, *"A release here does not imply one there."*
Separating the axes is what makes a reorganization affordable, because almost all of the legibility a
newcomer perceives lives in the cheap one.

## Decision

1. **A path names a resource. A tag names a function.** A path answers "what is this a thing *of*";
   a tag answers "what area of the product does this belong to". Neither substitutes for the other,
   and a change to one is not justification for a change to the other.

2. **Exactly one tag per operation.** No aggregator sets a tag; the tag is set on the leaf router
   that owns the operation. This makes `["library", "library"]` and `["library", "deduplicate"]`
   unrepresentable rather than merely fixed.

3. **Tags are lowercase kebab-case**, matching the operationId they produce. `Library Organization`
   becomes `organizer`. The normalisation in `custom_generate_unique_id` stays as a safety net but
   should never again have anything to do.

4. **A path moves only when it misnames its resource** — not to match a tag, and not for symmetry.
   `/tracks/{id}/played` stays where it is when its tag becomes `plays`, because the event genuinely
   belongs to the track.

5. **The functional areas are published, not implied.** `openapi_tags` gives every tag an ordered
   position and a description, and `x-tagGroups` groups them; `/redoc` already renders both, and
   `main.py` sets neither today. A newcomer's first read of the API should be the list of areas.

6. **Routers are aggregated once.** `routes/__init__.py` exports a single `api_router` that
   `main.py` includes with one call, so a shared concern like `DEFAULT_ERROR_RESPONSES` is applied in
   one place and cannot be applied unevenly to 35 of 36 routers.

7. **A tag with one operation is a smell, not an error.** It usually means a path prefix was wanted.
   It is allowed, but it needs a reason in the ADR that introduces it.

## Alternatives Considered

**Fix the six defects individually and add no rule.** This is what `ADR-0014` point 2 did for
`Proposed Changes`, and the result is on the record: it fixed one tag, asserted the class was empty,
and left a tag of the same shape that had been there for seven months. Individual fixes do not
survive because nothing tells the next person which axis to use.

**Drop tags and organize by path alone.** Impossible without unpicking `ADR-0007` point 2: the
generated Swift surface is defined *by tag* in `filter.tags`, so tags are load-bearing regardless of
how the paths look. It would also lose the only mechanism that groups operations across resource
boundaries.

**Set `operation_id` by hand so the tag is free to be arbitrary.** This decouples the axes in the
other direction, and it has been tried here: `ADR-0007` line 66 records finding *"four hand-set
`operation_id`s that bypassed the naming convention"* as a defect during phase 2. Hand-set ids drift
from their routes, and the convention exists because 95-character generated names were unusable.

**Leave `library` whole and accept the dead generated code.** `ADR-0007` point 2 chose this
knowingly — *"the cost of the extra 17 is dead generated code rather than a defect"* — because tags
could not express the split at the time. The reason it is rejected now is that the split *is* the
line this restructure is drawing; `ADR-0014`'s Alternatives already left the door open, saying it was
*"worth doing on its own if those seventeen ever do resist typing."*

## Consequences

- **Positive** — every subsequent ADR in this set has a rule to cite instead of an opinion, and the
  question "should this be a path change or a tag change" has one answer.
- **Positive** — the cost of a proposed change becomes legible before it is made: tag work is free or
  compile-time, path work reaches installed applications.
- **Positive** — points 2 and 6 remove two whole classes of defect by construction rather than by
  vigilance.
- **Tradeoff** — the rule is not machine-checked by itself. Point 2 and point 3 can be linted;
  point 1 and point 4 are judgement, and a reviewer has to apply them.
- **Tradeoff** — one tag per operation gives up cross-cutting tags entirely. Nothing uses them today
  beyond the `deduplicate` accident, but a future operation genuinely belonging to two areas will
  have to pick one.
- **Follow-up** — `ADR-0014`'s statement at line 48 that `Proposed Changes` was the only malformed
  tag is contradicted by this ADR's Context. Per the convention its Decision is not edited; this
  record is where the correction lives.
- **Follow-up** — a lint asserting one lowercase kebab-case tag per operation, and that every tag
  appears in exactly one `x-tagGroups` entry with a non-empty description, belongs with the first
  phase that applies this.
