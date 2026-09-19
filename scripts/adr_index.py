#!/usr/bin/env python3
"""Generate `docs/ADR-INDEX.md`: the decisions by subsystem and status (ADR-0127 point 6).

`docs/decisions/` holds only ADRs by convention, so the index lives beside it. It is generated so
it cannot drift: CI regenerates and fails on a diff (`--check`). Subsystems come from keyword
rules over each record's title, with `OVERRIDES` for the ones a title does not settle — edit those
when a record is misfiled, not the output.

Superseded and rejected records are listed last, under their own heading, so a reader looking for
current instructions does not meet them first (point 6).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "decisions"
OUT = ROOT / "docs" / "ADR-INDEX.md"

SUBSYSTEMS = [
    "Apple clients",
    "Playback",
    "Analysis and discovery",
    "API",
    "Web admin",
    "Visualizers",
    "Website",
    "Operations",
    "Security",
    "Process and documentation",
]

# Ordered: the first rule whose pattern matches the title (or filename) wins.
RULES: list[tuple[str, str]] = [
    (r"visuali[sz]er|visualizers", "Visualizers"),
    (r"apple|native|mac\b|macos|ios|iphone|phone|carplay|swift|live activity|xcode|app bundle|the apple client|composition root|repositories|tabs are home|download", "Apple clients"),
    (r"playback|queue|radio|shuffle|ambient|crossfade|effect|casting|output|audio engine|airplay|listening|music video|play events|stream|transcod|lossless|aac|remux|weighted", "Playback"),
    (r"analysis|analy[sz]ed|embedding|clap|feature|melodic|mood|fingerprint|recording|corpus|community cache|discover|suggest|similar|rank|map|new releases|bandcamp|acquire|soulseek|slskd|inbox|zero-touch|scan|sync|artwork|artist|album|canonical|duplicate|review|metadata|lyrics", "Analysis and discovery"),
    (r"\bapi\b|openapi|contract|alias|path|tag|generated|error|envelope|schema|mcp|llm|chat|tools", "API"),
    (r"website|site\b|install section|remote access|illustration", "Website"),
    (r"web app|admin|top bar|component tree|settings|dashboard|management surface|embed|player.s removal|pwa|browser", "Web admin"),
    (r"docker|backup|deploy|image|compose|runner|ci\b|test|database|dependenc|assembled|module boundar|lint|clapback|nas|s3|restore|transfer|export|import", "Operations"),
    (r"auth|token|security|inbound|login|credential", "Security"),
    (r"documentation|history|start-here|decision records|no caller", "Process and documentation"),
]

# Title keywords are not always enough; these are decided by hand, by number.
OVERRIDES: dict[int, str] = {
    11: "Apple clients",  # the library cached whole on the device
    12: "Apple clients",  # favourites as a collection in the native UI
    29: "Apple clients",  # listener preferences live on the device
    30: "Analysis and discovery",  # scrobbling: a Last.fm integration
    38: "Operations",  # the demo server
    41: "Playback",  # the playhead
    53: "API",  # the command channel observes the interface
    57: "Web admin",  # what the web app keeps
    62: "Apple clients",  # the music map is a Mac surface
    74: "API",  # the queue tag
    75: "API",  # the command channel is not playback
    76: "API",  # server operations are one surface
    82: "Web admin",  # colour tokens and the theme class
    89: "Visualizers",  # the app bundle seeds the visualizer folder
    98: "API",  # the Mac app as the MCP stdio bridge
    100: "Apple clients",  # connecting an account in the listener's app
    101: "Analysis and discovery",
    104: "Analysis and discovery",  # whole-track embeddings by chunked mean
    108: "Analysis and discovery",  # a contribution names its installation
    110: "Playback",  # loudness levels
    112: "Operations",  # the server's file-response ceiling
    117: "Analysis and discovery",  # a Soulseek download is a pending-review track
}


def parse(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"ADR-(\d{4})-", path.name)
    number = int(m.group(1)) if m else 0
    title = next((l[2:].strip() for l in text.split("\n") if l.startswith("# ")), path.stem)
    title = re.sub(r"^ADR-\d{4}:\s*", "", title)
    status_line = next((l for l in text.split("\n") if l.startswith("Status:")), "Status: unknown")
    raw = status_line[len("Status:"):].strip()
    lowered = raw.lower()
    if lowered.startswith("superseded"):
        status = "superseded"
    elif lowered.startswith("rejected"):
        status = "rejected"
    elif lowered.startswith("accepted"):
        status = "accepted"
    elif lowered.startswith("proposed"):
        status = "proposed"
    else:
        status = "unknown"
    # An accepted record with a point superseded elsewhere: keep it current, carry the note.
    note = ""
    if status == "accepted" and "—" in raw:
        note = raw.split("—", 1)[1].strip().rstrip(".")
    date = next((l[len("Date:"):].strip() for l in text.split("\n") if l.startswith("Date:")), "")
    return {"number": number, "title": title, "status": status, "note": note, "date": date, "file": path.name}


def classify(record: dict) -> str:
    if record["number"] in OVERRIDES:
        return OVERRIDES[record["number"]]
    haystack = record["title"].lower()
    for pattern, subsystem in RULES:
        if re.search(pattern, haystack):
            return subsystem
    return "Operations"


def render(records: list[dict]) -> str:
    current = [r for r in records if r["status"] in ("accepted", "proposed")]
    retired = [r for r in records if r["status"] not in ("accepted", "proposed")]
    by_subsystem: dict[str, list[dict]] = defaultdict(list)
    for r in current:
        by_subsystem[classify(r)].append(r)

    lines = [
        "# ADR index",
        "",
        "Generated by `scripts/adr_index.py` from the records in `docs/decisions/` — do not edit; run",
        "`make adr-index` after adding or changing one, and CI fails on a stale copy (ADR-0127 point 6).",
        "",
        f"{len(current)} current records ({sum(1 for r in current if r['status'] == 'accepted')} accepted,",
        f"{sum(1 for r in current if r['status'] == 'proposed')} proposed), {len(retired)} retired. A record whose"
        " status carries a note has had a point superseded by a later one; the note says which.",
        "",
    ]
    for subsystem in SUBSYSTEMS:
        rs = sorted(by_subsystem.get(subsystem, []), key=lambda r: r["number"])
        if not rs:
            continue
        lines += [f"## {subsystem}", "", "| ADR | Title | Status |", "|---|---|---|"]
        for r in rs:
            status = r["status"] + (f" — {r['note']}" if r["note"] else "")
            lines.append(f"| [{r['number']:04d}](decisions/{r['file']}) | {r['title']} | {status} |")
        lines.append("")
    if retired:
        lines += ["## Superseded and rejected", "", "Kept for the record; not current instructions.", "", "| ADR | Title | Status |", "|---|---|---|"]
        for r in sorted(retired, key=lambda r: r["number"]):
            lines.append(f"| [{r['number']:04d}](decisions/{r['file']}) | {r['title']} | {r['status']} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    records = [parse(p) for p in sorted(DECISIONS.glob("ADR-*.md"))]
    text = render(records)
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(ROOT)} is stale — run: make adr-index")
            return 1
        print(f"{OUT.relative_to(ROOT)} is current ({len(records)} records).")
        return 0
    OUT.write_text(text)
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(records)} records).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
