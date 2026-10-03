#!/usr/bin/env python3
"""Add a release to Familiar Server's Sparkle feed (ADR-0135 point 3), or replace its entry.

The feed lives on the `appcast` branch as appcast.xml; `publish-update.sh` checks it out, runs this,
and pushes. Replacing rather than appending makes a re-run of the same release harmless. Newest
first: Sparkle reads every item and picks the highest `sparkle:version`, which is the bundle's
CFBundleVersion (a build timestamp), so the order is for people reading the file.

usage: appcast.py <appcast.xml> --tag v0.2.0-beta9 --build 202610011200 --length 371246439 \\
                  --signature <edSignature> --notes CHANGELOG.md
       appcast.py <appcast.xml> --notes CHANGELOG.md     refresh every entry's notes, add nothing

**Release notes are the item's `<description>`, from CHANGELOG.md, not a link.** Each item used to
carry `<sparkle:releaseNotesLink>` to the GitHub release page, and Sparkle shows a link by loading
the whole page into its small notes pane: the update dialog showed GitHub's header and nothing of
the release (found 2026-10-03). A description is HTML Sparkle renders as it is, so the dialog shows
the changelog section for that version.
"""

from __future__ import annotations

import argparse
import email.utils
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
REPO = "https://github.com/seethroughlab/familiar"
MINIMUM_SYSTEM = "14.0"  # LSMinimumSystemVersion in Support/Info.plist

ET.register_namespace("sparkle", SPARKLE)


# --- release notes ------------------------------------------------------------------------------

_STYLE = (
    '<meta name="color-scheme" content="light dark">'
    "<style>body{font:13px -apple-system,sans-serif;margin:12px;line-height:1.4}"
    "h3{font-size:13px;margin:14px 0 4px}ul{padding-left:18px;margin:4px 0}li{margin:3px 0}"
    "code{font:12px ui-monospace,monospace}p{margin:6px 0}</style>"
)


def changelog_section(changelog: str, version: str) -> str | None:
    """The body under `## [version] - date`, up to the next `## [`; None when there is none."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    return match.group(1).strip() if match else None


def _inline(text: str) -> str:
    """Escape, then the four marks the changelog uses: `code`, **bold**, *italic*, [text](url)."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return out


def notes_html(section: str) -> str:
    """CHANGELOG.md's subset of Markdown — `###` headings, `-` bullets with wrapped continuation
    lines, paragraphs — as HTML for Sparkle's notes pane. Nothing else is needed, and a parser
    dependency would be a second thing for the release job to install."""
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[list[str]] = []

    def flush() -> None:
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{_inline(' '.join(i))}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in section.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
        elif line.startswith("### "):
            flush()
            blocks.append(f"<h3>{_inline(line[4:].strip())}</h3>")
        elif re.match(r"^\s*[-*] ", line):
            if paragraph:
                flush()
            items.append([re.sub(r"^\s*[-*] ", "", line).strip()])
        elif items and raw[:1].isspace():
            items[-1].append(line.strip())
        else:
            if items:
                flush()
            paragraph.append(line.strip())
    flush()
    return _STYLE + "".join(blocks)


def set_notes(item: ET.Element, changelog: str) -> bool:
    """Give an item its version's notes and drop any notes link. False when the changelog has no
    section for it, which leaves the item as it was rather than blank."""
    version = item.findtext(f"{{{SPARKLE}}}shortVersionString") or ""
    section = changelog_section(changelog, version)
    if section is None:
        return False
    for link in item.findall(f"{{{SPARKLE}}}releaseNotesLink"):
        item.remove(link)
    description = item.find("description")
    if description is None:
        description = ET.Element("description")
        item.insert(2, description)
    description.text = notes_html(section)
    return True


def _empty_feed() -> ET.ElementTree:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Familiar Server"
    ET.SubElement(channel, "link").text = f"{REPO}/releases"
    ET.SubElement(channel, "description").text = "Updates to Familiar Server, the Mac form of the Familiar server."
    return ET.ElementTree(rss)


def add_release(feed: ET.ElementTree, *, tag: str, build: str, length: int, signature: str, date: str) -> None:
    version = tag.removeprefix("v")
    channel = feed.getroot().find("channel")
    assert channel is not None, "an appcast has a channel"
    for item in channel.findall("item"):
        if item.findtext(f"{{{SPARKLE}}}shortVersionString") == version:
            channel.remove(item)

    item = ET.Element("item")
    ET.SubElement(item, "title").text = f"Familiar Server {version}"
    ET.SubElement(item, "pubDate").text = date
    ET.SubElement(item, "link").text = f"{REPO}/releases/tag/{tag}"
    ET.SubElement(item, f"{{{SPARKLE}}}version").text = build
    ET.SubElement(item, f"{{{SPARKLE}}}shortVersionString").text = version
    ET.SubElement(item, f"{{{SPARKLE}}}minimumSystemVersion").text = MINIMUM_SYSTEM
    ET.SubElement(item, "enclosure", {
        "url": f"{REPO}/releases/download/{tag}/Familiar-Server-{version}.dmg",
        "length": str(length),
        "type": "application/octet-stream",
        f"{{{SPARKLE}}}edSignature": signature,
    })
    first_item = next((i for i, child in enumerate(channel) if child.tag == "item"), len(channel))
    channel.insert(first_item, item)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("appcast", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--build", help="the bundle's CFBundleVersion")
    parser.add_argument("--length", type=int)
    parser.add_argument("--signature")
    parser.add_argument("--notes", type=Path, help="CHANGELOG.md; every item gets its version's section")
    args = parser.parse_args(argv)
    adding = args.tag is not None
    if adding and not all([args.build, args.length, args.signature]):
        parser.error("--tag needs --build, --length and --signature")
    if adding and not args.tag.startswith("v"):
        parser.error(f"--tag is the release tag, v and all: {args.tag!r}")
    if not adding and args.notes is None:
        parser.error("give --tag to add a release, or --notes to refresh notes")

    feed = ET.parse(args.appcast) if args.appcast.exists() else _empty_feed()
    if adding:
        add_release(
            feed, tag=args.tag, build=args.build, length=args.length, signature=args.signature,
            date=email.utils.formatdate(usegmt=True),
        )
    if args.notes is not None:
        changelog = args.notes.read_text()
        channel = feed.getroot().find("channel")
        for item in channel.findall("item") if channel is not None else []:
            set_notes(item, changelog)
    ET.indent(feed, space="  ")
    feed.write(args.appcast, encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
