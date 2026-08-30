# ADR-0097: The Site Is Checked Where It Is Served

Status: accepted

Date: 2026-08-29

Implementation:
- Accepted and built the same day, on `adr-0097-check-the-deployed-site`. `check_deployed` in
  `site/scripts/check-claims.py`, run after the four local checks and before the link check, and
  skipped by `--offline`.
- **The check needs a `User-Agent` header or it never runs.** Cloudflare answers python-urllib's
  default with **403**, and the first version caught that alongside the connection errors and
  reported "skipped — unreachable", green, forever. That is the silent pass this ADR was written to
  abolish, reproduced inside the fix for it. `check_links` already sets
  `User-Agent: familiar-site-check` for the same reason.
- **Point 3 was implemented too broadly and has been narrowed.** A `URLError` or timeout is a host
  being down and skips; an `HTTPError` is the site reachable and answering *wrongly*, which now
  fails. A domain serving 403 or 404 to a visitor is a worse problem than a stale one, not a lesser
  one.
- Verified against all four branches, by pointing it at real URLs rather than by reasoning:
  the stale production deployment `b4f34b45` (**exit 1**, naming both versions and the
  `production_branch` cause); a genuine 404 (**exit 1**, `HTTP 404`); a non-resolving host
  (**exit 0**, skipped); and a `CHANGELOG.md` bumped without a redeploy (**exit 1**, both the local
  and the deployed check firing, which is the everyday case).
- **One attempted test proved nothing and had to be replaced.** Pointing the check at a nonexistent
  path on the Pages domain returned **200 with `index.html`** — Cloudflare Pages serves an SPA
  fallback for any unmatched path, so the check saw the correct page and passed. The 404 branch was
  re-tested against `raw.githubusercontent.com`. Worth knowing generally: **a 200 from
  `familiar-site.pages.dev` does not mean the path exists.**

Extends [ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md), whose point 2 requires
every claim on the site to be checkable and checked. This ADR says *which* site.

## Context

On 2026-08-29 the live site was found to be serving a build from **2026-04-17**, four months and one
minor version stale. Among the things it was telling visitors:

> — native Capacitor wrapper with background audio, lock-screen controls, and CarPlay scaffolding.

`packages/ios` was deleted on 2026-08-11 under `ADR-0001` point 6. That sentence is **the specific
claim `ADR-0055`'s audit was written to remove**, and it is named in `check-claims.py:41` as a
retired term, with the reason attached. The check passes. It has always passed. It reads
`site/index.html` from the working tree, where the word does not appear, and never asks what
`familiar.seethroughlab.com` is actually serving.

The site also had no illustrations, no MCP section, and none of the current screenshots — everything
`ADR-0054` and `ADR-0055` produced had been merged and never shipped.

### Why nothing shipped

`.github/workflows/cloudflare-pages.yml` runs on every push to `main` and deploys with
`cloudflare/pages-action@v1`. It has been succeeding — green ticks, "Deployment complete", the right
files uploaded. But the Cloudflare Pages project's `production_branch` is **`master`**, and this
repository's branch is `main`. Cloudflare therefore recorded every one of those deployments as a
**preview**: `wrangler pages deployment list` shows `Environment: Preview, Branch: main` for all of
them, while the production alias — which the custom domain is a CNAME to — stayed pinned to
deployment `b4f34b45` from 2026-05-26.

**Every signal available said the deploy worked.** The workflow was green, the action reported
success, and a deployment URL was printed and served the new content. The one thing nobody checked
was the address a visitor types.

### The shape, again

This is the fifth instance this month of a record disagreeing with the thing it describes —
`WEB-PARITY.md`, `ADR-0058` point 4's unreachable trigger, `ADR-0061`'s tabs, `ADR-0049`'s point 7,
and now the deployed site. It is also, exactly, the defect this project keeps naming in its own
code: **an affordance whose destination is not mounted.** A green deploy check whose output nobody
serves is that defect wearing CI's clothes.

The distinguishing feature of this one is that the verification existed and was pointed at the wrong
copy. `check-claims.py` is a good tool. It audits a directory.

## Decision

1. **`check-claims.py` gains a deploy check: fetch the live site and compare its version chip
   against `CHANGELOG.md`.** The same assertion `check_version` already makes about the working
   tree, made about the thing visitors load. A mismatch fails the run and names both versions.

2. **The live site is also checked for retired terms.** `check_retired` runs against the deployed
   HTML as well as the local files, using the same `RETIRED` map with its reasons. This is the check
   that would have caught "Capacitor" in May, and it costs one more comparison over HTML already
   fetched.

3. **The deploy check is skipped by `--offline`, and a host being *down* is a skip rather than a
   failure.** A site that is momentarily unreachable is not a false claim. But this exemption covers
   connection failures only — `URLError`, timeouts. **An HTTP error status fails**, because a domain
   answering a visitor with 403 or 404 is a worse problem than a stale page, not a lesser one. The
   first implementation conflated the two and skipped on a 403 forever; see the Implementation note.

4. **The check reads the domain from a constant in the script, not from an environment variable.**
   `https://familiar.seethroughlab.com` is what the site *is*. A configurable target would let a run
   pass by pointing at a preview URL, which is the failure this ADR exists to prevent, parameterised.

5. **Version equality is the test, not recency.** Comparing dates would need a rule about how stale
   is too stale, and any such rule is a number someone will raise when it becomes inconvenient.
   Either the deployed chip matches `CHANGELOG.md` or it does not.

6. **This does not attempt to fix the deploy.** The `production_branch` setting lives in Cloudflare
   and is not in this repository; changing it is a dashboard action. What this ADR guarantees is
   that the *next* time it silently stops working, something says so.

## Alternatives Considered

- **Fix the Cloudflare setting and add no check.** The immediate cause, and it is one field. Rejected
  because it addresses this instance and not the class: the deploy can break again — a token
  expires, a project is recreated, the action is deprecated — and the failure mode is silence in
  every case. The setting should be fixed *and* watched.

- **Have the deploy workflow verify itself** — fetch the live URL as a final step and fail the job.
  Attractive, because it fails at the moment of deploying. Rejected on timing: Cloudflare's alias
  moves asynchronously, so the step needs a poll with a timeout, and a flaky deploy job trains people
  to re-run it. The check belongs where the other claims are checked, run deliberately.

- **Compare a content hash of the deployed page against the built `_site/`.** Strictly stronger — it
  would catch a partial or corrupted deploy, not just a stale one. Rejected as too tight: the built
  output is not byte-stable across a Pages deploy, and a check that cries wolf gets disabled.
  The version chip is a deliberate, human-maintained fingerprint and moves exactly when a release
  does.

- **A scheduled workflow that checks the live site daily.** The most likely to catch drift early, and
  worth doing later. Rejected for now because it needs a notification channel that this project does
  not have; a cron job whose failure nobody sees is the same defect a third time.

## Consequences

- **Positive** — `ADR-0055` point 2's promise finally covers the artefact a visitor sees. Until now
  it covered a directory.
- **Positive** — the check that already knows why "Capacitor" is retired gets to apply that knowledge
  to the place the word was actually appearing.
- **Tradeoff** — `check-claims.py` gains a dependency on one external host being up. Point 3 bounds
  it: unreachable is a skip, stale is a failure.
- **Tradeoff** — the check is only as good as the version chip being maintained. If a release ships
  without the chip moving, this compares two equal wrong values. `check_version` already has that
  property against the working tree.
- **Follow-up** — the Cloudflare `production_branch` is `master` and should be `main`. Until it is,
  the GitHub Action will keep producing previews, and this new check will keep failing — correctly,
  and usefully, because it is the only thing that says so.
- **Follow-up** — the scheduled version of this, once there is somewhere for a failure to be seen.
