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


def luma_matte(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Alpha and colour for artwork drawn light-on-black.

    Exact, unlike anything that has to guess where a subject ends. Over a black ground
    the observed pixel *is* the colour premultiplied by its own coverage, so coverage is
    just how bright it got — and dividing that back out recovers the ink. Anti-aliased
    edges and fine crosshatch come out with correct partial alpha rather than being cut
    or eroded, which is the whole reason a hatched style can survive the trip at all.

    The dark inside a shape becomes transparent, and that is right: in this register the
    darkness is the ground, so it should show the page rather than carry its own black.

    Coverage is taken from the brightest channel rather than luminance, because luminance
    weights green at 71% and blue at 7% — on a violet-and-magenta set that would matte the
    blues almost away.
    """
    alpha = a.max(axis=2) / 255.0
    with np.errstate(divide="ignore", invalid="ignore"):
        ink = a / np.maximum(alpha, 1e-6)[..., None]
    return np.clip(ink, 0, 255), alpha


def extract(src: Path, dst: Path, size: int, colours: int) -> str:
    a = np.asarray(Image.open(src).convert("RGB")).astype(int)

    tones = _border_tones(a)
    if tones and max(tones[0]) < 40:
        return _write(*luma_matte(a), dst, size, colours, f"black ground rgb{tones[0]}")

    bg, mode = background_mask(a)

    # Matte the edge rather than cutting it.
    #
    # An anti-aliased edge pixel is a genuine mixture of mark and background, and the
    # honest answer for it is partial alpha. The first version instead cut hard and then
    # eroded a couple of pixels to hide the bright fringe that left — which costs a thick
    # outline nothing and destroys a thin one. Measured, it removed 17% of the
    # constellation's artwork. Any style with a finer line loses more.
    #
    # Alpha ramps over the width of the anti-aliasing, and then the background's own
    # colour is divided back out: an edge pixel that is half violet and half white page
    # is stored as violet at 50%, not as a pale mauve that glows against a dark page.
    # Without that second step a soft edge is just a halo with extra steps.
    dist = np.min([np.linalg.norm(a - np.array(t), axis=2) for t in _border_tones(a)], axis=0)
    alpha = np.clip((dist - TOLERANCE) / TOLERANCE, 0, 1)
    alpha[bg] = 0

    bg_colour = np.array(_border_tones(a)[0], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        unmixed = (a - (1 - alpha)[..., None] * bg_colour) / np.maximum(alpha, 1e-6)[..., None]
    a = np.where((alpha > 0)[..., None], np.clip(unmixed, 0, 255), a)
    alpha = (alpha * 255).astype(np.uint8)

    return _write(a, alpha / 255.0, dst, size, colours, mode)


def _write(a: np.ndarray, alpha: np.ndarray, dst: Path, size: int, colours: int,
           mode: str) -> str:
    # Drop specks. JPEG leaves the odd pixel that matches nothing, and one stray dot in
    # the corner of an otherwise clean mark survives the crop and moves the bounding box.
    labels, count = ndimage.label(alpha > 0.05)
    if count:
        areas = ndimage.sum_labels(np.ones_like(labels), labels, range(1, count + 1))
        too_small = (np.arange(1, count + 1))[areas < alpha.size * 1e-4]
        alpha = np.where(np.isin(labels, too_small), 0, alpha)

    alpha = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([a.astype(np.uint8), alpha]), mode="RGBA")
    out = out.crop(out.getbbox())
    out.thumbnail((size, size), Image.LANCZOS)

    # Quantise the colour, keep the alpha at full depth.
    #
    # These are flat-colour illustrations, but they arrive as JPEG, and the mottling JPEG
    # leaves inside a "flat" fill is what stops PNG compressing it — 167 KB for a mark
    # that is really five colours. A palette PNG would be smaller still, but palette
    # transparency is one bit, which would throw away the matted edge. So the colours
    # collapse and the alpha channel survives intact.
    rgb, a8 = out.convert("RGB"), out.getchannel("A")
    rgb = rgb.quantize(colors=colours, method=Image.FASTOCTREE,
                       dither=Image.Dither.NONE).convert("RGB")
    out = Image.merge("RGBA", (*rgb.split(), a8))

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
