"""Generative album art from audio analysis features.

Renders a deterministic 500x500 layered composition using Pillow,
driven by aggregated TrackAnalysis features. Used as a final fallback
when no real artwork is available from embedded tags or external sources.
"""

import colorsys
import hashlib
import logging
import math
import random
from collections import Counter
from io import BytesIO
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# Output size
SIZE = 500


# ── Feature Aggregation ─────────────────────────────────────────────────


async def aggregate_album_features(
    db, artist: str, album: str
) -> dict | None:
    """Query all tracks for an album and aggregate their analysis features.

    Numeric features use median (robust against outlier tracks).
    Categorical features use mode (most common value).
    Returns None if no analyzed tracks exist.
    """
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis

    stmt = (
        select(TrackAnalysis)
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(Track.artist == artist, Track.album == album)
    )
    result = await db.execute(stmt)
    analyses = result.scalars().all()

    if not analyses:
        return None

    # Numeric features: collect non-None values, take median
    numeric_keys = [
        "bpm", "energy", "danceability", "valence", "acousticness",
        "instrumentalness", "speechiness", "brightness",
        "dynamic_range_db", "harmonic_complexity", "swing_ratio",
        "syncopation", "section_count", "note_density",
    ]
    # Categorical features: take mode
    categorical_keys = [
        "key", "modal_character", "energy_shape", "tempo_character",
    ]

    features: dict = {}

    for key in numeric_keys:
        values = [getattr(a, key) for a in analyses if getattr(a, key) is not None]
        if values:
            features[key] = median(values)

    for key in categorical_keys:
        values = [getattr(a, key) for a in analyses if getattr(a, key) is not None]
        if values:
            counter = Counter(values)
            features[key] = counter.most_common(1)[0][0]

    # Genre from tracks
    genre_stmt = (
        select(Track.genre)
        .where(Track.artist == artist, Track.album == album, Track.genre.isnot(None))
    )
    genre_result = await db.execute(genre_stmt)
    genres = [r[0] for r in genre_result.all()]
    if genres:
        counter = Counter(genres)
        features["genre"] = counter.most_common(1)[0][0]

    return features if features else None


# ── Color Palette ────────────────────────────────────────────────────────

# 12 musical keys mapped to evenly-spaced hues (0-1)
KEY_HUE_MAP = {
    "C": 0.0, "C#": 1 / 12, "Db": 1 / 12,
    "D": 2 / 12, "D#": 3 / 12, "Eb": 3 / 12,
    "E": 4 / 12, "F": 5 / 12,
    "F#": 6 / 12, "Gb": 6 / 12,
    "G": 7 / 12, "G#": 8 / 12, "Ab": 8 / 12,
    "A": 9 / 12, "A#": 10 / 12, "Bb": 10 / 12,
    "B": 11 / 12,
}


def _parse_key_root(key_str: str | None) -> str | None:
    """Extract root note from key string like 'Am', 'C#m', 'D major'."""
    if not key_str:
        return None
    # Strip mode suffixes
    root = key_str.replace("minor", "").replace("major", "").replace("m", "").strip()
    # Handle sharps/flats
    if len(root) >= 2 and root[1] in ("#", "b"):
        return root[:2]
    return root[:1] if root else None


def _derive_palette(features: dict) -> list[tuple[int, int, int]]:
    """Derive a 5-color palette from audio features using HSL color space."""
    # Base hue from musical key
    key_root = _parse_key_root(features.get("key"))
    base_hue = KEY_HUE_MAP.get(key_root, 0.5) if key_root else 0.5

    # Energy -> saturation (0.3-0.9)
    energy = features.get("energy", 0.5)
    saturation = 0.3 + energy * 0.6

    # Valence -> lightness (0.2-0.7, happy=lighter)
    valence = features.get("valence", 0.5)
    lightness = 0.2 + valence * 0.5

    # Modal character shifts hue
    modal = features.get("modal_character", "")
    if "major" in str(modal).lower():
        base_hue = (base_hue + 0.03) % 1.0  # Warmer
    elif "minor" in str(modal).lower():
        base_hue = (base_hue - 0.03) % 1.0  # Cooler
    elif "atonal" in str(modal).lower():
        saturation *= 0.6  # Desaturate

    # Brightness -> secondary hue offset
    brightness = features.get("brightness", 0.5)
    secondary_offset = 0.1 + brightness * 0.2

    # Acousticness -> background warmth
    acousticness = features.get("acousticness", 0.5)
    bg_hue_shift = acousticness * 0.05

    def hsl_to_rgb(h: float, s: float, lit: float) -> tuple[int, int, int]:
        r, g, b = colorsys.hls_to_rgb(h % 1.0, lit, s)
        return (int(r * 255), int(g * 255), int(b * 255))

    palette = [
        # Primary
        hsl_to_rgb(base_hue, saturation, lightness),
        # Secondary
        hsl_to_rgb(base_hue + secondary_offset, saturation * 0.8, lightness + 0.1),
        # Accent
        hsl_to_rgb(base_hue - secondary_offset, saturation * 0.9, lightness - 0.05),
        # Background dark
        hsl_to_rgb(base_hue + bg_hue_shift, saturation * 0.4, max(0.1, lightness - 0.15)),
        # Background light
        hsl_to_rgb(base_hue + bg_hue_shift, saturation * 0.3, min(0.9, lightness + 0.2)),
    ]
    return palette


# ── Rendering Layers ─────────────────────────────────────────────────────


def _render_background(
    img: Image.Image, palette: list[tuple[int, int, int]], features: dict
) -> None:
    """Render a two-color gradient background with optional film grain."""
    bpm = features.get("bpm", 120)
    angle_rad = math.radians(bpm % 180)

    color_a = palette[3]  # Background dark
    color_b = palette[4]  # Background light

    # Direction vector for gradient
    dx = math.cos(angle_rad)
    dy = math.sin(angle_rad)

    # Build gradient as raw pixel data for speed (avoid per-pixel draw calls)
    pixels = bytearray(SIZE * SIZE * 3)
    half = SIZE / 2
    for y in range(SIZE):
        row_base = (y - half) * dy
        for x in range(SIZE):
            t = ((x - half) * dx + row_base) / SIZE + 0.5
            t = max(0.0, min(1.0, t))
            idx = (y * SIZE + x) * 3
            pixels[idx] = int(color_a[0] + (color_b[0] - color_a[0]) * t)
            pixels[idx + 1] = int(color_a[1] + (color_b[1] - color_a[1]) * t)
            pixels[idx + 2] = int(color_a[2] + (color_b[2] - color_a[2]) * t)
    img.frombytes(bytes(pixels))

    # High acousticness -> warm film grain noise
    acousticness = features.get("acousticness", 0.5)
    if acousticness > 0.6:
        grain_rng = random.Random(int(bpm * 1000))
        grain_opacity = int((acousticness - 0.6) * 80)  # 0-32
        grain_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        grain_draw = ImageDraw.Draw(grain_layer)
        for _ in range(SIZE * SIZE // 20):
            gx = grain_rng.randint(0, SIZE - 1)
            gy = grain_rng.randint(0, SIZE - 1)
            noise_val = grain_rng.randint(-30, 30)
            warm = max(0, min(255, 128 + noise_val))
            grain_draw.point((gx, gy), fill=(warm, warm - 10, warm - 20, grain_opacity))
        img.paste(Image.alpha_composite(img.convert("RGBA"), grain_layer).convert("RGB"))


def _render_geometry(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    features: dict,
    rng: random.Random,
) -> None:
    """Render geometric shapes driven by energy_shape, section_count, etc."""
    draw = ImageDraw.Draw(img, "RGBA")

    energy_shape = features.get("energy_shape", "varied")
    section_count = int(features.get("section_count", 8))
    section_count = max(3, min(20, section_count))
    harmonic_complexity = features.get("harmonic_complexity", 0.5)
    swing_ratio = features.get("swing_ratio", 0.5)
    dynamic_range = features.get("dynamic_range_db", 10)
    instrumentalness = features.get("instrumentalness", 0.5)

    # Polygon sides from harmonic complexity (3=triangle to 8=octagon)
    sides = max(3, min(8, int(3 + harmonic_complexity * 5)))

    # Alpha from instrumentalness (more instrumental = more ethereal)
    alpha = max(30, min(180, int(180 - instrumentalness * 120)))

    # Spread radius from dynamic range
    spread = max(50, min(200, int(dynamic_range * 8)))

    # Choose shape type based on energy_shape
    shape_type = "circle"
    if energy_shape == "building":
        shape_type = "triangle"
    elif energy_shape == "varied":
        shape_type = "mixed"
    elif energy_shape == "decaying":
        shape_type = "square"

    # Layout: circular vs offset grid
    circular_layout = swing_ratio < 0.55

    cx, cy = SIZE // 2, SIZE // 2

    for i in range(section_count):
        color = palette[i % 3]
        rgba_color = (*color, alpha)

        # Position
        if circular_layout:
            angle = (2 * math.pi * i) / section_count
            radius = spread * (0.5 + rng.random() * 0.5)
            px = int(cx + radius * math.cos(angle))
            py = int(cy + radius * math.sin(angle))
        else:
            cols = max(2, int(math.sqrt(section_count)))
            row, col = divmod(i, cols)
            cell_w = SIZE // cols
            cell_h = SIZE // max(1, (section_count + cols - 1) // cols)
            px = col * cell_w + cell_w // 2 + rng.randint(-20, 20)
            py = row * cell_h + cell_h // 2 + rng.randint(-20, 20)

        # Size varies per shape
        shape_size = int(20 + rng.random() * 40 + spread * 0.2)

        current_shape = shape_type
        if shape_type == "mixed":
            current_shape = rng.choice(["circle", "triangle", "square", "polygon"])

        if current_shape == "circle":
            bbox = [px - shape_size, py - shape_size, px + shape_size, py + shape_size]
            draw.ellipse(bbox, fill=rgba_color)
        elif current_shape == "triangle":
            points = _regular_polygon_points(px, py, shape_size, 3, rng.random() * math.pi)
            draw.polygon(points, fill=rgba_color)
        elif current_shape == "square":
            half = shape_size
            draw.rectangle([px - half, py - half, px + half, py + half], fill=rgba_color)
        elif current_shape == "polygon":
            points = _regular_polygon_points(px, py, shape_size, sides, rng.random() * math.pi)
            draw.polygon(points, fill=rgba_color)


def _regular_polygon_points(
    cx: int, cy: int, radius: int, sides: int, rotation: float = 0
) -> list[tuple[int, int]]:
    """Generate vertices for a regular polygon."""
    points = []
    for i in range(sides):
        angle = rotation + (2 * math.pi * i) / sides
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        points.append((x, y))
    return points


def _render_flow_field(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    features: dict,
    rng: random.Random,
) -> None:
    """Render a deterministic flow field with pseudo-noise."""
    draw = ImageDraw.Draw(img, "RGBA")

    note_density = features.get("note_density", 5.0)
    danceability = features.get("danceability", 0.5)
    dynamic_range = features.get("dynamic_range_db", 10)

    # Number of lines from note density (10-80)
    num_lines = max(10, min(80, int(note_density * 8)))

    # Line length from danceability (more danceable = longer curves)
    line_length = max(20, min(150, int(30 + danceability * 120)))

    # Line thickness from dynamic range
    line_width = max(1, min(4, int(dynamic_range / 8)))

    # Alpha for flow lines
    alpha = 100

    # Seed for deterministic noise field
    seed_val = rng.randint(0, 100000)

    for i in range(num_lines):
        # Starting position
        x = float(rng.randint(20, SIZE - 20))
        y = float(rng.randint(20, SIZE - 20))

        color = palette[(i % 3)]
        rgba_color = (*color, alpha)

        points: list[tuple[float, float]] = [(x, y)]

        for step in range(line_length):
            # Pseudo-noise angle field
            nx = x / SIZE * 3
            ny = y / SIZE * 3
            angle = _pseudo_noise(nx, ny, seed_val + i) * math.pi * 2
            x += math.cos(angle) * 3
            y += math.sin(angle) * 3

            # Clamp to bounds
            x = max(0, min(SIZE - 1, x))
            y = max(0, min(SIZE - 1, y))
            points.append((x, y))

        # Draw as connected line segments
        if len(points) > 1:
            int_points = [(int(p[0]), int(p[1])) for p in points]
            for j in range(len(int_points) - 1):
                draw.line(
                    [int_points[j], int_points[j + 1]],
                    fill=rgba_color,
                    width=line_width,
                )


def _pseudo_noise(x: float, y: float, seed: int) -> float:
    """Simple deterministic pseudo-noise function (0-1)."""
    # Hash-based noise for determinism without numpy
    val = math.sin(x * 12.9898 + y * 78.233 + seed * 0.1) * 43758.5453
    return val - math.floor(val)


def _render_texture(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    features: dict,
    rng: random.Random,
) -> None:
    """Render texture elements: dot marks, syncopation accents, rhythmic lines."""
    draw = ImageDraw.Draw(img, "RGBA")

    speechiness = features.get("speechiness", 0.0)
    syncopation = features.get("syncopation", 0.0)
    bpm = features.get("bpm", 120)

    # Speechiness -> text-like dot marks
    if speechiness > 0.1:
        num_dots = int(speechiness * 300)
        dot_color = (*palette[2], 60)
        for _ in range(num_dots):
            dx = rng.randint(30, SIZE - 30)
            dy = rng.randint(30, SIZE - 30)
            # Small clusters to suggest text
            for _ in range(rng.randint(2, 6)):
                ox = dx + rng.randint(-2, 8)
                oy = dy + rng.randint(-1, 1)
                draw.point((ox, oy), fill=dot_color)
            dy += rng.randint(4, 8)

    # Syncopation -> off-grid accent dots
    if syncopation > 0.2:
        num_accents = int(syncopation * 40)
        accent_color = (*palette[1], 80)
        for _ in range(num_accents):
            ax = rng.randint(20, SIZE - 20)
            ay = rng.randint(20, SIZE - 20)
            r = rng.randint(2, 5)
            draw.ellipse([ax - r, ay - r, ax + r, ay + r], fill=accent_color)

    # BPM -> subtle rhythmic vertical lines
    num_lines = max(5, min(30, int(bpm / 8)))
    line_color = (*palette[0], 25)
    spacing = SIZE // num_lines
    for i in range(num_lines):
        x = i * spacing + rng.randint(-3, 3)
        draw.line([(x, 0), (x, SIZE)], fill=line_color, width=1)


def _post_process(img: Image.Image, features: dict) -> Image.Image:
    """Apply post-processing: blur, vignette, or light flare."""
    # Slight Gaussian blur to blend layers
    img = img.filter(ImageFilter.GaussianBlur(radius=12))

    brightness = features.get("brightness", 0.5)

    if brightness < 0.3:
        # Vignette: darken edges
        vignette = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        vignette_draw = ImageDraw.Draw(vignette)
        cx, cy = SIZE // 2, SIZE // 2
        for ring in range(0, SIZE // 2, 2):
            # Outer rings are darker
            t = ring / (SIZE // 2)
            alpha = int(t * t * 100)  # Quadratic falloff, max 100
            vignette_draw.ellipse(
                [cx - (SIZE // 2 - ring), cy - (SIZE // 2 - ring),
                 cx + (SIZE // 2 - ring), cy + (SIZE // 2 - ring)],
                fill=None,
                outline=(0, 0, 0, alpha),
                width=3,
            )
        img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")

    elif brightness > 0.7:
        # Subtle light flare in upper area
        flare = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        flare_draw = ImageDraw.Draw(flare)
        flare_x = SIZE // 3
        flare_y = SIZE // 4
        for r in range(80, 0, -2):
            alpha = max(0, min(40, int((80 - r) * 0.5)))
            flare_draw.ellipse(
                [flare_x - r, flare_y - r, flare_x + r, flare_y + r],
                fill=(255, 255, 240, alpha),
            )
        img = Image.alpha_composite(img.convert("RGBA"), flare).convert("RGB")

    return img


# ── Vinyl Label ──────────────────────────────────────────────────────────

_FONT_PATH = Path(__file__).parent.parent / "assets" / "fonts" / "Inter-SemiBold.ttf"


def _get_initials(artist: str, album: str) -> str:
    """Extract initials from artist and album names.

    Skips common prefixes like 'The', 'A', 'An' for the artist.
    """
    a_initial = ""
    if artist:
        # Skip common prefixes
        name = artist.strip()
        for prefix in ("The ", "A ", "An "):
            if name.startswith(prefix) and len(name) > len(prefix):
                name = name[len(prefix):]
                break
        if name:
            a_initial = name[0].upper()

    b_initial = ""
    if album:
        name = album.strip()
        if name:
            b_initial = name[0].upper()

    return a_initial + b_initial


def _draw_arc_text(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    center: tuple[int, int],
    radius: int,
    start_angle: float,
    end_angle: float,
    color: tuple[int, int, int, int],
    shadow_color: tuple[int, int, int, int] | None = None,
    clockwise: bool = True,
) -> None:
    """Render text along a circular arc by placing each character individually."""
    if not text:
        return

    cx, cy = center

    # Measure total text width and individual char widths
    char_widths = []
    for ch in text:
        bbox = font.getbbox(ch)
        char_widths.append(bbox[2] - bbox[0])
    total_width = sum(char_widths)

    # Calculate available arc length
    arc_span = abs(end_angle - start_angle)
    arc_length = radius * arc_span

    # Truncate with ellipsis if text is too wide
    display_text = text
    display_widths = char_widths
    if total_width > arc_length * 0.75:
        ellipsis = "..."
        ellipsis_width = sum(font.getbbox(c)[2] - font.getbbox(c)[0] for c in ellipsis)
        budget = arc_length * 0.75 - ellipsis_width
        accum = 0
        cut = 0
        for i, w in enumerate(char_widths):
            if accum + w > budget:
                cut = i
                break
            accum += w
        else:
            cut = len(char_widths)
        display_text = text[:cut] + ellipsis
        display_widths = char_widths[:cut] + [
            font.getbbox(c)[2] - font.getbbox(c)[0] for c in ellipsis
        ]
        total_width = sum(display_widths)

    # Calculate angle per pixel
    angle_per_px = arc_span / (radius if radius > 0 else 1)

    # Center the text within the arc
    text_arc_span = total_width * angle_per_px
    if clockwise:
        current_angle = start_angle + (arc_span - text_arc_span) / 2
    else:
        current_angle = start_angle - (arc_span - text_arc_span) / 2

    for i, ch in enumerate(display_text):
        char_w = display_widths[i]
        char_arc = char_w * angle_per_px

        if clockwise:
            char_angle = current_angle + char_arc / 2
        else:
            char_angle = current_angle - char_arc / 2

        # Position on circle
        x = cx + radius * math.cos(char_angle)
        y = cy + radius * math.sin(char_angle)

        # Render character to small image
        bbox = font.getbbox(ch)
        ch_w = bbox[2] - bbox[0]
        ch_h = bbox[3] - bbox[1]
        pad = 4
        char_img_size = max(ch_w, ch_h) + pad * 2

        # Rotation angle: tangent to circle
        if clockwise:
            rot = math.degrees(char_angle) + 90
        else:
            rot = math.degrees(char_angle) - 90

        # Draw shadow first, then main character
        for draw_color, offset in [
            (shadow_color, 1),
            (color, 0),
        ]:
            if draw_color is None:
                continue
            char_img = Image.new("RGBA", (char_img_size, char_img_size), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_img)
            tx = char_img_size // 2 - ch_w // 2 - bbox[0]
            ty = char_img_size // 2 - ch_h // 2 - bbox[1]
            char_draw.text((tx + offset, ty + offset), ch, font=font, fill=draw_color)

            rotated = char_img.rotate(-rot, resample=Image.BICUBIC, expand=True)

            # Paste centered on position
            paste_x = int(x - rotated.width / 2)
            paste_y = int(y - rotated.height / 2)
            img.paste(rotated, (paste_x, paste_y), rotated)

        if clockwise:
            current_angle += char_arc
        else:
            current_angle -= char_arc


def _render_vinyl_label(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    features: dict,
    artist: str,
    album: str,
) -> None:
    """Render a vinyl record label with arc text and centered initials."""
    if not _FONT_PATH.exists():
        logger.warning("Font not found at %s, skipping vinyl label", _FONT_PATH)
        return

    label = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(label)

    cx, cy = SIZE // 2, SIZE // 2
    radius = 180

    # Dark backdrop disc for text contrast
    draw.ellipse(
        [cx - radius + 4, cy - radius + 4, cx + radius - 4, cy + radius - 4],
        fill=(0, 0, 0, 50),
    )

    # Semi-transparent ring
    ring_color = (255, 255, 255, 80)
    ring_width = 2
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=ring_color,
        width=ring_width,
    )

    # Separator dots at 3 o'clock and 9 o'clock
    dot_r = 3
    dot_color = (255, 255, 255, 100)
    for angle in [0, math.pi]:  # 3 o'clock and 9 o'clock
        dx = int(cx + radius * math.cos(angle))
        dy = int(cy + radius * math.sin(angle))
        draw.ellipse(
            [dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r],
            fill=dot_color,
        )

    # Text colors
    text_color = (255, 255, 255, 230)
    shadow = (0, 0, 0, 180)

    # Load fonts at different sizes
    font_artist = ImageFont.truetype(str(_FONT_PATH), 22)
    font_album = ImageFont.truetype(str(_FONT_PATH), 18)
    font_initials = ImageFont.truetype(str(_FONT_PATH), 90)

    # Artist name - arc along top of circle (120° span centered at top)
    # 0 rad = 3 o'clock, -π/2 = top; span from -150° to -30°
    artist_text = artist.upper() if artist else ""
    text_radius = radius - 14  # Slightly inside the ring
    _draw_arc_text(
        label, artist_text, font_artist, (cx, cy), text_radius,
        start_angle=-math.pi * 5 / 6,  # -150 degrees
        end_angle=-math.pi / 6,        # -30 degrees
        color=text_color,
        shadow_color=shadow,
        clockwise=True,
    )

    # Album name - arc along bottom of circle (120° span centered at bottom)
    album_text = album.upper() if album else ""
    _draw_arc_text(
        label, album_text, font_album, (cx, cy), text_radius,
        start_angle=math.pi * 5 / 6,   # 150 degrees
        end_angle=math.pi / 6,         # 30 degrees
        color=text_color,
        shadow_color=shadow,
        clockwise=False,
    )

    # Centered initials
    initials = _get_initials(artist, album)
    if initials:
        # Shadow
        bbox = font_initials.getbbox(initials)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        ix = cx - tw // 2 - bbox[0]
        iy = cy - th // 2 - bbox[1]
        draw.text((ix + 2, iy + 2), initials, font=font_initials, fill=(0, 0, 0, 160))
        draw.text((ix, iy), initials, font=font_initials, fill=text_color)

    # Composite label onto main image
    img_rgba = img.convert("RGBA")
    composited = Image.alpha_composite(img_rgba, label)
    img.paste(composited.convert("RGB"))


# ── Public Entry Point ───────────────────────────────────────────────────


async def generate_album_art(album_hash: str, artist: str, album: str) -> bool:
    """Generate deterministic album art from audio analysis features.

    Creates its own DB session. Saves artwork to disk and creates a
    .generated marker file.

    Returns True if artwork was generated and saved, False otherwise.
    """
    from app.db.session import create_task_engine_session
    from app.services.artwork import save_artwork

    engine, session_maker = create_task_engine_session()
    try:
        async with session_maker() as db:
            features = await aggregate_album_features(db, artist, album)

        if not features:
            logger.debug(f"No analyzed tracks for {artist} - {album}, skipping generative art")
            return False

        # Deterministic seed from album hash
        seed = int(hashlib.sha256(album_hash.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Derive color palette
        palette = _derive_palette(features)

        # Render layers
        img = Image.new("RGB", (SIZE, SIZE), palette[3])

        _render_background(img, palette, features)
        _render_geometry(img, palette, features, rng)
        _render_flow_field(img, palette, features, rng)
        _render_texture(img, palette, features, rng)
        img = _post_process(img, features)
        _render_vinyl_label(img, palette, features, artist, album)

        # Encode to JPEG bytes
        buf = BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        image_data = buf.getvalue()

        # Save using standard artwork pipeline
        saved = save_artwork(image_data, album_hash)
        if saved:
            from app.services.artwork import mark_as_generated
            mark_as_generated(album_hash)
            logger.info(f"Generated artwork for {artist} - {album} ({album_hash})")
            return True

        return False

    except Exception:
        logger.exception(f"Failed to generate artwork for {artist} - {album}")
        return False
    finally:
        await engine.dispose()
