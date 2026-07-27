"""Tests for cgroup-aware CPU counting.

`os.cpu_count()` reports the **host's** CPUs, not the container's quota. On the NAS that
is 8 against a cgroup limit of 2, so anything sizing work off `os.cpu_count()` overshoots
by 4x — it thinks it has cores it will never be scheduled on.

The concrete case is `adaptive_queue_limit`, which multiplies the count by 100 and clamps
to 500: at a reported 8 it returns the ceiling regardless of the real limit.

These drive the parsers against synthetic cgroup files rather than whatever the machine
running the tests happens to have, so they mean the same thing on macOS, on a bare Linux
runner, and inside a container.
"""

from pathlib import Path

import pytest

from app.config import adaptive_queue_limit, available_cpu_count


@pytest.fixture()
def cgroup(tmp_path, monkeypatch):
    """Point the cgroup readers at a temp directory and hand back writers for each file."""

    v2 = tmp_path / "cpu.max"
    v1_quota = tmp_path / "cpu.cfs_quota_us"
    v1_period = tmp_path / "cpu.cfs_period_us"

    monkeypatch.setattr("app.config.CGROUP_V2_CPU_MAX", v2)
    monkeypatch.setattr("app.config.CGROUP_V1_CPU_QUOTA", v1_quota)
    monkeypatch.setattr("app.config.CGROUP_V1_CPU_PERIOD", v1_period)
    monkeypatch.setattr("os.cpu_count", lambda: 8)

    class Cgroup:
        def v2(self, contents: str) -> None:
            v2.write_text(contents)

        def v1(self, quota: str, period: str) -> None:
            v1_quota.write_text(quota)
            v1_period.write_text(period)

    return Cgroup()


class TestCgroupV2:
    def test_reads_the_quota(self, cgroup):
        cgroup.v2("200000 100000")  # 2.0 CPUs — the NAS's actual setting
        assert available_cpu_count() == 2

    def test_unlimited_falls_back_to_the_host_count(self, cgroup):
        cgroup.v2("max 100000")
        assert available_cpu_count() == 8

    def test_fractional_quota_rounds_down_but_never_to_zero(self, cgroup):
        cgroup.v2("50000 100000")  # 0.5 CPUs
        assert available_cpu_count() == 1

    def test_quota_above_the_host_count_is_capped(self, cgroup):
        """A quota can exceed the cores that physically exist; the cores cannot."""
        cgroup.v2("1600000 100000")  # 16.0 CPUs on an 8-core host
        assert available_cpu_count() == 8

    def test_malformed_contents_fall_back(self, cgroup):
        cgroup.v2("nonsense")
        assert available_cpu_count() == 8

    def test_empty_file_falls_back(self, cgroup):
        cgroup.v2("")
        assert available_cpu_count() == 8


class TestCgroupV1:
    def test_reads_quota_and_period(self, cgroup):
        cgroup.v1("200000", "100000")
        assert available_cpu_count() == 2

    def test_negative_quota_means_unlimited(self, cgroup):
        cgroup.v1("-1", "100000")
        assert available_cpu_count() == 8

    def test_zero_period_does_not_divide_by_zero(self, cgroup):
        cgroup.v1("200000", "0")
        assert available_cpu_count() == 8

    def test_v2_wins_when_both_are_present(self, cgroup):
        cgroup.v2("400000 100000")  # 4.0
        cgroup.v1("100000", "100000")  # 1.0
        assert available_cpu_count() == 4


class TestNoCgroup:
    def test_missing_files_fall_back_to_os_cpu_count(self, cgroup):
        # The fixture creates no files.
        assert available_cpu_count() == 8

    def test_unreadable_file_falls_back(self, cgroup, monkeypatch):
        """A sandboxed or restricted /sys must not take the process down."""
        def boom(*args, **kwargs):
            raise PermissionError("nope")

        monkeypatch.setattr(Path, "read_text", boom)
        assert available_cpu_count() == 8

    def test_os_cpu_count_none_falls_back_to_two(self, cgroup, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: None)
        assert available_cpu_count() == 2

    def test_always_at_least_one(self, cgroup, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 0)
        assert available_cpu_count() >= 1


class TestAdaptiveQueueLimitUsesTheRealCount:
    """The reason the helper exists."""

    def test_capped_container_no_longer_reports_the_ceiling(self, cgroup):
        cgroup.v2("200000 100000")  # 2.0 CPUs on an 8-core host — the NAS
        assert adaptive_queue_limit() == 200, (
            "with os.cpu_count() this returned the 500 clamp, sizing analysis batches "
            "for four times the cores the container can actually use"
        )

    def test_uncapped_host_is_unchanged(self, cgroup):
        cgroup.v2("max 100000")
        assert adaptive_queue_limit() == 500  # 8 * 100, clamped
