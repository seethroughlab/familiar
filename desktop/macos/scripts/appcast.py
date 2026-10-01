#!/usr/bin/env python3
"""Add a release to Familiar Server's Sparkle feed (ADR-0135 point 3), or replace its entry.

The feed lives on the `appcast` branch as appcast.xml; `publish-update.sh` checks it out, runs this,
and pushes. Replacing rather than appending makes a re-run of the same release harmless. Newest
first: Sparkle reads every item and picks the highest `sparkle:version`, which is the bundle's
CFBundleVersion (a build timestamp), so the order is for people reading the file.

usage: appcast.py <appcast.xml> --tag v0.2.0-beta9 --build 202610011200 --length 371246439 \\
                  --signature <edSignature>
"""

from __future__ import annotations

import argparse
import email.utils
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
REPO = "https://github.com/seethroughlab/familiar"
MINIMUM_SYSTEM = "14.0"  # LSMinimumSystemVersion in Support/Info.plist

ET.register_namespace("sparkle", SPARKLE)


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
    ET.SubElement(item, f"{{{SPARKLE}}}releaseNotesLink").text = f"{REPO}/releases/tag/{tag}"
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
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build", required=True, help="the bundle's CFBundleVersion")
    parser.add_argument("--length", required=True, type=int)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args(argv)
    if not args.tag.startswith("v"):
        parser.error(f"--tag is the release tag, v and all: {args.tag!r}")

    feed = ET.parse(args.appcast) if args.appcast.exists() else _empty_feed()
    add_release(
        feed, tag=args.tag, build=args.build, length=args.length, signature=args.signature,
        date=email.utils.formatdate(usegmt=True),
    )
    ET.indent(feed, space="  ")
    feed.write(args.appcast, encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
