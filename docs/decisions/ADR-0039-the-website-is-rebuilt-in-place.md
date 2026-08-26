# ADR-0039: The Website Is Rebuilt in Place

Status: accepted

Date: 2026-08-06

## Implementation

Points 1, 2, 3, 5, 6 and 7 are done. **Point 4 is not**, and point 8 is half done.

The page was reordered rather than rewritten, exactly as point 2 asks — all ten sections were
extracted whole and reassembled, so no content was lost or retyped. The order is now screenshots,
features, ask, comparison, who it's for, remote access, FAQ, intro, install, feedback, and a closing
call to action before the footer. **Install moved from seventh to second-from-last on purpose**: the
*command* is in the hero under point 3, and the detailed section is the repeat at the bottom that
point 2 asks for. The manifesto paragraph that used to be the gate is now a coda.

Point 3 put the `docker compose` quickstart and the requirements line directly in the hero, at
smaller type than the page's other code blocks — it is a thing you copy, not a thing you read, and
at body size three long URLs dominate the hero they exist to support.

Point 7 corrected `site/README.md`, which had described GitHub Pages, a CNAME file the repository
does not contain, and DNS pointing at `seethroughlab.github.io`. It deploys to the Cloudflare Pages
project `familiar-site` via `CF_API_TOKEN` and `CF_ACCOUNT_ID`. The workflow is still named
`pages.yml` with a job called Pages, which is presumably how the stale text survived the migration —
the follow-up about renaming it stands, and is now the only thing keeping this from recurring.

**Point 8 is done.** The Apple clients are in the hero and the closing call to action, and the demo
link joined them once [ADR-0038](ADR-0038-the-demo-server-is-always-on.md)'s machine was up — which
happened the same day, after a Dockerfile fix.

It was absent for several hours in between, on purpose: `familiar-demo.fly.dev` was scaled to zero
and timing out at 30 seconds, and a "Try the demo" button that hangs is worse than no button. **The
condition for adding it was not "the deploy finished" but "the thing a visitor will do works"** —
verified as 32 tracks over the API and a `206 Partial Content` on a range request against a track's
stream, which is what a player actually issues. A demo that loads and cannot play is the same defect
one screen later.

**Point 4 — the illustration set — is untouched**, and the ADR's own tradeoff predicted this is the
part most likely to be left half-done. It is not half-done; it is not started, which is the better
of the two states. The structure is ready to receive it.

Verified rather than eyeballed: the document parses with every tag balanced, all fourteen in-page
anchors resolve to an id that exists (the nav and section order both changed, so this was the likely
breakage), and all eighteen referenced local assets are present.

- **Two follow-ups closed, 2026-08-13.**

  The workflow is renamed `cloudflare-pages.yml`, its job commented with why, and `site/README.md`
  points at the new path. That was the last thing keeping alive the confusion point 7 fixed.

  `og-image.png` was 485 kB and, more to the point, **stale**: it showed the AI Assistant panel that
  ADR-0048 removed and a "Spotify Library" sidebar item retired on 2026-08-10 — on the one asset
  that appears whenever anybody shares the link. Replaced with the Mac app on the site's own
  background at the canonical 1200×630, as `og-image.jpg`, **84 kB**. The follow-up asked for it to
  be regenerated "with the new illustration set"; the illustration set does not exist yet and the
  image was actively wrong, so it was regenerated from a screenshot instead. Point 4 still stands
  and this does not discharge it.

  The screenshot follow-up is also closed: five images of the Mac app are on the page, captured by
  driving it over the command channel ([ADR-0053](ADR-0053-the-command-channel-drives-and-observes-the-interface.md))
  and photographing the window with the system tool.

## Context

`https://familiar.seethroughlab.com/` is live and serves `site/index.html` — **364 lines** of
hand-written HTML, beside `privacy.html`, an `assets/` directory (`site.css` at 15 kB, `icon.svg`,
`app-store-badge.svg`, a 485 kB `og-image.png`) and a gitignored `screenshots` symlink to the repo
root. Thirteen commits in the last six months, the most recent 2026-07-26. It is maintained, not
abandoned.

Its current shape is ten stacked sections: hero, intro, "Who Familiar is for", "How Familiar
compares", Features, "Ask Familiar…", Install, "Listen from anywhere", FAQ, Screenshots, and beta
feedback. It reads as a very good README that has been given a stylesheet — which is what it is,
since `README.md` embeds the same fifteen screenshots from the same directory.

**There is a documentation conflict to record before touching anything.** `site/README.md` says:

> Published via GitHub Pages on push to `main` … The Pages workflow copies `site/` plus the
> repo-root `screenshots/` directory into `_site/`, writes the CNAME, and deploys. DNS:
> `familiar.seethroughlab.com` CNAME → `seethroughlab.github.io`.

None of that is true. `.github/workflows/pages.yml` assembles `_site/` and deploys through
`cloudflare/pages-action@v1` to a Cloudflare Pages project named `familiar-site`, using
`CF_API_TOKEN` and `CF_ACCOUNT_ID`. No CNAME file is written anywhere in the repository. The
workflow is still called `pages.yml` and its job is still called Pages, which is presumably how the
README survived the migration.

**The reference point for the rebuild is `git-fork.com`**, and it is worth naming what is being
borrowed. Fork's landing page is: a thin nav (Home / Release Notes / Blog / About), a hero whose
entire content is two download buttons with system requirements and price, a screenshot carousel
per platform, four feature callouts each pairing a sentence with an image, two feature matrices, a
short section introducing the two people who make it, a repeated download call to action, and a
footer. Generous whitespace, plain typography, and screenshots doing the persuading rather than
abstract graphics.

Two things transfer and one does not. What transfers is the **information architecture** — the
install path is above the fold and repeated at the bottom, and the product is shown rather than
described. What does not transfer is the visual register: Fork is deliberately neutral, and
Familiar is a self-hosted music player with a name that invites illustration. Black cats, crows,
witchy but playful is a real differentiator against a category of self-hosted software that all
looks like a dashboard.

**What the current page gets wrong by that measure** is that "Install" is the seventh section. A
self-hosted product's landing page is an install page with an argument attached; this one is an
argument with an install section some distance down it.

## Decision

1. **The site stays static, in `site/`, deployed to Cloudflare Pages.** No generator, no build
   step, no new dependency, no `packages/` workspace. Two HTML files and a stylesheet do not
   justify a toolchain, and the deployment path already works.

2. **The structure is rebuilt around the install path**, taking Fork's architecture: nav, hero with
   the install command and the app links immediately visible, screenshots close behind, feature
   callouts, a comparison table, FAQ, and a repeated install call to action before the footer. The
   existing sections are reordered and rewritten rather than replaced wholesale — the content is
   good, its ordering is not.

3. **Familiar's hero is a `docker run` and two app links, not a price.** Fork's hero sells a
   purchase; this one sells a five-minute install of MIT-licensed software plus the Apple clients.
   Requirements — Docker, 2 GB RAM, x86_64 or ARM64 — belong there, as Fork puts its OS
   requirements there.

4. **An illustration set is commissioned or drawn once, named, and used consistently.** Black cats,
   crows, and witchy-but-playful marks. SVG, inline where small, and theme-aware so the site can
   have a dark mode without a second set of files. This is called out as a decision because an
   illustration style adopted for a hero and then abandoned for every other section is worse than
   having none — the inconsistency reads as unfinished in a way plain typography never does.

5. **Screenshots stay generated.** `packages/web/e2e/screenshots.spec.ts` writes `screenshots/`,
   `README.md` embeds them and `pages.yml` copies them into `_site/`. The site does not acquire its
   own copies to drift, and a screenshot that goes stale is fixed by re-running the spec.

6. **Release notes, a blog and rendered docs are out of scope, and that is what would reverse point
   1.** Fork has all three and they are why Fork would need a generator. Familiar has
   `CHANGELOG.md` and a `docs/` directory of unbuilt Markdown; the moment either wants to be a
   section of the site with an index and permalinks, this decision should be made again rather than
   worked around with hand-written pages.

7. **`site/README.md` is corrected to describe Cloudflare Pages**, including the project name and
   the two secrets, and the DNS claim is removed or replaced with what is actually configured.

8. **The Apple clients get a place on the page.** `app-store-badge.svg` has been sitting in
   `assets/` since April in anticipation. Once
   [ADR-0038](ADR-0038-the-demo-server-is-always-on.md) provides a public instance, the demo gets a
   link too — the first time the site has been able to show the product rather than picture it.

## Alternatives Considered

**Adopt Astro or 11ty.** It is the obvious modern answer, it would let `docs/` and `CHANGELOG.md`
become real pages with an index, and both are cheap to run. Rejected *for now* and only for now:
the site is one landing page and a privacy page, and a build step for two documents is a
maintenance cost paid every time a dependency needs updating, on a repository that already carries
a pnpm workspace, a Python backend and a Swift package. Point 6 names the trigger that would change
this, which is release notes — not aesthetics.

**Redesign the visuals and leave the structure alone.** Cheapest real option, and it addresses the
part that is most obviously dated. Rejected because the structure is the weaker half: burying
Install seven sections down is the substantive problem, and a prettier version of the same ordering
fixes nothing that matters. The Fork reference was offered for its architecture as much as its
look.

**Move the site into `packages/` as a workspace and build it with Vite like the app.** One
toolchain across the repository, and shared design tokens with the product. Rejected because it
shares nothing real with the app — no components, no state, no routing — and would inherit a pnpm
install and a build for two static files. It would also couple the site's deployment to the app's
dependency tree, so a Vite upgrade could break the marketing page.

**Serve the site from the Familiar server itself, alongside the app.** No Cloudflare, no second
deployment, and `backend/app/main.py` already serves static files with an SPA fallback. Rejected
because the marketing site must be up when nobody's server is — it is what someone reads *before*
they have one — and because it would put a public-facing page inside the application that
[ADR-0038](ADR-0038-the-demo-server-is-always-on.md) point 7 is careful to keep from becoming a
service.

**Use an off-the-shelf template.** Fast, competent, and free. Rejected because the illustration set
in point 4 is the entire point of the exercise, and a template's value is that it looks like every
other site built from it — which is the position the self-hosted-software category is already in.

## Consequences

- **Positive:** The install path — the one thing a visitor needs — moves to the top and is repeated
  at the bottom, which is the change most likely to matter.
- **Positive:** No new dependency, no new CI step, and the deployment that works keeps working.
- **Positive:** A documentation conflict that has been misdescribing the deployment since the
  Cloudflare migration gets fixed, before someone follows it to a GitHub Pages setting that does
  nothing.
- **Positive:** The Apple clients and, once ADR-0038 lands, a live demo get somewhere to be
  announced.
- **Tradeoff:** Hand-written HTML means every section is duplicated markup, and a nav change is a
  change in two files. That is the accepted cost of point 1 and it grows with every page added —
  which is exactly why point 6 names the reversal condition.
- **Tradeoff:** An illustration set is real work with no functional payoff, and it is the part most
  likely to be left half-done. Point 4 is written to make that visible rather than to prevent it.
- **Tradeoff:** The site continues to depend on `screenshots/` being regenerated by hand after
  significant UI changes. Nothing checks that they are current, and several predate the Apple
  clients entirely.
- **Follow-up:** There are no screenshots of the native Mac or iOS apps at all — `screenshots/`
  contains the web app and its mobile layout. The Apple clients cannot be shown until something
  captures them, and `screenshots.spec.ts` is a Playwright spec that cannot.
- **Follow-up:** `og-image.png` is 485 kB, which is most of the page weight. Worth regenerating
  with the new illustration set rather than carrying forward.
- **Follow-up:** The workflow is named `pages.yml` and its job "Deploy Pages" while deploying to
  Cloudflare. Renaming it would prevent the next version of the conflict this ADR is fixing.
