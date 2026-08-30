#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Re-check the mechanical half of the site's claims (ADR-0055 point 2).

The judgement half lives in `docs/SITE-CLAIMS.md` and needs a person. This covers the part
that rots on its own — a version that drifts from the changelog, a link that dies, a
screenshot that ages past the surface it shows, a term from the retired register creeping
back, an anchor left dangling by a section that moved.

It exists because the first audit of this site was ad-hoc greps in a conversation, which
passed a false claim and left nothing to re-run. Anything checkable belongs here rather
than in someone's memory of having looked.

    uv run site/scripts/check-claims.py            # all checks
    uv run site/scripts/check-claims.py --offline  # skip the network
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
ROOT = SITE.parent
PAGES = ["index.html", "faq.html", "privacy.html"]

# From WEB-PARITY.md's "Retired, and deliberately not coming back" table. A page that says
# any of these has re-acquired a claim someone deliberately removed. The chat one is not
# hypothetical: privacy.html told readers their conversations went to Anthropic for two days
# after the feature was gone.
RETIRED = {
    "chat feature": "chat was retired (ADR-0043 -> ADR-0048); an MCP host brings its own model",
    "capacitor": "the Capacitor app was deleted 2026-08-11 (ADR-0001 point 6)",
    "spotify import": "Spotify favourites import was retired 2026-08-10",
    "ai chat": "same as chat feature",
}

# Screenshots are generated (ADR-0039 point 5) and nobody notices when they stop being. The
# grid was showing pictures four months older than the surfaces they claimed to show.
SCREENSHOT_MAX_AGE_DAYS = 60

# Where the site actually is (ADR-0097 point 4). A constant, not an argument: a configurable
# target could be pointed at a preview URL, which is precisely the failure this check exists to
# catch, only parameterised.
LIVE_URL = "https://familiar.seethroughlab.com/"


def fail(msg: str) -> str:
    return f"  FAIL  {msg}"


def ok(msg: str) -> str:
    return f"  ok    {msg}"


def check_version(problems: list[str]) -> list[str]:
    """The version chip must match the top of CHANGELOG.md."""
    changelog = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(r"^## \[([^\]]+)\] - (\S+)", changelog, re.M)
    if not m:
        problems.append(fail("CHANGELOG.md has no parseable release heading"))
        return []
    want = f"v{m.group(1)} · {m.group(2)}"
    page = (SITE / "index.html").read_text()
    chip = re.search(r"<span class=\"version-dot\"></span>\s*([^<]+)", page)
    got = chip.group(1).strip() if chip else "(no chip)"
    if got != want:
        problems.append(fail(f"version chip is {got!r}, CHANGELOG says {want!r}"))
        return []
    return [ok(f"version chip matches CHANGELOG ({want})")]


def check_retired(problems: list[str]) -> list[str]:
    out = []
    for name in PAGES:
        text = (SITE / name).read_text().lower()
        for term, why in RETIRED.items():
            if term in text:
                problems.append(fail(f"{name} mentions {term!r} — {why}"))
    if not problems:
        out.append(ok(f"no retired features named across {len(PAGES)} pages"))
    return out


def check_anchors(problems: list[str]) -> list[str]:
    """Every internal anchor resolves. A dangling fragment does not error — it silently
    drops the reader at the top of the page, which is why this is worth automating."""
    index_ids = set(re.findall(r'id="([^"]+)"', (SITE / "index.html").read_text()))
    checked = 0
    for name in PAGES:
        text = (SITE / name).read_text()
        own = set(re.findall(r'id="([^"]+)"', text))
        for frag in re.findall(r'href="#([^"]+)"', text):
            checked += 1
            if frag not in own:
                problems.append(fail(f"{name}: #{frag} does not exist on that page"))
        for frag in re.findall(r'href="\./#([^"]+)"', text):
            checked += 1
            if frag not in index_ids:
                problems.append(fail(f"{name}: ./#{frag} does not exist on index.html"))
    return [ok(f"{checked} internal anchors resolve")]


def check_screenshots(problems: list[str]) -> list[str]:
    out, now = [], datetime.now(timezone.utc)
    refs = set()
    for name in PAGES:
        refs |= set(re.findall(r"\./screenshots/([\w.-]+)", (SITE / name).read_text()))
    for ref in sorted(refs):
        path = ROOT / "screenshots" / ref
        if not path.exists():
            problems.append(fail(f"screenshot missing: {ref}"))
            continue
        age = (now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)).days
        if age > SCREENSHOT_MAX_AGE_DAYS:
            problems.append(fail(f"{ref} is {age} days old (max {SCREENSHOT_MAX_AGE_DAYS}) "
                                 f"— regenerate with packages/web/e2e/screenshots.spec.ts"))
        else:
            out.append(ok(f"{ref} is {age} days old"))
    return out


def check_deployed(problems: list[str]) -> list[str]:
    """What the live site is serving, not what the working tree says (ADR-0097).

    This exists because every other check in this file reads `site/` from disk, and on
    2026-08-29 the deployed site was found to be four months stale — still describing the iOS
    app as a "native Capacitor wrapper" eighteen days after `packages/ios` was deleted. That is
    the exact string `RETIRED` below already knows about, with the reason attached. The check
    passed throughout, because the word was not in the working tree.

    The deploy had been green all along: the workflow succeeded, the action reported success,
    and the printed deployment URL served the right content. The Pages project's
    `production_branch` was `master` while this repository's branch is `main`, so Cloudflare
    filed every deployment as a preview and the production alias never moved. Nothing in CI can
    see that. Fetching the address a visitor types is the only check that can.
    """
    # The User-Agent is not optional: Cloudflare answers python-urllib's default with **403**,
    # so without it this check skips forever and reports that as fine — which is the silent pass
    # it was written to abolish. `check_links` already sets the same header, for the same reason.
    req = urllib.request.Request(LIVE_URL, headers={"User-Agent": "familiar-site-check"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # Reachable and answering wrongly. Point 3's exemption is for a host being *down*; a site
        # serving 403 or 404 to a visitor is a worse problem than a stale one, not a lesser one.
        problems.append(fail(f"{LIVE_URL} — HTTP {exc.code}"))
        return []
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Point 3: one host being unreachable is not a false claim. Skip, loudly, without failing.
        return [ok(f"skipped — {LIVE_URL} unreachable ({type(exc).__name__})")]

    out = []

    changelog = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(r"^## \[([^\]]+)\] - (\S+)", changelog, re.M)
    if not m:
        problems.append(fail("CHANGELOG.md has no parseable release heading"))
    else:
        want = f"v{m.group(1)} · {m.group(2)}"
        chip = re.search(r"<span class=\"version-dot\"></span>\s*([^<]+)", html)
        got = chip.group(1).strip() if chip else "(no chip)"
        if got != want:
            problems.append(fail(
                f"{LIVE_URL} is serving {got!r}, CHANGELOG says {want!r} — "
                f"the deploy is not reaching production. Check the Pages project's "
                f"production_branch against this repository's branch."))
        else:
            out.append(ok(f"live site is serving {want}"))

    # Point 2: the same retired terms, against the copy that is actually published.
    lowered = html.lower()
    for term, reason in sorted(RETIRED.items()):
        if term in lowered:
            problems.append(fail(f"{LIVE_URL} still says {term!r} — {reason}"))
    if not any(t in lowered for t in RETIRED):
        out.append(ok(f"no retired features named on the live site"))

    return out


def check_links(problems: list[str]) -> list[str]:
    out = set()
    for name in PAGES:
        out |= set(re.findall(r'href="(https?://[^"]+)"', (SITE / name).read_text()))
    results = []
    for url in sorted(out):
        code = None
        # HEAD first because it is cheap, then GET — plenty of app servers answer HEAD with
        # 405 while serving the page perfectly well. The demo instance is one of them, and
        # reporting it as a dead link is the check crying wolf about its own method.
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(url, method=method,
                                         headers={"User-Agent": "familiar-site-check"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:  # noqa: BLE001 — a dead link and a DNS failure are the same news
                problems.append(fail(f"{url} — {type(e).__name__}"))
                code = None
                break
            if code != 405:
                break
        if code is None:
            continue
        if code >= 400:
            problems.append(fail(f"{url} — HTTP {code}"))
        else:
            results.append(ok(f"{url} — {code}"))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip the link check")
    args = ap.parse_args()

    problems: list[str] = []
    sections = [
        ("version", check_version),
        ("retired features", check_retired),
        ("internal anchors", check_anchors),
        ("screenshots", check_screenshots),
    ]
    if not args.offline:
        sections.append(("deployed site", check_deployed))
        sections.append(("external links", check_links))

    for title, fn in sections:
        print(f"\n{title}")
        for line in fn(problems):
            print(line)

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(p)
        print("\nThe judgement half is docs/SITE-CLAIMS.md and is not checked here.")
        return 1
    print("All mechanical checks pass. The judgement half is docs/SITE-CLAIMS.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
