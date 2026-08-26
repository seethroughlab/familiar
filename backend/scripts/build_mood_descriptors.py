#!/usr/bin/env python
"""Regenerate `app/services/data/mood_descriptors.npz` (ADR-0093 point 7).

The 48 descriptor vectors are a pure function of `mood_tags.DESCRIPTORS` and the CLAP text encoder,
so they are computed once and committed rather than recomputed at runtime. Run this when either
changes — nothing runs it automatically, because nothing should: a request path that can rebuild
this file is a request path that can load a 1.5 GB model.

Needs CLAP, so run it where analysis runs:

    docker exec familiar-api python /app/scripts/build_mood_descriptors.py

then copy the file out and commit it. The script refuses to write a file that does not match
`DESCRIPTORS`, because order is the contract — `compute_mood_tags` indexes `DESCRIPTORS` by the
winning row, so drifted rows return confident, wrong words.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis import extract_text_embedding  # noqa: E402
from app.services.mood_tags import DESCRIPTORS  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "services" / "data" / "mood_descriptors.npz"


def main() -> int:
    embeddings = []
    for descriptor in DESCRIPTORS:
        vector = extract_text_embedding(descriptor["description"])
        if vector is None:
            print(f"CLAP returned nothing for {descriptor['tag']!r}; aborting", file=sys.stderr)
            return 1
        embeddings.append([float(x) for x in vector])

    matrix = np.array(embeddings, dtype=np.float32)
    tags = np.array([d["tag"] for d in DESCRIPTORS])
    if matrix.shape[0] != len(DESCRIPTORS):
        print("row count does not match DESCRIPTORS; aborting", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, tags=tags, embeddings=matrix)
    print(f"wrote {OUT} — {matrix.shape[0]} descriptors, dim {matrix.shape[1]}, "
          f"{OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
