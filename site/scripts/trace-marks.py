#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy", "scipy", "vtracer"]
# ///
"""Trace a generated mark to SVG, normalising its outline weight on the way.

`extract-marks.py` cuts a transparent PNG out of the JPEG. This does the same job in
vector, and is the better tool for two reasons the raster version cannot fix:

**Thin outlines survive.** The raster cut has to erode the alpha by a couple of pixels
to avoid leaving a bright fringe on a dark page. That is harmless on a 30px outline and
fatal on a 10px one — it removed 17% of the constellation's artwork, whose connecting
lines are the thinnest in the set. A tracer follows colour regions instead, so a thin
stroke becomes a path rather than a casualty.

**Line weight becomes adjustable.** The set was generated a prompt at a time and its
outlines range from 10px to 54px against a median of 30. Here the violet band is grown
or shrunk to a single target before tracing, so the marks read as one set.

Colour is deliberately left alone apart from the two structural colours. Snapping every
pixel to the site palette turned the cat's pale green eyes rose — pale green sits nearer
`#c07f8a` than `#22c55e` in RGB — so only the violet outline and the near-black fill are
unified, and the accents stay as drawn.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image, ImageFilter
from scipy import ndimage

# Imported by path because the sibling's filename is hyphenated and so is not a module
# name. Worth the awkwardness: background detection is subtle and belongs in one place.
_spec = importlib.util.spec_from_file_location(
    "extract_marks", Path(__file__).parent / "extract-marks.py")
_em = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_em)

VIOLET = (0xA8, 0x55, 0xF7)
# The marks fill with a lifted, faintly violet black — measured across the set at
# #0f0e14 — and NOT with the page's own #0a0a0a. Unifying them to the page colour was
# tried and made the cat, the crow and the two cats read as hollow outlines, because
# their bodies became exactly the surface behind them.
MARK_BLACK = (0x0F, 0x0E, 0x14)
# Not in the artwork, so any path left carrying it is background and gets dropped.
SENTINEL = (0xFF, 0x00, 0xFF)

# How far from canonical violet a pixel can sit and still be outline. The set's violets
# drift from #8f37d4 to #b669e3, which is most of this budget.
VIOLET_RADIUS = 90

# Snap radii for the two structural colours, and they are deliberately different.
# Violet can be generous — nothing else in the set is purple — and needs to be, since the
# marks' own violets drift from #8f37d4 to #b669e3. Black must be tight: at 60 it reached
# far enough to swallow the shaded end of the cat-ear's rose gradient, which came out as
# black speckles scattered through the fill.
# Pixels of anti-aliased ramp to eat off the silhouette, at the source's own resolution.
HALO = 3

VIOLET_SNAP = 70
BLACK_SNAP = 30


def _shrink(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Carry a full-resolution mask down to the traced resolution."""
    if mask.shape == shape:
        return mask
    small = Image.fromarray((mask * 255).astype(np.uint8)).resize(
        (shape[1], shape[0]), Image.BOX)
    return np.asarray(small) > 127


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def outline_width(violet: np.ndarray) -> float:
    """The dominant width of the violet band, in pixels.

    Measured off the ridge of a distance transform — the centreline of each band, where
    the distance to the nearest non-violet pixel is half the local width. The *mode*
    rather than a percentile, because several marks fill a shape with violet as well as
    outlining with it (the orb's stand, the eye's iris), and a high percentile measures
    those blobs instead of the strokes.
    """
    dist = ndimage.distance_transform_edt(violet)
    ridge = violet & (dist >= ndimage.maximum_filter(dist, size=5) - 1e-6) & (dist > 1.5)
    widths = 2 * dist[ridge]
    if widths.size < 50:
        return 0.0
    hist, edges = np.histogram(widths, bins=np.arange(0, 200, 4))
    return float(edges[hist.argmax()] + 2)


def set_outline_width(a: np.ndarray, violet: np.ndarray, target: float) -> np.ndarray:
    current = outline_width(violet)
    if not current or abs(target - current) < 2:
        return a
    delta = int(round(abs(target - current) / 2))
    if delta < 1:
        return a

    if target > current:
        grown = ndimage.binary_dilation(violet, _disk(delta))
        a = a.copy()
        a[grown & ~violet] = VIOLET
        return a

    kept = ndimage.binary_erosion(violet, _disk(delta))
    vacated = violet & ~kept
    # Hand each vacated pixel to whichever region was nearest — background outside the
    # shape, the fill inside it. Guessing one or the other would leave a halo on the
    # wrong side of every stroke.
    #
    # `sources` excludes the sentinel as well as the violet, and that exclusion is the
    # whole reason the edges come out smooth. Quantising leaves a few stray sentinel
    # pixels along interior boundaries; with them eligible, every one became the nearest
    # neighbour for a wedge of the vacated band and got smeared along it, so each outline
    # ended up combed with magenta teeth a dozen pixels long.
    sources = ~violet & ~np.all(a == np.array(SENTINEL), axis=2)
    _, (iy, ix) = ndimage.distance_transform_edt(~sources, return_indices=True)
    a = a.copy()
    a[vacated] = a[iy[vacated], ix[vacated]]
    return a


def trace(src: Path, dst: Path, target: float, speckle: int, smooth: int, colours: int, trace_size: int) -> str:
    a = np.asarray(Image.open(src).convert("RGB")).astype(int)
    bg, mode = _em.background_mask(a)

    before = outline_width((np.linalg.norm(a - np.array(VIOLET), axis=2) < VIOLET_RADIUS) & ~bg)

    # Trim the halo before anything else looks at the image.
    #
    # Where the artwork meets the background there is an anti-aliased ramp a few pixels
    # wide, blending the outline into the checkerboard. It matches neither the background
    # tones nor any artwork colour, so masking on colour leaves it behind — and posterising
    # then splits it into a pale rim and a magenta one, which is the "tiny traces of white"
    # that show between an outline and the fill inside it.
    #
    # Safe to eat because the outline is regrown afterwards: a 10px line loses 6px here and
    # is then normalised back up to 30. Doing it in the other order is what would break it.
    bg = ndimage.binary_dilation(bg, _disk(HALO))
    a[bg] = SENTINEL
    ys, xs = np.where(~bg)
    if not ys.size:
        return f"{dst.name}: nothing but background"
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    bg = bg[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    # Downscale before tracing. The source is 2048px and nothing displays a mark above
    # 512, so tracing at full size buys no fidelity and costs it in coordinates: every
    # path number is twice as long and every wobble in the edge gets its own segment.
    # Done before posterising, so the anti-aliasing this reintroduces is flattened again
    # rather than traced.
    #
    # BOX rather than LANCZOS, which matters more than it looks. Lanczos overshoots at a
    # high-contrast edge — it is what makes a downscale look crisp — and posterising turns
    # that ringing into alternating pixels, so the eye's white-against-violet border came
    # out visibly ragged and the cat-ear's rose picked up black speckles from the dark side
    # of the same overshoot. Area averaging has no overshoot to quantise.
    if trace_size and max(a.shape[:2]) > trace_size:
        h, w = a.shape[:2]
        scale = trace_size / max(h, w)
        img = Image.fromarray(a.astype(np.uint8)).resize(
            (max(1, round(w * scale)), max(1, round(h * scale))), Image.BOX)
    else:
        img = Image.fromarray(a.astype(np.uint8))

    # Smooth before tracing. The source is JPEG, so every flat fill is faintly mottled
    # and every edge faintly ringed; a tracer reads that as detail and spends hundreds of
    # path segments describing compression noise. A median filter flattens it without
    # rounding the corners a blur would.
    img = img.filter(ImageFilter.MedianFilter(smooth))

    # Then posterise, which is what stops the fills leaking.
    #
    # Between a violet outline and the fill beside it there is an anti-aliased ramp a few
    # pixels wide. Traced in cutout mode — where regions do not overlap — that ramp
    # becomes a region of its own: a pale sliver following every outline, sitting between
    # the outline and a fill that is now slightly too small. Collapsing the image to a
    # handful of colours first removes the ramp, so the two regions meet on one edge and
    # there is nothing left in between for a sliver to be made of.
    #
    # **Dithering off.** `Image.quantize` applies Floyd-Steinberg by default, which is
    # right for photographs and wrong for this: it scatters pixels along every boundary
    # and through every gradient to approximate colours the palette does not hold. That
    # is what made the eye's edges look ragged and put black speckles through the
    # cat-ear's rose — the source art is perfectly clean, and the noise was ours.
    img = img.quantize(colors=colours, method=Image.FASTOCTREE,
                       dither=Image.Dither.NONE).convert("RGB")

    # Snap the two structural colours *after* posterising, so every mark ends up on the
    # same violet and the same fill black rather than on whatever its own cluster landed.
    q = np.asarray(img).astype(int)
    for canon, radius in ((VIOLET, VIOLET_SNAP), (MARK_BLACK, BLACK_SNAP)):
        q[np.linalg.norm(q - np.array(canon), axis=2) < radius] = canon

    # Put the sentinel back where it belongs and nowhere else.
    #
    # It is one of only six colours the posteriser has to work with, so it wins a few
    # pixels along interior boundaries that are nothing to do with the background. Left
    # alone they become background-coloured specks *inside* the mark, and every one is a
    # hole once the background paths are dropped. Recomputing from the mask that actually
    # knows where the background is costs nothing and removes the whole class.
    inside = ~_shrink(bg, q.shape[:2])
    stray = inside & (np.linalg.norm(q - np.array(SENTINEL), axis=2) < 80)
    if stray.any():
        _, (iy, ix) = ndimage.distance_transform_edt(stray, return_indices=True)
        q[stray] = q[iy[stray], ix[stray]]
    q[~inside] = SENTINEL

    # Normalise the outline only now, on flat colour.
    #
    # Doing it on the raw JPEG first left the eye — the widest outline in the set, cut
    # from 54px to 30 — with a visibly ragged seam. Narrowing hands each vacated pixel to
    # its nearest non-violet neighbour, and on an un-posterised image those neighbours are
    # anti-aliased pixels of no particular colour, so the new edge inherited their noise.
    # Against flat regions the same rule produces a clean boundary.
    if target:
        scale = q.shape[0] / a.shape[0]
        violet = np.all(q == np.array(VIOLET), axis=2)
        q = set_outline_width(q, violet, target * scale)

    img = Image.fromarray(q.astype(np.uint8))

    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / "flat.png"
        img.save(flat)
        raw = Path(tmp) / "raw.svg"
        vtracer.convert_image_to_svg_py(
            str(flat), str(raw), colormode="color", hierarchical="cutout", mode="spline",
            filter_speckle=speckle, color_precision=6, layer_difference=16,
            corner_threshold=60, length_threshold=4.0, splice_threshold=45, path_precision=1)
        svg = raw.read_text()

    svg = _tidy(svg)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(svg)
    after = outline_width(np.all(np.asarray(img).astype(int) == np.array(VIOLET), axis=2))
    after = after / (np.asarray(img).shape[0] / a.shape[0])
    kb = dst.stat().st_size / 1024
    return (f"{dst.name:<22} {mode.split(' ')[0]:<13} outline {before:>3.0f} -> {after:>3.0f}px"
            f"  {len(re.findall('<path', svg)):>3} paths  {kb:>5.1f} KB")


def _tidy(svg: str) -> str:
    """Drop the background paths and unify the two structural colours.

    Relies on the trace being made in `cutout` mode. In `stacked` mode vtracer lays a
    full-canvas base layer down and paints regions over it, so deleting the background
    path does not make a hole — it exposes the base, and half the set came back sitting
    on a violet rectangle. Cutout regions do not overlap, so a deleted path is gone.
    """
    def snap(m: re.Match[str]) -> str:
        c = m.group(1)
        rgb = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        if sum((x - y) ** 2 for x, y in zip(rgb, SENTINEL)) < 60 ** 2:
            return 'fill="DROP"'
        for canon in (VIOLET, MARK_BLACK):
            if sum((x - y) ** 2 for x, y in zip(rgb, canon)) < 60 ** 2:
                return 'fill="#%02x%02x%02x"' % canon
        return m.group(0)

    svg = re.sub(r'fill="#([0-9a-fA-F]{6})"', snap, svg)
    svg = re.sub(r"<path[^>]*fill=\"DROP\"[^>]*/>\s*", "", svg)
    # vtracer writes width/height in px and no viewBox, which pins the mark to one size.
    m = re.search(r'width="(\d+)"\s+height="(\d+)"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        svg = svg.replace(m.group(0), f'viewBox="0 0 {w} {h}"', 1)
    return svg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="path, or name=path to rename the output")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stroke", type=float, default=30,
                    help="target outline width in source pixels (0 to leave alone)")
    ap.add_argument("--speckle", type=int, default=32)
    ap.add_argument("--smooth", type=int, default=5, help="median filter size before tracing")
    ap.add_argument("--colours", type=int, default=6, help="posterise to this many colours")
    ap.add_argument("--trace-size", type=int, default=1024, help="downscale to this before tracing")
    args = ap.parse_args()

    for item in args.images:
        name, _, path = item.rpartition("=")
        src = Path(path)
        if not src.exists():
            print(f"missing: {src}", file=sys.stderr)
            return 1
        print(trace(src, args.out / f"{name or src.stem}.svg", args.stroke, args.speckle, args.smooth, args.colours, args.trace_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
