# ADR-0069: The Site Adopts a Static Site Generator

Status: rejected

**Rejected 2026-08-31, and not because its reasoning was wrong.** Its trigger was
`ADR-0039` point 6 — rendered docs arriving — and that condition did arrive: `ADR-0103`
published `docs/VISUALIZER_API.md` on the site. It was done with **one script over one
known file**, added to the `Assemble site` step that already copied and pruned, and the
result was a rendered page with no toolchain, no plugins, no content model and no
dependency. The migration this ADR describes — Eleventy, a dev dependency, byte-identical
re-renders of every existing page — would have been a large change to reach the same place.

Two things kept, because they were the valuable half:

- **Point 5's concern is now implemented.** "`check-claims.py` runs against the build
  output, and the build fails if it fails" — the script was run by no workflow at all, so
  the ledger `ADR-0055` point 2 calls the only thing standing between this site and lying
  by attrition was purely manual. `cloudflare-pages.yml` now runs it before the deploy and
  again against the live site afterwards.
- **`ADR-0039` point 6 still stands**, and this ADR's own framing is the reason. Point 6
  asks for the decision to be *made again* when docs want to be a section with an index and
  permalinks. One rendered document is not that. A second one, or an index, still is — and
  this ADR remains the right starting point when it happens.

`ADR-0055`, the condition in point 6, has since landed, so this was no longer blocked. It
is rejected on its merits rather than left proposed indefinitely.

Date: 2026-08-17

Supersedes [ADR-0039](ADR-0039-the-website-is-rebuilt-in-place.md) points 1 and 6. The rest of
`0039` stands: the site lives in `site/`, deploys to Cloudflare Pages, leads with the install
command, and still has no blog. Point 6 named the condition under which point 1 should be decided
again; this is that condition arriving, so the decision is made again rather than worked around.

## Context

`0039` point 1 reads in full: *"The site stays static, in `site/`, deployed to Cloudflare Pages. No
generator, no build step, no new dependency, no `packages/` workspace. Two HTML files and a
stylesheet do not justify a toolchain, and the deployment path already works."*

That was correct, and the reasoning is worth preserving rather than dismissed: the site is three
hand-written pages — `site/index.html` (15,890 bytes), `site/faq.html`, `site/privacy.html` — plus
`assets/`, a `screenshots` symlink into the repository root, and two Python scripts. There is no
generator anywhere in this repository: no mkdocs, no Docusaurus, no Astro, no Eleventy, no
`_config.yml`.

**Point 6 is the part that matters here, and it is unusually specific about its own reversal:**

> Release notes, a blog and rendered docs are out of scope, and that is what would reverse point 1.
> Fork has all three and they are why Fork would need a generator. Familiar has `CHANGELOG.md` and a
> `docs/` directory of unbuilt Markdown; the moment either wants to be a section of the site with an
> index and permalinks, this decision should be made again rather than worked around with
> hand-written pages.

[ADR-0063](ADR-0063-the-visualizer-api-is-published-for-outside-authors.md) wants exactly that: the
719-line `docs/VISUALIZER_API.md` as a section of the site, plus a gallery with an index and a
permalink per listed visualizer. It is the case point 6 reserved, arriving for the reason point 6
predicted.

**[ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md) already rejected a generator,
and that rejection has expired rather than been overruled.** Its alternative reads: *"Move to a
static site generator so docs, changelog and FAQ become real sections… Rejected because it reverses
`0039` point 1 and point 6 for a page of five sections, and `0039` was explicit that this is the
decision to make again only when a blog or rendered docs are actually wanted."* The rejection was
conditional on its own terms. Rendered docs are now actually wanted, so the condition it named is
met — this ADR is not disagreeing with `0055`, it is the branch `0055` left open.

**The boundary that does not move.** [ADR-0038](ADR-0038-the-demo-server-is-always-on.md) point 7
holds the demo server to *"not hosted Familiar… no growth into a service"*, and `0039` separately
rejected serving the site from the Familiar server because *"the marketing site must be up when
nobody's server is — it is what someone reads before they have one"*. A generator changes how the
site is built. It must not change where it is served from, and this ADR does not.

## Decision

1. **The site is built by Eleventy, from sources in `site/`, and still deploys to Cloudflare
   Pages.** The generator is chosen for the two properties this specific job needs and not for
   capability in general: it passes HTML through untouched, so the three existing pages move
   without being rewritten, and it accepts arbitrary input globs, so Markdown that lives elsewhere
   in the repository can be rendered from where it already is. It emits static HTML with no client
   runtime, which is the part of `0039` point 1 that was actually load-bearing.

2. **Markdown in the repository stays the single source of truth, and is rendered in place.**
   `docs/VISUALIZER_API.md` is not copied into `site/`. A second copy of a contract is precisely
   the drift `ADR-0055` point 2 exists to prevent, and a documentation page that disagrees with the
   document it was made from is worse than no page. The `screenshots` symlink is the existing
   precedent for reaching out of `site/` rather than duplicating into it.

3. **Only developer documentation becomes a rendered section. The blog is still refused, and
   `CHANGELOG.md` is not published by this ADR.** `0039` point 6 named three things; this reverses
   it for one of them. A changelog section is defensible and is deliberately left undecided, because
   the argument for it is about release communication and has nothing to do with why a generator is
   being adopted. Adding it later is a paragraph in a new ADR, not a re-migration.

4. **The generator is a dev dependency of `site/`, not a member of the pnpm workspace.** `0039`
   point 1's "no `packages/` workspace" clause survives intact: `site/` gets its own `package.json`
   and the frontend build is untouched. The site must remain buildable and deployable by someone
   who has never run the app.

5. **`site/scripts/check-claims.py` runs against the build output, and the build fails if it
   fails.** The script currently reads `site/index.html` directly and hardcodes
   `PAGES = ["index.html", "faq.html", "privacy.html"]`; under a generator those become artefacts of
   a build, so the script has to be pointed at the output directory. This is called out as a
   decision point rather than left to implementation because `ADR-0055` point 2's ledger is the only
   mechanism standing between this site and lying by attrition, and a migration that quietly stops
   running it would remove that mechanism while appearing to succeed.

6. **`ADR-0055` lands before this migration, or is withdrawn first.** `0055` is still `proposed` and
   unimplemented: it deletes the screenshot grid, collapses fourteen features into five illustrated
   sections, moves the FAQ to its own page and caps `<main>` at six claims and 700 words. Migrating
   the current eleven-section page into a generator and then restructuring it means doing the work
   twice, and the second pass is the one that would be rushed.

7. **The pages the site already has must render byte-identically at first, and the deploy is
   verified before anything new is added.** A migration and a new section in the same change makes a
   broken page ambiguous. `0039` point 8 set the precedent when the demo link was held back for
   hours: **the condition is not "the build succeeded" but "the thing a visitor will do works"**.

## Alternatives Considered

- **Astro.** More capable than Eleventy in every direction — components, islands, content
  collections, first-class Markdown. Genuinely the better tool if the site ever becomes an
  application. Rejected because every one of those capabilities is one this site has no use for,
  and its content-collection model expects Markdown to live inside the project, which fights point
  2's requirement that `docs/` stays where it is. The larger dependency surface buys nothing here.

- **One narrow render step: a script that turns `docs/VISUALIZER_API.md` into a styled HTML page at
  deploy time, and nothing else.** Reverses only "no build step" and leaves the rest of `0039`
  point 1 standing, which makes it the smallest honest change. Rejected because `ADR-0063` also
  wants a gallery index with a permalink per entry, and a bespoke script that grows a routing and
  templating layer is a static site generator being written by hand, badly.

- **Hand-write the documentation as HTML pages.** No new dependency at all, and the site keeps
  working exactly as it does. Rejected because it is the workaround `0039` point 6 forbids by name,
  and because it creates the second copy of the contract that point 2 rules out. A 719-line document
  transcribed by hand is stale the first time the source changes.

- **Link out to GitHub, which renders Markdown already, and add nothing to the site.** Costs
  nothing, reverses nothing, and is genuinely how most small projects handle this. Rejected because
  it does not answer the ask: an invitation to outside authors that bounces them to a repository
  file browser is not a documented API that lives on the website, and the gallery has nowhere to go
  at all.

- **Serve the documentation from the Familiar server, alongside `/embed` and `/visualizer`.** The
  bundle already builds three documents and the machinery is there. Rejected on `0039`'s original
  grounds — the site is what someone reads *before* they have a server — and on
  [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md) point 2, which holds the web app to
  three destinations.

## Consequences

- **Positive:** `docs/` becomes publishable without being copied, which makes `ADR-0063` possible
  and makes any future document cheap to publish.
- **Positive:** The decision `0039` point 6 deferred is now made explicitly, with its trigger
  recorded, rather than eroded by a series of hand-written pages that each seemed reasonable.
- **Tradeoff:** The site gains a toolchain, and `0039`'s objection to that was correct at the time
  and is not wrong now — it is outweighed. A contributor who wants to fix a typo on the marketing
  page now needs Node and an install where previously they needed a text editor.
- **Tradeoff:** The deploy path gains a way to fail that it did not have. Cloudflare Pages currently
  publishes files that are already correct on disk; a build step can succeed and emit something
  wrong, which is what point 7 exists to catch and point 5 exists to keep catching.
- **Tradeoff:** Point 6 puts this behind `ADR-0055`, which has been `proposed` since 2026-08-13. If
  `0055` stalls, this stalls, and `ADR-0063` stalls behind it. The alternative — migrating first —
  was rejected, but the dependency is real and is the most likely reason this does not happen.
- **Follow-up:** `site/README.md` describes the current no-build deployment and will be wrong the
  moment this lands. `0039` point 7 corrected that file once already, after it spent months
  describing GitHub Pages and a CNAME the repository does not contain.
- **Follow-up:** Whether `CHANGELOG.md` becomes a rendered section, per point 3. The machinery will
  exist and the decision will not have been made.
- **Follow-up:** The `.github/workflows/cloudflare-pages.yml` job is still named `Pages`, a name
  inherited from the GitHub Pages era. `0039` left renaming it as the only thing keeping that
  confusion from recurring, and this change touches the same workflow.
