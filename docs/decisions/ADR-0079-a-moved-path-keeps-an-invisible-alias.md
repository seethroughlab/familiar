# ADR-0079: A Moved Path Keeps an Invisible Alias for One Release

Status: accepted

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md), which separates the two
axes and establishes that a path is runtime coupling. This says what to do on the rare occasion one
has to move anyway.

## Context

`ADR-0072` point 4 keeps path changes rare, and most of the restructure lands in tags. A few paths
still have to move, because they name the wrong resource: `/queue/*` holds playback-session
persistence, radio suggestions and the offline manifest; `/playback/*` is the MCP command channel and
not playback at all.

**Moving a path is not like renaming a tag, and the difference is who breaks.** A tag rename breaks
the `familiar-apple` build, which `ADR-0007` counts as the mechanism working — a compile error in
another repository, fixed by recompiling. A path rename breaks **software already installed on
someone's phone**, which no build anywhere will report.

**The two repositories version independently and say so.**
`familiar-apple/CHANGELOG.md` states it in its second paragraph: *"the two version independently —
the server is at `0.2.0-alpha1` while these apps are at `1.2`. **A release here does not imply one
there.**"* The apps ship through TestFlight and the App Store, so a client release is gated on review
in a way a server upgrade is not, and a self-hoster upgrades their server whenever they please.
"Release both together" is therefore not something the project can actually promise.

**Three kinds of client hold a path, and only one of them is regenerated.**

1. The **generated Swift client**, which follows the schema and is fixed by regenerating.
2. **Hand-written Swift**, which does not: `PlaybackCommandClient.swift:144` and `:210` build
   `api/v1/playback/commands` and `api/v1/playback/artifacts/{id}` by hand;
   `ServerConfiguration.swift:326,352`, `MixtapesStore.swift:104` and `FamiliarKit/Artwork.swift:52`
   do the same for `/tracks`, `/mixtapes` and artwork.
3. **`VisualizerBundle.html`**, the 3.4 MB build artefact vendored into the app bundle. It contains a
   whole inlined API client with paths compiled in — `/tracks/{id}/visualizer-ranking`,
   `/tracks/{id}/similar`, `/tracks/{id}/stream`, `/tracks/{id}/lyrics`, `/tracks/{id}/album-gain`,
   `/videos/{id}/search`, `/videos/{id}/stream` and more. A shipped app carries whichever copy was
   vendored when it was built.

So a path move with no compatibility step is not a coordinated release; it is a decision that
everyone running the previous app gets errors until they upgrade.

**The obvious mitigation is exactly the thing this restructure exists to prevent.** A deprecated
route left in the schema, tagged and documented, is precisely the archaeology a newcomer should never
have to read: two paths for one thing, one of them explained by history. That tension is what this
ADR resolves.

## Decision

1. **A moved path keeps its old spelling registered, and that registration is invisible.** The old
   route is re-declared with `include_in_schema=False`, delegating to the same handler. It does not
   appear in `openapi.json`, in `/docs`, in `/redoc`, in the generated Swift client, or in anything
   `lint_openapi.py` counts. **A newcomer reading the API cannot see it**, which is what makes this
   compatible with the goal rather than a compromise of it.

2. **The alias is a delegation, never a copy.** It calls the same handler function. Two
   implementations of one endpoint would drift, and the second one would be the untested one.

3. **The alias announces itself to machines, not to people.** It responds with `Deprecation: true`
   and a `Sunset` date (RFC 8594). Anything still calling the old path can be found in logs, which is
   how the removal decision gets made on evidence rather than on a calendar.

4. **One server minor, and the trigger is written down when the alias is added.** The alias is
   removed when the last app build that used the old path is no longer offered — not on a date, and
   not "when convenient". `ADR-0058` point 4 established that a removal condition must be checkable
   by reading something; the ADR that adds an alias records the specific build number and where to
   check it.

5. **Aliases are listed in one place.** A single module holds every compatibility route, so the set
   is countable and its removal is one file's worth of work. An alias scattered beside its handler is
   an alias nobody deletes.

6. **This applies to paths only.** Tags, operation ids and schema names get no aliases — they are
   compile-time, `ADR-0007` intends the compile error, and there is nothing in the field holding
   them.

7. **`GET /api/v1/health` is a permanent exception, not an alias.** Container probes, load balancers
   and platform health checks are not clients and are not versioned with anything. It stays
   registered at its current path indefinitely, unschemad, whatever the `system` tag does with it.

## Alternatives Considered

**Move the paths and coordinate the releases.** The plan of record until the versioning statement in
`familiar-apple/CHANGELOG.md` was read. Rejected because the coordination it assumes does not exist:
App Store review is days, self-hosters upgrade servers on their own schedule, and nothing forces a
user to update an app. The failure mode is silent errors on a phone, which is the hardest place in
this project to observe anything.

**Leave the misleading paths alone.** Genuinely tempting — `/queue/session` is not that misleading in
practice, and `ADR-0072` point 4 already keeps most paths still. Rejected for `/playback/*`
specifically: a prefix that says "playback" for a channel that carries agent commands, next to
`tracks/playback.py` which records listening events, is the kind of collision that makes people write
the wrong code. Being wrong is worse than being ugly.

**Deprecate visibly — keep the old path in the schema, marked `deprecated: true`.** The conventional
answer, and it is what most APIs do. Rejected because the schema is read by exactly two audiences
here: a generator, which would emit a deprecated Swift method nobody should call, and a person
orienting themselves, for whom a second spelling of one endpoint is pure noise. Neither is served.

**Version the API — `/api/v2/…` for the new shape.** Rejected as disproportionate: this reshapes
about six paths out of 228, and a major version implies a compatibility surface far larger than what
is changing. It would also double the schema for years.

**Redirect with 307/308 instead of delegating.** Rejected because redirect handling varies across the
three client kinds — `URLSession`, swift-openapi-generator's transport, and the axios build inside
the vendored bundle — and a redirect that one of them silently drops on a POST is a defect that only
appears in the field.

## Consequences

- **Positive** — the paths that lie can be corrected without a flag day, and installed applications
  keep working across the change.
- **Positive** — the resulting API reads as though it had always been shaped this way, because the
  compatibility surface is invisible to every reader of the schema.
- **Positive** — point 3 turns "can we remove this yet" into a log query.
- **Tradeoff** — for one release the server answers on paths that are not in its own contract. Anyone
  reading the *source* will find them; only readers of the schema are spared. Point 5's single module
  is what keeps that honest.
- **Tradeoff** — an invisible route is untested by anything that works from the schema, including
  contract tests. Each alias needs an explicit test that the old path still reaches the handler, or
  it will rot silently — which is the failure mode this ADR is otherwise designed to avoid.
- **Tradeoff** — point 4's trigger depends on someone actually checking. It is weaker than
  `ADR-0058` point 4's file-reading condition, because "no longer offered on the App Store" is not in
  the repository.
- **Follow-up** — the alias module's removal is a scheduled piece of work, not a cleanup someone
  notices. It should be a task at the time the alias is created.
- **Follow-up** — `VisualizerBundle.html` is the client least likely to be current, since it is
  vendored by hand. `ADR-0078` point 4's revision stamp is what makes its lag visible, and the two
  ADRs should land together.
