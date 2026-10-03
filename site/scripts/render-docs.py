#!/usr/bin/env python3
"""Render `docs/VISUALIZER_API.md` into `site/visualizers.html` (ADR-0103 point 1).

**The Markdown file stays the source.** This renders it; it does not restate it.
Two copies of a contract drift, and the one on the website is the copy nobody who
could correct it ever reads — which is `ADR-0097`'s lesson about a check whose
subject is not the thing anyone uses.

**On the build step this represents.** `ADR-0039` point 1 said the site has no
generator and no build step, and point 6 named rendered docs as the thing that
would reverse it. This is deliberately not a generator: it is one script rendering
one known file into the `Assemble site` step that already copies and prunes, with
no toolchain, no plugins and no content model. If a second document, an index or
permalinks ever want to exist, that is the moment `ADR-0039` point 6 is really
asking about, and the answer then should be a decision rather than another script.

Markdown is rendered by hand rather than by a dependency, because the subset this
one document uses is small and closed — headings, fenced code, inline code, bold,
links, lists, paragraphs — and adding a package to the site would be the toolchain
point 1 refused. If the document starts needing tables or footnotes, reach for a
library rather than growing this.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "VISUALIZER_API.md"
OUTPUT = ROOT / "site" / "visualizers.html"
GALLERY_DATA = ROOT / "site" / "visualizers.json"

#: Bumped when the *contract* changes, not when this renderer does. Shown on the
#: page so an author can tell which version they are reading — ADR-0103 point 6.
API_VERSION = 1


DOCS_URL = "https://github.com/seethroughlab/familiar/blob/main/docs/"


def _href(target: str) -> str:
    """A link as the page must hold it. The document's relative links (`decisions/ADR-….md`)
    resolve against `docs/` in the repository, and 404'd on the site, where there is no `docs/`."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
        return target
    return DOCS_URL + target.removeprefix("./")


def _inline(text: str) -> str:
    """Escape, then re-introduce the inline markup this document actually uses."""
    out = html.escape(text, quote=False)
    # Code first: nothing inside a code span should be processed further, and doing
    # it first means a `**` inside backticks stays literal.
    codes: list[str] = []

    def keep(m: re.Match) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = re.sub(r"`([^`]+)`", keep, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*(?!\s)([^*]+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{_href(m.group(2))}">{m.group(1)}</a>', out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def render_markdown(md: str) -> str:
    """The closed subset `VISUALIZER_API.md` uses. Not a general Markdown renderer.

    Block by block, as Markdown means it: consecutive lines are one paragraph, an indented line
    continues the list item above it, and `>` lines are one quotation. It rendered every source
    line as its own `<p>` until 2026-10-03, which broke sentences mid-way, split list items from
    their continuations and printed blockquote markers as `&gt;`.
    """
    lines = md.split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    quote: list[str] = []
    items: list[list[str]] = []
    in_code = False
    code: list[str] = []

    def flush() -> None:
        if paragraph:
            parts.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if quote:
            parts.append(f"<blockquote><p>{_inline(' '.join(quote))}</p></blockquote>")
            quote.clear()
        if items:
            parts.append("<ul>" + "".join(f"<li>{_inline(' '.join(i))}</li>" for i in items) + "</ul>")
            items.clear()

    for line in lines:
        if line.startswith("```"):
            if in_code:
                parts.append(
                    "<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>"
                )
                code = []
                in_code = False
            else:
                flush()
                in_code = True
            continue

        if in_code:
            code.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            flush()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            # The document's H1 becomes the page's own title, so it is not repeated
            # in the body.
            if level == 1:
                continue
            parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        if stripped.startswith(">"):
            if paragraph or items:
                flush()
            quote.append(stripped.lstrip(">").strip())
            continue

        item = re.match(r"^[-*]\s+(.*)$", stripped)
        if item:
            if paragraph or quote:
                flush()
            items.append([item.group(1)])
            continue

        if items and line[:1].isspace():
            items[-1].append(stripped)
            continue

        if items or quote:
            flush()
        paragraph.append(stripped)

    flush()
    if in_code:
        raise SystemExit("render-docs: unclosed code fence in VISUALIZER_API.md")
    return "\n".join(parts)


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Visualizer API — Familiar</title>
  <meta name="description" content="Write a visualizer for Familiar: a folder with an index.html, four events, and no libraries to learn.">
  <link rel="icon" type="image/svg+xml" href="./assets/icon.svg">
  <link rel="stylesheet" href="./assets/site.css">
</head>
<body>

<nav class="topnav" aria-label="Primary">
  <a class="topnav-brand" href="./">
    <img src="./assets/icon.svg" alt="" aria-hidden="true">
    <span>Familiar</span>
  </a>
  <div class="topnav-links">
    <a href="./#features">Features</a>
    <a href="./#comparison">Compare</a>
    <a href="./faq.html">FAQ</a>
    <a href="./#install" class="topnav-install">Install</a>
  </div>
</nav>

<main id="top" class="doc">
  <h1>Visualizer API</h1>
  <p class="doc-meta">
    Contract version <strong>apiVersion&nbsp;{api_version}</strong>.
    Rendered from <a href="https://github.com/seethroughlab/familiar/blob/main/docs/VISUALIZER_API.md">docs/VISUALIZER_API.md</a>,
    which is the source of truth.
  </p>
{body}
</main>

<footer>
  <p>MIT-licensed · <a href="https://github.com/seethroughlab/familiar" target="_blank" rel="noopener">GitHub</a> · <a href="https://github.com/seethroughlab/familiar/tree/main/docs" target="_blank" rel="noopener">Docs</a> · <a href="./faq.html">FAQ</a> · <a href="./privacy.html">Privacy</a> · <a href="https://github.com/seethroughlab/familiar/issues" target="_blank" rel="noopener">Report a bug</a></p>
</footer>

</body>
</html>
"""


def render_gallery() -> str:
    """The gallery, shipped set first (ADR-0103 point 2).

    Leading with what ships is the correction to `ADR-0063`, whose gallery listed
    only submissions and so would have launched empty and stayed empty until
    strangers arrived. These five exist today and are the worked examples the
    contract above refers to.

    **The site hosts no bundles** (point 3). A submitted entry is a link to somebody
    else's repository; Familiar links to third-party code, it does not distribute it.
    """
    import json

    data = json.loads(GALLERY_DATA.read_text())

    def card(entry: dict, *, shipped: bool) -> str:
        name = html.escape(entry["name"], quote=False)
        desc = html.escape(entry["description"], quote=False)
        author = html.escape(entry.get("author") or "Unknown", quote=False)
        api = entry.get("apiVersion")
        badge = "Ships with Familiar" if shipped else f"by {author}"
        link = entry.get("url")
        title = (
            f'<a href="{html.escape(link, quote=True)}">{name}</a>' if link else name
        )
        return (
            '<li class="viz-card">'
            f"<h3>{title}</h3>"
            f"<p>{desc}</p>"
            f'<p class="viz-meta">{badge}'
            + (f" · apiVersion {int(api)}" if api is not None else "")
            + "</p></li>"
        )

    shipped_cards = "\n".join(card(v, shipped=True) for v in data["shipped"])
    parts = [
        '<h2 id="gallery">The gallery</h2>',
        "<p>These five ship with Familiar and are seeded into your "
        "<code>Visualizers/</code> folder the first time it runs. Each is a folder "
        "with an <code>index.html</code> — the same thing yours will be.</p>",
        f'<ul class="viz-grid">{shipped_cards}</ul>',
    ]

    submitted = data.get("submitted") or []
    parts.append("<h3>Written by other people</h3>")
    if submitted:
        parts.append(
            '<ul class="viz-grid">'
            + "\n".join(card(v, shipped=False) for v in submitted)
            + "</ul>"
        )
    else:
        # An empty state that says why it is empty, rather than an empty list that
        # reads as a broken page.
        parts.append(
            "<p>None yet — this is a new contract. If you write one, "
            '<a href="https://github.com/seethroughlab/familiar/blob/main/site/visualizers.json">'
            "open a pull request against <code>site/visualizers.json</code></a> with a name, "
            "an author, the <code>apiVersion</code> you target and a link to your repository. "
            "Familiar links to your code; it does not host it.</p>"
        )
    return "\n".join(parts)


def main() -> int:
    if not SOURCE.exists():
        print(f"render-docs: {SOURCE} not found", file=sys.stderr)
        return 1
    if not GALLERY_DATA.exists():
        print(f"render-docs: {GALLERY_DATA} not found", file=sys.stderr)
        return 1
    body = render_markdown(SOURCE.read_text()) + "\n" + render_gallery()
    OUTPUT.write_text(PAGE.format(api_version=API_VERSION, body=body))
    print(f"render-docs: wrote {OUTPUT.relative_to(ROOT)} ({len(body)} bytes of body)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
