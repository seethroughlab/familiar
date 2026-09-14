"""Quality scoring and comparison for audio tracks.

Implements music tracker-style quality hierarchy for duplicate detection
and replacement ("trumping").
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class FormatTier(IntEnum):
    """Quality tiers from lowest to highest."""
    UNKNOWN = 0
    LOSSY_LOW = 1      # MP3 <192kbps
    LOSSY_MID = 2      # MP3 V2 (~190kbps avg)
    LOSSY_HIGH = 3     # MP3 320 CBR, V0 (~245kbps avg)
    LOSSLESS_CD = 4    # FLAC 16-bit 44.1kHz
    LOSSLESS_HIRES = 5 # FLAC 24-bit or >48kHz


@dataclass
class QualityScore:
    """Quality score for a track."""
    format_tier: FormatTier
    bitrate: int | None  # kbps
    sample_rate: int | None  # Hz
    bit_depth: int | None
    is_lossless: bool
    bitrate_mode: str | None  # "CBR", "VBR", or None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "format_tier": self.format_tier.value,
            "format_tier_name": self.format_tier.name,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "is_lossless": self.is_lossless,
            "bitrate_mode": self.bitrate_mode,
        }

    def format_string(self) -> str:
        """Human-readable quality string."""
        if self.is_lossless:
            parts = []
            if self.bit_depth:
                parts.append(f"{self.bit_depth}-bit")
            if self.sample_rate:
                sr_khz = self.sample_rate / 1000
                if sr_khz == int(sr_khz):
                    parts.append(f"{int(sr_khz)}kHz")
                else:
                    parts.append(f"{sr_khz:.1f}kHz")
            if parts:
                return f"FLAC {' '.join(parts)}"
            return "FLAC"
        else:
            # Lossy format
            parts = []
            if self.bitrate:
                parts.append(f"{self.bitrate}kbps")
            if self.bitrate_mode:
                parts.append(self.bitrate_mode)
            return " ".join(parts) if parts else "Unknown"


#: File formats (by suffix) that are lossless. **One set, two readers**: the quality score below and
#: `is_lossless_source`, which decides whether `/stream?format=aac` encodes a track or passes it
#: through (ADR-0118 point 2). They must agree, so there is one of them.
LOSSLESS_FORMATS = frozenset({"flac", "alac", "wav", "aiff", "aif"})

#: Codecs that are lossless whatever container they arrive in. `format` is the file suffix, and an
#: ALAC file is `.m4a` — the same suffix as AAC — so the suffix alone would call it lossy and
#: `?format=aac` would hand it back untouched at 30 MB. ffprobe names these; `Track.codec` stores
#: what it said.
LOSSLESS_CODECS = frozenset({"flac", "alac", "wavpack", "ape", "tta", "truehd", "mlp"})


def is_lossless_source(suffix: str | None, codec: str | None) -> bool:
    """Whether a library file is lossless — by codec when known, by suffix otherwise.

    The codec wins because it is the truth and the suffix is a convention: ``.m4a`` holds both
    AAC and ALAC, and ``pcm_*`` is what ffprobe calls the audio inside a WAV or AIFF.
    """
    if codec:
        c = codec.lower()
        if c in LOSSLESS_CODECS or c.startswith("pcm_"):
            return True
        # A known lossy codec is lossy even in a container the suffix table calls lossless —
        # there is no such file in practice, but the suffix should not overrule ffprobe.
        if c in ("aac", "mp3", "vorbis", "opus", "wmav2", "wmav1"):
            return False
    return (suffix or "").lower().lstrip(".") in LOSSLESS_FORMATS


def calculate_quality_score(
    format: str | None,
    bitrate: int | None,
    sample_rate: int | None,
    bit_depth: int | None,
    bitrate_mode: str | None = None,
) -> QualityScore:
    """Calculate quality score from track metadata.

    Args:
        format: File format (mp3, flac, m4a, etc.)
        bitrate: Bitrate in kbps (or bps for some sources - we normalize)
        sample_rate: Sample rate in Hz
        bit_depth: Bit depth (16, 24, etc.)
        bitrate_mode: "CBR", "VBR", or None

    Returns:
        QualityScore with tier and metadata
    """
    format_lower = (format or "").lower().lstrip(".")

    # Normalize bitrate to kbps (some sources report bps)
    if bitrate and bitrate > 10000:
        bitrate = bitrate // 1000

    # Lossless formats
    is_lossless = format_lower in LOSSLESS_FORMATS

    if is_lossless:
        # Determine lossless tier based on bit depth and sample rate
        is_hires = False
        if bit_depth and bit_depth > 16:
            is_hires = True
        if sample_rate and sample_rate > 48000:
            is_hires = True

        tier = FormatTier.LOSSLESS_HIRES if is_hires else FormatTier.LOSSLESS_CD

        return QualityScore(
            format_tier=tier,
            bitrate=bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            is_lossless=True,
            bitrate_mode=None,
        )

    # Lossy formats
    if format_lower in ("mp3", "m4a", "aac", "ogg", "opus"):
        tier = _classify_lossy_tier(bitrate, bitrate_mode)

        return QualityScore(
            format_tier=tier,
            bitrate=bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            is_lossless=False,
            bitrate_mode=bitrate_mode,
        )

    # Unknown format
    return QualityScore(
        format_tier=FormatTier.UNKNOWN,
        bitrate=bitrate,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        is_lossless=False,
        bitrate_mode=bitrate_mode,
    )


def _classify_lossy_tier(bitrate: int | None, bitrate_mode: str | None) -> FormatTier:
    """Classify lossy audio into quality tiers.

    Tier classification:
    - LOSSY_HIGH: 320 CBR, or VBR with avg >= 245 (V0)
    - LOSSY_MID: 192-319 CBR, or VBR with avg 190-244 (V2)
    - LOSSY_LOW: <192 kbps
    """
    if not bitrate:
        return FormatTier.UNKNOWN

    if bitrate_mode == "CBR":
        if bitrate >= 320:
            return FormatTier.LOSSY_HIGH
        elif bitrate >= 192:
            return FormatTier.LOSSY_MID
        else:
            return FormatTier.LOSSY_LOW
    elif bitrate_mode == "VBR":
        # VBR classification based on average bitrate
        # V0 averages ~245kbps, V2 averages ~190kbps
        if bitrate >= 245:
            return FormatTier.LOSSY_HIGH
        elif bitrate >= 180:
            return FormatTier.LOSSY_MID
        else:
            return FormatTier.LOSSY_LOW
    else:
        # Unknown bitrate mode - use bitrate alone
        if bitrate >= 320:
            return FormatTier.LOSSY_HIGH
        elif bitrate >= 192:
            return FormatTier.LOSSY_MID
        else:
            return FormatTier.LOSSY_LOW


def compare_quality(
    incoming: QualityScore,
    existing: QualityScore,
) -> tuple[str, str]:
    """Compare quality of incoming track vs existing track.

    Args:
        incoming: Quality score of track being imported
        existing: Quality score of track already in library

    Returns:
        Tuple of (status, reason) where:
        - status: "trumps" (incoming is better), "trumped_by" (existing is better), "equal"
        - reason: Human-readable explanation
    """
    # Compare by tier first
    if incoming.format_tier > existing.format_tier:
        return (
            "trumps",
            f"{incoming.format_string()} > {existing.format_string()}"
        )
    elif incoming.format_tier < existing.format_tier:
        return (
            "trumped_by",
            f"{existing.format_string()} > {incoming.format_string()}"
        )

    # Same tier - compare specifics
    # For lossless, compare sample rate then bit depth
    if incoming.is_lossless and existing.is_lossless:
        # Higher sample rate wins
        inc_sr = incoming.sample_rate or 0
        ext_sr = existing.sample_rate or 0
        if inc_sr > ext_sr:
            return (
                "trumps",
                f"Higher sample rate: {inc_sr}Hz > {ext_sr}Hz"
            )
        elif inc_sr < ext_sr:
            return (
                "trumped_by",
                f"Higher sample rate: {ext_sr}Hz > {inc_sr}Hz"
            )

        # Same sample rate - compare bit depth
        inc_bd = incoming.bit_depth or 0
        ext_bd = existing.bit_depth or 0
        if inc_bd > ext_bd:
            return (
                "trumps",
                f"Higher bit depth: {inc_bd}-bit > {ext_bd}-bit"
            )
        elif inc_bd < ext_bd:
            return (
                "trumped_by",
                f"Higher bit depth: {ext_bd}-bit > {inc_bd}-bit"
            )

        return ("equal", "Same lossless quality")

    # For lossy, compare bitrate
    if not incoming.is_lossless and not existing.is_lossless:
        inc_br = incoming.bitrate or 0
        ext_br = existing.bitrate or 0
        if inc_br > ext_br:
            return (
                "trumps",
                f"Higher bitrate: {inc_br}kbps > {ext_br}kbps"
            )
        elif inc_br < ext_br:
            return (
                "trumped_by",
                f"Higher bitrate: {ext_br}kbps > {inc_br}kbps"
            )

        # Same bitrate - prefer CBR over VBR (CBR is more predictable)
        if incoming.bitrate_mode == "CBR" and existing.bitrate_mode == "VBR":
            return ("trumps", "CBR preferred over VBR at same bitrate")
        elif incoming.bitrate_mode == "VBR" and existing.bitrate_mode == "CBR":
            return ("trumped_by", "CBR preferred over VBR at same bitrate")

        return ("equal", "Same lossy quality")

    # Should not reach here given tier comparison above
    return ("equal", "Same quality tier")
