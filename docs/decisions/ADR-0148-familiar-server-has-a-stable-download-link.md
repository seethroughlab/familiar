# ADR-0148: Familiar Server Has a Stable Download Link

Status: accepted

Date: 2026-10-03

Implementation:
- **Accepted 2026-10-03**, as written. Not yet built.

Extends [ADR-0135](ADR-0135-familiar-server-is-a-separate-app.md);
closes the follow-up in [ADR-0143](ADR-0143-the-install-section-is-a-three-step-chooser.md)

## Context

ADR-0146 puts a "Download Familiar Server for Mac" button in the hero. Today there is no URL for it
to point at. Read on 2026-10-03:

- `release.yml` creates every release with `prerelease: ${{ contains(github.ref_name, '-') }}`, and
  every tag so far is a beta, so **every release is a prerelease**.
- GitHub's `releases/latest` skips prereleases. With no full release it redirects to `/releases`,
  and `releases/latest/download/<name>` does not resolve (ADR-0135, ADR-0143's follow-up).
- The asset's name carries its version: `Familiar-Server-<version>.dmg`
  (`desktop/macos/scripts/package.sh`), so no fixed URL could name it anyway.
- So the site and `docs/FAMILIAR-SERVER.md` send a reader to the releases page to find "the newest
  release's Assets" — the developer's path, on the page meant for someone who is not one.
- **The `.dmg` arrives late.** `create-release` makes the release; the `familiar-server` job on the
  self-hosted Mac builds, notarizes and attaches the `.dmg` afterwards (`release.yml`, "Attach to the
  release"), tens of minutes later. A release marked latest at creation would serve a 404 for the
  fixed name during that gap, and permanently if the macOS job failed.

Docker already behaves as this ADR proposes: `latest` moves on every beta once its smoke tests pass.

## Decision

1. **The release job also attaches the `.dmg` under a fixed name, `Familiar-Server.dmg`**, beside the
   versioned one, in the same step that uploads it.

2. **A release is marked GitHub's latest, and not a prerelease, only after that upload succeeds** —
   a `gh release edit "$TAG" --prerelease=false --latest` step after "Attach to the release". Until
   then the previous release stays latest, so
   `https://github.com/seethroughlab/familiar/releases/latest/download/Familiar-Server.dmg` always
   names a file that exists, and a failed macOS build leaves the last good one in place.

3. **That URL is the one the site, `docs/FAMILIAR-SERVER.md` and the README link.** The versioned
   asset, the Sparkle appcast (which names versioned URLs) and Docker's tags are unchanged.

4. **`check-claims.py`'s link check covers it** as it covers every absolute link, so a release that
   broke the fixed name would fail the site's deploy check rather than a reader's download.

## Alternatives Considered

- **A redirect on the site, written by the release job.** Keeps releases as prereleases. Rejected:
  the release job would commit to `main` or deploy the site on every release, a second moving part
  whose failure looks exactly like a working link to the wrong version.
- **Link the appcast's newest entry from the page with JavaScript.** Uses a feed that already
  exists. Rejected: the page must work without JavaScript (ADR-0095 point 6), and a download button
  that depends on a script fetching XML is the affordance-without-destination this project keeps
  finding.
- **Stop tagging betas; ship 1.0.** The cleanest answer, eventually. Rejected as the fix: the version
  number says what state the software is in, and the download link should not wait on it.
- **Mark releases latest when they are created.** One line. Rejected for the gap in Context: the
  fixed name would 404 until the macOS job finishes, and for good if it fails.

## Consequences

- **Positive:** one URL, forever, for "the current Familiar Server".
- **Tradeoff:** betas show as "Latest" on GitHub, and GitHub's "Pre-release" label stops warning
  anyone. The version number and the changelog carry that instead.
- **Tradeoff:** a release whose macOS job fails is never marked latest, so Docker's `latest` and
  GitHub's "Latest" can briefly name different versions. The download link stays correct, which is
  what matters.
- **Follow-up:** the first release after this ships is the first time the link resolves; the site's
  hero waits for it (ADR-0146 point 7 already holds the hero back for pairing).
