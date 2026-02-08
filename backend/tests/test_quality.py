"""Tests for audio quality scoring and comparison."""

from app.services.quality import (
    FormatTier,
    QualityScore,
    calculate_quality_score,
    compare_quality,
)


class TestCalculateQualityScore:
    """Tests for calculate_quality_score."""

    def test_flac_cd_quality(self):
        score = calculate_quality_score("flac", 1411, 44100, 16)
        assert score.format_tier == FormatTier.LOSSLESS_CD
        assert score.is_lossless is True

    def test_flac_hires_24bit(self):
        score = calculate_quality_score("flac", 2116, 96000, 24)
        assert score.format_tier == FormatTier.LOSSLESS_HIRES
        assert score.is_lossless is True

    def test_flac_hires_high_sample_rate(self):
        score = calculate_quality_score("flac", 2116, 96000, 16)
        assert score.format_tier == FormatTier.LOSSLESS_HIRES

    def test_mp3_320_cbr(self):
        score = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        assert score.format_tier == FormatTier.LOSSY_HIGH
        assert score.is_lossless is False

    def test_mp3_v0_vbr(self):
        score = calculate_quality_score("mp3", 245, 44100, None, "VBR")
        assert score.format_tier == FormatTier.LOSSY_HIGH

    def test_mp3_v2_vbr(self):
        score = calculate_quality_score("mp3", 190, 44100, None, "VBR")
        assert score.format_tier == FormatTier.LOSSY_MID

    def test_mp3_192_cbr(self):
        score = calculate_quality_score("mp3", 192, 44100, None, "CBR")
        assert score.format_tier == FormatTier.LOSSY_MID

    def test_mp3_128_cbr(self):
        score = calculate_quality_score("mp3", 128, 44100, None, "CBR")
        assert score.format_tier == FormatTier.LOSSY_LOW

    def test_mp3_low_vbr(self):
        score = calculate_quality_score("mp3", 128, 44100, None, "VBR")
        assert score.format_tier == FormatTier.LOSSY_LOW

    def test_unknown_format(self):
        score = calculate_quality_score("wma", 128, 44100, None)
        assert score.format_tier == FormatTier.UNKNOWN

    def test_bitrate_bps_normalization(self):
        """Bitrate > 10000 should be treated as bps and normalized to kbps."""
        score = calculate_quality_score("mp3", 320000, 44100, None, "CBR")
        assert score.bitrate == 320
        assert score.format_tier == FormatTier.LOSSY_HIGH

    def test_aac_lossy(self):
        score = calculate_quality_score("m4a", 256, 44100, None, "CBR")
        assert score.format_tier == FormatTier.LOSSY_MID
        assert score.is_lossless is False

    def test_wav_is_lossless(self):
        score = calculate_quality_score("wav", 1411, 44100, 16)
        assert score.is_lossless is True

    def test_aiff_is_lossless(self):
        score = calculate_quality_score("aiff", 1411, 44100, 16)
        assert score.is_lossless is True

    def test_no_bitrate_returns_unknown_tier(self):
        score = calculate_quality_score("mp3", None, 44100, None)
        assert score.format_tier == FormatTier.UNKNOWN

    def test_format_with_dot_prefix(self):
        score = calculate_quality_score(".flac", 1411, 44100, 16)
        assert score.is_lossless is True

    def test_none_format(self):
        score = calculate_quality_score(None, 320, 44100, None)
        assert score.format_tier == FormatTier.UNKNOWN


class TestQualityScoreFormatString:
    """Tests for QualityScore.format_string."""

    def test_lossless_full(self):
        score = QualityScore(FormatTier.LOSSLESS_HIRES, 2116, 96000, 24, True, None)
        assert score.format_string() == "FLAC 24-bit 96kHz"

    def test_lossless_cd(self):
        score = QualityScore(FormatTier.LOSSLESS_CD, 1411, 44100, 16, True, None)
        result = score.format_string()
        assert "FLAC" in result
        assert "16-bit" in result

    def test_lossless_no_details(self):
        score = QualityScore(FormatTier.LOSSLESS_CD, None, None, None, True, None)
        assert score.format_string() == "FLAC"

    def test_lossy_with_bitrate(self):
        score = QualityScore(FormatTier.LOSSY_HIGH, 320, 44100, None, False, "CBR")
        result = score.format_string()
        assert "320kbps" in result
        assert "CBR" in result

    def test_lossy_no_details(self):
        score = QualityScore(FormatTier.UNKNOWN, None, None, None, False, None)
        assert score.format_string() == "Unknown"

    def test_fractional_sample_rate(self):
        score = QualityScore(FormatTier.LOSSLESS_HIRES, None, 88200, 24, True, None)
        result = score.format_string()
        assert "88.2kHz" in result


class TestCompareQuality:
    """Tests for compare_quality."""

    def test_lossless_trumps_lossy(self):
        flac = calculate_quality_score("flac", 1411, 44100, 16)
        mp3 = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        status, reason = compare_quality(flac, mp3)
        assert status == "trumps"

    def test_lossy_trumped_by_lossless(self):
        mp3 = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        flac = calculate_quality_score("flac", 1411, 44100, 16)
        status, reason = compare_quality(mp3, flac)
        assert status == "trumped_by"

    def test_hires_trumps_cd(self):
        hires = calculate_quality_score("flac", 2116, 96000, 24)
        cd = calculate_quality_score("flac", 1411, 44100, 16)
        status, reason = compare_quality(hires, cd)
        assert status == "trumps"

    def test_same_lossless_equal(self):
        a = calculate_quality_score("flac", 1411, 44100, 16)
        b = calculate_quality_score("flac", 1411, 44100, 16)
        status, reason = compare_quality(a, b)
        assert status == "equal"

    def test_higher_bitrate_lossy_trumps(self):
        high = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        low = calculate_quality_score("mp3", 128, 44100, None, "CBR")
        status, reason = compare_quality(high, low)
        assert status == "trumps"

    def test_cbr_preferred_over_vbr_same_bitrate(self):
        cbr = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        vbr = calculate_quality_score("mp3", 320, 44100, None, "VBR")
        status, reason = compare_quality(cbr, vbr)
        assert status == "trumps"

    def test_same_lossy_equal(self):
        a = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        b = calculate_quality_score("mp3", 320, 44100, None, "CBR")
        status, reason = compare_quality(a, b)
        assert status == "equal"

    def test_higher_sample_rate_lossless_trumps(self):
        a = calculate_quality_score("flac", 2116, 96000, 24)
        b = calculate_quality_score("flac", 2116, 48000, 24)
        status, reason = compare_quality(a, b)
        assert status == "trumps"

    def test_higher_bit_depth_same_sr_trumps(self):
        a = calculate_quality_score("flac", 2116, 44100, 24)
        b = calculate_quality_score("flac", 1411, 44100, 16)
        status, reason = compare_quality(a, b)
        assert status == "trumps"
