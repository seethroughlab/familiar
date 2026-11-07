#!/usr/bin/env python
"""Measure how often the lyrics service finds lyrics, on a fixed sample of a real library.

Calls `LyricsService` directly. Persistence lives in the route, so nothing is written to the
library. It exists because today's service answers every failure with `None`: read from the outside,
an LRCLIB outage and a low hit rate are the same number. So every request goes through a recording
transport, and a run with transient failures says so before it says anything else.

The sample is a CSV (id, title, artist, album, album_artist, duration_seconds), taken once and
reused so that a before and an after are the same tracks. It lists a private library, and so does
the output: keep both out of git. Taken from the server with:

    COPY (SELECT id, title, artist, album, album_artist, duration_seconds FROM tracks
          ORDER BY md5(id::text || '<seed>') LIMIT 400) TO STDOUT WITH (FORMAT csv, HEADER true)

**A uniform sample, deliberately.** Splitting vocal from instrumental on
`TrackAnalysis.instrumentalness` is not possible: on the maintainer's library its 10th, 50th and
90th percentiles are all 1.0.

    uv run python scripts/measure_lyrics.py sample.csv --out baseline.csv
"""

import argparse
import asyncio
import csv
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

USER_AGENT = "Familiar/lyrics-measure (https://github.com/seethroughlab/familiar)"

#: LRCLIB allows about 90 a minute to an identified client; this stays well under it.
MIN_INTERVAL_SECONDS = 1.0


@dataclass
class Exchange:
    """One request, as it actually went: the thing the service does not report."""

    path: str
    status: int | None
    retry_after: float | None = None
    error: str | None = None
    body: str | None = None

    @property
    def transient(self) -> bool:
        """Says nothing about the track. A 404 is an answer; these are not."""
        return self.status is None or self.status == 429 or self.status >= 500


@dataclass
class RecordingTransport(httpx.AsyncBaseTransport):
    """Paces requests, and writes down what each one did before the service can discard it."""

    inner: httpx.AsyncBaseTransport
    min_interval: float = MIN_INTERVAL_SECONDS
    exchanges: list[Exchange] = field(default_factory=list)
    _last_sent: float = 0.0
    _hold_until: float = 0.0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        wait = max(self._last_sent + self.min_interval, self._hold_until) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_sent = time.monotonic()

        try:
            response = await self.inner.handle_async_request(request)
        except httpx.TransportError as exc:
            self.exchanges.append(
                Exchange(request.url.path, None, error=type(exc).__name__)
            )
            raise

        await response.aread()
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        if retry_after is not None:
            self._hold_until = time.monotonic() + retry_after
        self.exchanges.append(
            Exchange(request.url.path, response.status_code, retry_after, body=response.text)
        )
        return response

    def take(self) -> list[Exchange]:
        taken, self.exchanges = self.exchanges, []
        return taken


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def classify(has_lines: bool, synced: bool, exchanges: Sequence[Exchange]) -> str:
    """What one track's lookup amounts to.

    A hit stands even if an earlier call failed. A miss with any transient failure behind it is
    `transient`, not `miss`, because nobody got an answer about that track.
    """
    if has_lines:
        return "synced" if synced else "plain"
    if any(exchange.transient for exchange in exchanges):
        return "transient"
    return "miss"


def summarize(outcomes: Sequence[str]) -> dict[str, float]:
    counts = Counter(outcomes)
    total = len(outcomes) or 1
    return {
        "tracks": len(outcomes),
        "synced": counts["synced"],
        "plain": counts["plain"],
        "miss": counts["miss"],
        "transient": counts["transient"],
        "skipped": counts["skipped"],
        "synced_rate": round(counts["synced"] / total, 3),
        "valid": counts["transient"] / total < 0.01,
    }


async def run(sample: Path, out: Path) -> dict[str, float]:
    from app.services.lyrics import LyricsService

    transport = RecordingTransport(httpx.AsyncHTTPTransport())
    service = LyricsService()
    await service.client.aclose()
    service.client = httpx.AsyncClient(
        transport=transport, timeout=10.0, headers={"User-Agent": USER_AGENT}
    )

    with sample.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    outcomes: list[str] = []
    raw_path = out.with_suffix(".raw.jsonl")
    with out.open("w", newline="") as result_file, raw_path.open("w") as raw_file:
        writer = csv.writer(result_file)
        writer.writerow(
            ["id", "artist", "title", "album", "duration", "outcome", "lines", "calls", "statuses",
             "first_line"]
        )
        for index, row in enumerate(rows, 1):
            # The route's own guard: without both it never asks.
            if not row["title"] or not row["artist"]:
                outcomes.append("skipped")
                writer.writerow([row["id"], row["artist"], row["title"], row["album"],
                                 row["duration_seconds"], "skipped", 0, 0, "", ""])
                continue

            duration = float(row["duration_seconds"]) if row["duration_seconds"] else None
            result = await service.search(
                track_name=row["title"],
                artist_name=row["artist"],
                album_name=row["album"] or None,
                duration=duration,
            )
            exchanges = transport.take()
            has_lines = bool(result and result.lines)
            outcome = classify(has_lines, bool(result and result.synced), exchanges)
            outcomes.append(outcome)

            writer.writerow([
                row["id"], row["artist"], row["title"], row["album"], row["duration_seconds"],
                outcome, len(result.lines) if result else 0, len(exchanges),
                " ".join(f"{e.path.rsplit('/', 1)[-1]}:{e.status or e.error}" for e in exchanges),
                result.lines[0].text if has_lines and result else "",
            ])
            raw_file.write(json.dumps({
                "id": row["id"],
                "exchanges": [e.__dict__ for e in exchanges],
            }) + "\n")
            if index % 25 == 0:
                print(f"{index}/{len(rows)} {dict(Counter(outcomes))}", flush=True)

    await service.close()
    return summarize(outcomes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sample", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    summary = asyncio.run(run(args.sample, args.out))
    print(json.dumps(summary, indent=2))
    if not summary["valid"]:
        print("INVALID RUN: 1% or more of tracks hit a transient failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
