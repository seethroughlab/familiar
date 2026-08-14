#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""Cut the background off a generated mark and write a transparent PNG.

Gemini returns **JPEG**, and JPEG has no alpha channel. Asked for a transparent
background it therefore does the only thing the format allows: it *draws* the grey
checkerboard, because that is the visual signifier of transparency it has seen. Those
squares are real pixels. No amount of prompting removes them — see ILLUSTRATIONS.md,
which now asks for a flat cyan background instead.

This script handles both, picking the mode from the image itself:

  solid        the border is one flat colour (cyan, or the white Gemini sometimes
               returns anyway). Every pixel near that colour is background.

  checkerboard the border alternates two tones. Matching on colour alone is not
               enough: in some images the checkerboard's light square lands on 253-255
               while the artwork's own off-white is 250, and JPEG will not hold a
               5-value gap.

               What separates them is that only ONE of the two tones is ambiguous. The
               darker square is a mid-grey, and no mark uses mid-grey — so every dark
               pixel is certainly background. A light pixel is background only when it
               is **connected** to a dark one through same-coloured pixels. The
               checkerboard is one such region; the key's off-white body is not,
               because its violet outline breaks the path. Enclosed holes still go —
               the gap between the crow's legs has dark squares of its own.

Both modes key on colour rather than flood-filling from the corners, which matters for
holes: the gap between the crow's legs is background, fully enclosed by the bird, and a
corner fill can never reach it.

Usage:
    python3 extract-marks.py --out ../assets/marks cat=IMG_1234.jpeg crow=IMG_5678.jpeg
    python3 extract-marks.py --out ../assets/marks IMG_1234.jpeg          # keeps stem
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

# How close a pixel must be to a background tone to count as background. Generous,
# because JPEG smears flat colour, and the palette leaves room: the nearest artwork
# colour to cyan is the green accent, ~174 away in RGB.
TOLERANCE = 30



# Two checkerboard tones sit about 55-70 apart in RGB; JPEG noise within one tone is a
# couple of values. Anything closer than this is the same tone and gets merged.
SAME_TONE = 40


def _border_tones(a: np.ndarray) -> list[tuple[int, int, int]]:
    """The one or two colours the frame edge is made of.

    Clustered rather than quantised. Quantising splits a single tone whenever it
    straddles a bucket edge — 239 and 240 are the same grey and land 16 apart — which
    then forces a merge threshold so wide it eats the genuine second tone as well.
    """
    edge = np.concatenate([
        a[:8].reshape(-1, 3), a[-8:].reshape(-1, 3),
        a[:, :8].reshape(-1, 3), a[:, -8:].reshape(-1, 3),
    ])
    counts = Counter(map(tuple, edge))

    clusters: list[tuple[np.ndarray, int]] = []
    for colour, n in counts.most_common(64):
        c = np.array(colour, dtype=int)
        for i, (centre, weight) in enumerate(clusters):
            if np.linalg.norm(c - centre) <= SAME_TONE:
                clusters[i] = ((centre * weight + c * n) / (weight + n), weight + n)
                break
        else:
            clusters.append((c.astype(float), n))

    clusters.sort(key=lambda cw: -cw[1])
    total = sum(w for _, w in clusters)
    # A tone that is barely present on the edge is noise, not part of the background.
    return [tuple(int(round(v)) for v in centre)
            for centre, weight in clusters[:2] if weight > total * 0.15]


def _near(a: np.ndarray, tone: tuple[int, int, int], tol: int = TOLERANCE) -> np.ndarray:
    return np.linalg.norm(a - np.array(tone, dtype=int), axis=2) <= tol


def background_mask(a: np.ndarray) -> tuple[np.ndarray, str]:
    tones = _border_tones(a)
    if not tones:
        return np.zeros(a.shape[:2], dtype=bool), "none"

    if len(tones) == 1:
        return _near(a, tones[0]), f"solid rgb{tones[0]}"

    dark, light = sorted(tones, key=sum)
    tone_pixels = _near(a, dark) | _near(a, light)

    # Keep only the regions a certainly-background dark pixel can reach.
    labels, _ = ndimage.label(tone_pixels)
    reached = np.unique(labels[_near(a, dark)])
    keep = np.isin(labels, reached[reached != 0])
    return keep, f"checkerboard rgb{dark}/rgb{light}"


def extract(src: Path, dst: Path, size: int, colours: int) -> str:
    a = np.asarray(Image.open(src).convert("RGB")).astype(int)
    bg, mode = background_mask(a)

    # Grow the background by a pixel before cutting. Anti-aliased edge pixels are a
    # blend of mark and background and match neither tone, so they read as subject and
    # would leave a bright fringe — which on a near-black page is exactly the halo
    # everyone recognises as a bad cut-out. Losing a hair of outline is the better trade.
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    alpha = np.asarray(Image.fromarray(alpha).filter(ImageFilter.MinFilter(5)))

    # Drop specks. JPEG leaves the odd pixel that matches nothing, and one stray dot in
    # the corner of an otherwise clean mark survives the crop and moves the bounding box.
    labels, count = ndimage.label(alpha > 0)
    if count:
        areas = ndimage.sum_labels(np.ones_like(labels), labels, range(1, count + 1))
        too_small = (np.arange(1, count + 1))[areas < alpha.size * 1e-4]
        alpha = np.where(np.isin(labels, too_small), 0, alpha).astype(np.uint8)

    out = Image.fromarray(np.dstack([a.astype(np.uint8), alpha]), mode="RGBA")
    out = out.crop(out.getbbox())
    out.thumbnail((size, size), Image.LANCZOS)

    # Quantise. These are flat-colour illustrations, but they arrive as JPEG, and the
    # mottling JPEG leaves inside a "flat" fill is what stops PNG compressing it — 167 KB
    # for a mark that is really five colours. Snapping to a small palette both restores
    # the flatness the art was drawn with and takes it to about 10 KB.
    out = out.quantize(colors=colours, method=Image.FASTOCTREE, dither=Image.Dither.NONE)

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, optimize=True)
    kept = alpha.mean() / 255 * 100
    kb = dst.stat().st_size / 1024
    return f"{dst.name:<20} {mode:<44} {out.width}x{out.height}  {kept:>2.0f}% opaque  {kb:>5.0f} KB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="path, or name=path to rename the output")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--colours", type=int, default=16, help="palette size (default 16)")
    args = ap.parse_args()

    for item in args.images:
        name, _, path = item.rpartition("=")
        src = Path(path)
        if not src.exists():
            print(f"missing: {src}", file=sys.stderr)
            return 1
        print(extract(src, args.out / f"{name or src.stem}.png", args.size, args.colours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
