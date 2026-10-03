"""appcast.py's release notes: the changelog section, as HTML, in the item — not a link.

Run with `python3 scripts/test_appcast.py`; CI runs it in the Familiar Server job. Standard library
only, like the script.
"""

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import appcast  # noqa: E402

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0-beta15] - 2026-10-03

No migrations; the API contract stays at v1.

### Music videos

- **Searching for a video answers in about two seconds**, not ten or more. Each result was
  fully extracted; measured on the NAS: 9.2 s before, 2.1 s after.
- See [ADR-0148](docs/decisions/ADR-0148.md) and `releases/latest`.

## [0.2.0-beta14] - 2026-10-03

Older.
"""

S = appcast.SPARKLE


def feed_with(version: str, *, link: bool) -> ET.ElementTree:
    feed = appcast._empty_feed()
    channel = feed.getroot().find("channel")
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"Familiar Server {version}"
    ET.SubElement(item, "pubDate").text = "x"
    ET.SubElement(item, f"{{{S}}}shortVersionString").text = version
    if link:
        ET.SubElement(item, f"{{{S}}}releaseNotesLink").text = "https://github.com/x/releases/tag/v1"
    return feed


class ReleaseNotes(unittest.TestCase):
    def test_takes_only_its_own_section(self):
        section = appcast.changelog_section(CHANGELOG, "0.2.0-beta15")
        self.assertIn("Searching for a video", section)
        self.assertNotIn("Older.", section)
        self.assertIsNone(appcast.changelog_section(CHANGELOG, "9.9.9"))

    def test_markdown_becomes_the_html_the_pane_renders(self):
        body = appcast.notes_html(appcast.changelog_section(CHANGELOG, "0.2.0-beta15"))
        self.assertIn("<h3>Music videos</h3>", body)
        self.assertIn("<strong>Searching for a video answers in about two seconds</strong>", body)
        # A wrapped bullet is one item, not an item and a stray paragraph.
        self.assertIn("Each result was fully extracted; measured on the NAS", body)
        self.assertEqual(body.count("<li>"), 2)
        self.assertIn('<a href="docs/decisions/ADR-0148.md">ADR-0148</a>', body)
        self.assertIn("<code>releases/latest</code>", body)
        self.assertIn("<p>No migrations; the API contract stays at v1.</p>", body)

    def test_an_item_gets_notes_and_loses_the_link(self):
        # The link is the bug: Sparkle loaded the whole GitHub page into the notes pane.
        feed = feed_with("0.2.0-beta15", link=True)
        item = feed.getroot().find("channel/item")
        self.assertTrue(appcast.set_notes(item, CHANGELOG))
        self.assertIsNone(item.find(f"{{{S}}}releaseNotesLink"))
        self.assertIn("<h3>Music videos</h3>", item.findtext("description"))

    def test_a_version_the_changelog_lacks_is_left_alone(self):
        feed = feed_with("0.1.0", link=True)
        item = feed.getroot().find("channel/item")
        self.assertFalse(appcast.set_notes(item, CHANGELOG))
        self.assertIsNotNone(item.find(f"{{{S}}}releaseNotesLink"))

    def test_a_new_release_carries_notes_and_no_link(self):
        feed = appcast._empty_feed()
        appcast.add_release(feed, tag="v0.2.0-beta15", build="1", length=2, signature="s", date="d")
        item = feed.getroot().find("channel/item")
        self.assertIsNone(item.find(f"{{{S}}}releaseNotesLink"))
        appcast.set_notes(item, CHANGELOG)
        # Survives being written and read back, which is what Sparkle does with it.
        again = ET.fromstring(ET.tostring(feed.getroot()))
        self.assertIn("<strong>", again.find("channel/item/description").text)

    def test_refresh_mode_rewrites_a_feed_in_place(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "appcast.xml"
            feed_with("0.2.0-beta14", link=True).write(path, encoding="utf-8", xml_declaration=True)
            notes = Path(d) / "CHANGELOG.md"
            notes.write_text(CHANGELOG)
            self.assertEqual(appcast.main([str(path), "--notes", str(notes)]), 0)
            item = ET.parse(path).getroot().find("channel/item")
            self.assertIsNone(item.find(f"{{{S}}}releaseNotesLink"))
            self.assertIn("Older.", item.findtext("description"))


if __name__ == "__main__":
    unittest.main()
