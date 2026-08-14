#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""Cut the background off a generated illustration and write a transparent PNG.

Gemini returns **JPEG**, and JPEG has no alpha channel. Asked for a transparent
background it therefore does the only thing the format allows: it *draws* the grey
checkerboard, because that is the visual signifier of transparency it has seen. Those
squares are real pixels, and no amount of prompting removes them. So the prompts ask for
a background this can key instead — see ILLUSTRATIONS.md.

The mode is chosen from the image itself:

  black ground  the current register: light ink on pure black. Exact, and the reason to
                prefer it. Over black the observed pixel is the ink premultiplied by its
                own coverage, so coverage is just how bright it got, and dividing that
                back out recovers the ink. A one-pixel hatch line keeps correct partial
                alpha instead of being cut or eroded.

  solid         the border is one flat colour. Every pixel near that colour is
                background; edges are matted by distance from it and the background's
                colour divided back out, so a soft edge does not become a pale halo.

  checkerboard  the border alternates two tones. Colour alone is not enough: in some
                images the checkerboard's light square lands on 253-255 while the
                artwork's own off-white is 250, and JPEG will not hold a 5-value gap.
                What separates them is that only ONE tone is ambiguous — the dark square
                is a mid-grey no artwork uses — so every dark pixel is certainly
                background, and a light pixel is background only when connected to a
                dark one. Enclosed holes still go: the gap between a crow's legs has
                dark squares of its own, and no flood fill from a corner ever reaches it.

`--split RxC` carves a model sheet into its poses, cutting at the emptiest rows and
columns. That is how the recurring characters stay consistent: four poses drawn in one
generation agree with each other by construction, where four separate generations do not.

Usage:
    extract-marks.py --out ../assets/marks --split 2x2 cat=IMG_1234.jpeg   # -> cat-1..4
    extract-marks.py --out ../assets/marks crow=IMG_5678.jpeg
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


def extract(src: Path, dst: Path, size: int, colours: int, grid: tuple[int, int]) -> str:
    a = np.asarray(Image.open(src).convert("RGB")).astype(int)

    tones = _border_tones(a)
    if tones and max(tones[0]) < 40:
        ink, alpha = luma_matte(a)
        return _emit(ink, alpha, dst, size, colours, f"black ground rgb{tones[0]}", grid)

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

    return _emit(a, alpha / 255.0, dst, size, colours, mode, grid)


def _emit(a: np.ndarray, alpha: np.ndarray, dst: Path, size: int, colours: int,
          mode: str, grid: tuple[int, int]) -> str:
    """One mark, or a model sheet carved into its poses."""
    rows, cols = grid
    if rows * cols <= 1:
        return _write(a, alpha, dst, size, colours, mode)

    lines = []
    for i, (sub_a, sub_alpha) in enumerate(split_sheet(a, alpha, rows, cols), start=1):
        if sub_alpha.max() < 0.05:
            continue
        part = dst.with_name(f"{dst.stem}-{i}{dst.suffix}")
        lines.append(_write(sub_a, sub_alpha, part, size, colours, f"{mode} [{i}/{rows*cols}]"))
    return "\n".join(lines)


def _cluster_1d(values: np.ndarray, weights: np.ndarray, k: int) -> np.ndarray:
    """Assign each value to one of k groups along a single axis."""
    if k < 2:
        return np.zeros(len(values), dtype=int)
    centres = np.quantile(values, np.linspace(0, 1, k * 2 + 1)[1::2])
    for _ in range(32):
        which = np.argmin(np.abs(values[:, None] - centres[None, :]), axis=1)
        moved = centres.copy()
        for i in range(k):
            sel = which == i
            if sel.any():
                moved[i] = np.average(values[sel], weights=weights[sel])
        if np.allclose(moved, centres):
            break
        centres = moved
    # Relabel so group 0 is topmost/leftmost, giving reading order.
    return np.argsort(np.argsort(centres))[np.argmin(np.abs(values[:, None] - centres[None, :]), axis=1)]


def split_sheet(a: np.ndarray, alpha: np.ndarray, rows: int, cols: int):
    """Carve a model sheet into its individual poses, in reading order.

    Groups the drawing's connected parts by where their centres of mass fall, rather than
    cutting the frame at empty rows and columns. The obvious projection method fails on a
    real sheet: on the cat sheet there is no empty row anywhere, because the walking cat's
    tail and the stretching cat's tail both cross the horizontal middle. Nothing is wrong
    with that drawing — poses simply are not boxed — so it split into two columns and left
    two cats in each.

    Centres of mass separate cleanly even when the poses' extents overlap, and a pose made
    of several pieces (a detached whisker, a floating note) still lands with the piece it
    belongs to, because each piece joins the nearest group.
    """
    labels, count = ndimage.label(alpha > 0.05)
    if not count:
        return
    areas = ndimage.sum_labels(alpha, labels, range(1, count + 1))
    keep = np.arange(1, count + 1)[areas > areas.max() * 0.001]
    if not len(keep):
        return

    centres = np.array(ndimage.center_of_mass(alpha, labels, keep))
    mass = areas[keep - 1]
    row_of = _cluster_1d(centres[:, 0], mass, rows)
    col_of = _cluster_1d(centres[:, 1], mass, cols)

    for r in range(rows):
        for c in range(cols):
            members = keep[(row_of == r) & (col_of == c)]
            if not len(members):
                continue
            cell = np.isin(labels, members)
            ys, xs = np.where(cell)
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            # Zero anything from a neighbouring pose that reaches into this bounding box.
            masked = np.where(cell[y0:y1, x0:x1], alpha[y0:y1, x0:x1], 0)
            yield a[y0:y1, x0:x1], masked


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
    # WebP lossless. The hatching lives in the alpha channel, and an 8-bit alpha full of
    # fine cross-hatch is close to incompressible in PNG — half a megabyte for one mark.
    # Lossy WebP does not help either, because it stores alpha losslessly regardless; only
    # WebP's lossless mode, which has a real alpha codec, does, at roughly half the size.
    if dst.suffix == ".webp":
        out.save(dst, lossless=True, method=6)
    else:
        out.save(dst, optimize=True)
    kept = alpha.mean() / 255 * 100
    kb = dst.stat().st_size / 1024
    return f"{dst.name:<20} {mode:<44} {out.width}x{out.height}  {kept:>2.0f}% opaque  {kb:>5.0f} KB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="path, or name=path to rename the output")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--colours", type=int, default=16, help="palette size (default 16)")
    ap.add_argument("--ext", default="webp", choices=("webp", "png"))
    ap.add_argument("--split", default="1x1", metavar="RxC",
                    help="carve a model sheet into poses, e.g. 2x2 (default 1x1)")
    args = ap.parse_args()

    for item in args.images:
        name, _, path = item.rpartition("=")
        src = Path(path)
        if not src.exists():
            print(f"missing: {src}", file=sys.stderr)
            return 1
        rows, cols = (int(v) for v in args.split.lower().split("x"))
        print(extract(src, args.out / f"{name or src.stem}.{args.ext}", args.size, args.colours,
                      (rows, cols)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
