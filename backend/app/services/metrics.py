"""Application metrics collection for observability."""

import contextvars
import logging
import threading
import time
from collections import deque
from typing import Any

# Per-request SQL query counter (contextvar resets per request in middleware)
_request_query_count: contextvars.ContextVar[int] = contextvars.ContextVar(
    "request_query_count", default=0
)


def reset_query_count() -> None:
    """Reset query counter for a new request."""
    _request_query_count.set(0)


def increment_query_count() -> None:
    """Increment query counter (called by SQLAlchemy event listener)."""
    _request_query_count.set(_request_query_count.get() + 1)


def get_query_count() -> int:
    """Get current request's query count."""
    return _request_query_count.get()


# How a request ended. `RequestIDMiddleware` supplies this.
#   completed         — the response was fully sent
#   client_disconnect — the client went away mid-response (a skipped track, a closed tab)
#   error             — an exception escaped to ServerErrorMiddleware
OUTCOME_COMPLETED = "completed"
OUTCOME_CLIENT_DISCONNECT = "client_disconnect"
OUTCOME_ERROR = "error"


class MetricsCollector:
    """Collects request metrics and background gauges.

    Thread-safe via threading.Lock. Uses a bounded deque for request records.
    """

    def __init__(self, max_requests: int = 2000):
        self._requests: deque[tuple[float, str, str, int, float, int, str, bool]] = deque(maxlen=max_requests)
        self._gauges: dict[str, Any] = {}
        self._lock = threading.Lock()

    def record_request(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        query_count: int = 0,
        outcome: str = OUTCOME_COMPLETED,
        transfer: bool = False,
    ) -> None:
        """Record an HTTP request that has finished, however it finished.

        Both keyword arguments default to today's behaviour so existing positional call
        sites are unaffected.

        ``transfer`` marks a response whose body is audio or video. Its elapsed time is
        how long the bytes took to move, not how long the server took to think — the
        client reads at playback speed, or hangs up mid-track. Mixing that into the
        latency percentiles makes them meaningless; see ``get_snapshot``.
        """
        with self._lock:
            self._requests.append(
                (time.time(), method, route, status_code, duration_ms, query_count, outcome, transfer)
            )

    def set_gauge(self, name: str, value: Any) -> None:
        """Set a named gauge value."""
        with self._lock:
            self._gauges[name] = value

    @staticmethod
    def _percentiles(durations: list[float]) -> tuple[float, float, float]:
        """(p50, p95, p99) over a duration list, or zeroes if it is empty."""
        if not durations:
            return 0.0, 0.0, 0.0
        s = sorted(durations)
        n = len(s)
        if n == 1:
            return round(s[0], 2), round(s[0], 2), round(s[0], 2)
        return (
            round(s[n // 2], 2),
            round(s[int(n * 0.95)], 2),
            round(s[int(n * 0.99)], 2),
        )

    def get_snapshot(self, window_seconds: int = 300) -> dict[str, Any]:
        """Get metrics snapshot for the given time window.

        Two populations are kept apart, because folding them together produced a p95
        that measured nothing:

        - **Transfers** (``audio/*``, ``video/*``) are reported under ``transfer_*``.
          Their elapsed time is byte-movement, and a client that skips a track hangs up
          mid-response — uvicorn's ``send`` then silently no-ops, so the request still
          records as a clean 200 whose duration is simply how long the listener stayed.
          One skipped track was enough to define ``duration_p95_ms`` for a whole
          five-minute window. ``duration_*`` now covers API responses only and means
          "how quickly does the server answer".
        - **Client disconnects** are counted in ``client_disconnects`` and excluded from
          the percentiles and the error rate. Skipping a track is normal use; counting it
          as a server error would make the rate — and the alarm built on it in
          ``check_pressure_alarms`` — meaningless.
        """
        cutoff = time.time() - window_seconds
        with self._lock:
            recent = [r for r in self._requests if r[0] >= cutoff]
            gauges = dict(self._gauges)

        empty = {
            "window_seconds": window_seconds,
            "total_requests": 0,
            "client_disconnects": 0,
            "transfer_requests": 0,
            "error_rate": 0.0,
            "duration_p50_ms": 0.0,
            "duration_p95_ms": 0.0,
            "duration_p99_ms": 0.0,
            "transfer_p50_ms": 0.0,
            "transfer_p95_ms": 0.0,
            "avg_queries_per_request": 0.0,
            "max_queries_per_request": 0,
            "top_routes": [],
        }
        if not recent:
            return {"request_metrics": empty, "background_gauges": gauges}

        disconnects = [r for r in recent if r[6] == OUTCOME_CLIENT_DISCONNECT]
        served = [r for r in recent if r[6] != OUTCOME_CLIENT_DISCONNECT]
        api = [r for r in served if not r[7]]
        transfers = [r for r in served if r[7]]

        query_counts = [r[5] for r in recent]

        # Route counts cover everything — a route that only ever gets disconnected on is
        # exactly what we want to see.
        route_counts: dict[str, int] = {}
        for r in recent:
            route_counts[r[2]] = route_counts.get(r[2], 0) + 1
        top_routes = sorted(route_counts.items(), key=lambda x: -x[1])[:10]

        api_p50, api_p95, api_p99 = self._percentiles([r[4] for r in api])
        tx_p50, tx_p95, _ = self._percentiles([r[4] for r in transfers])

        # Error rate over served API requests. Transfers are excluded for the same
        # reason as their durations: a 200 that the client walked away from is not a
        # server outcome we can reason about.
        error_count = sum(1 for r in api if r[3] >= 500)

        return {
            "request_metrics": {
                "window_seconds": window_seconds,
                "total_requests": len(recent),
                "client_disconnects": len(disconnects),
                "transfer_requests": len(transfers),
                "error_rate": round(error_count / len(api), 4) if api else 0.0,
                "duration_p50_ms": api_p50,
                "duration_p95_ms": api_p95,
                "duration_p99_ms": api_p99,
                "transfer_p50_ms": tx_p50,
                "transfer_p95_ms": tx_p95,
                "avg_queries_per_request": round(sum(query_counts) / len(recent), 2),
                "max_queries_per_request": max(query_counts) if query_counts else 0,
                "top_routes": [{"route": r, "count": c} for r, c in top_routes],
            },
            "background_gauges": gauges,
        }


def update_background_gauges(collector: MetricsCollector) -> None:
    """Update background gauges from existing infrastructure.

    Called lazily when metrics endpoint is hit. All sources are fast
    (Redis reads + in-memory state).
    """
    from datetime import datetime

    from app.services.background import get_background_manager
    from app.services.background.events import get_recent_background_events
    from app.services.tasks import get_recent_failures

    bg = get_background_manager()

    collector.set_gauge("analysis_queue_depth", bg.get_analysis_task_count())
    collector.set_gauge("sync_running", bg.is_sync_running())
    collector.set_gauge("executor_circuit_breaker_open", bg._executor_disabled)

    # Count completed analyses in last 60s
    now = datetime.now()
    events = get_recent_background_events(limit=50)
    completed_count = 0
    for event in events:
        try:
            ts = datetime.fromisoformat(event.get("timestamp", ""))
            if (now - ts).total_seconds() <= 60 and "complete" in event.get("event", "").lower():
                completed_count += 1
        except (ValueError, TypeError):
            continue
    collector.set_gauge("analysis_completed_per_min", completed_count)

    # Count failures in last 60s
    failures = get_recent_failures(limit=50)
    failure_count = 0
    for failure in failures:
        try:
            ts = datetime.fromisoformat(failure.get("timestamp", ""))
            if (now - ts).total_seconds() <= 60:
                failure_count += 1
        except (ValueError, TypeError):
            continue
    collector.set_gauge("task_failure_rate_per_min", failure_count)

    # Per-phase sync progress gauges
    from app.services.tasks import get_sync_progress

    sync_progress = get_sync_progress()
    if sync_progress and sync_progress.get("status") == "running":
        collector.set_gauge("current_phase", sync_progress.get("phase", "unknown"))
        collector.set_gauge("phase_analyzed", sync_progress.get("tracks_analyzed", 0))
        collector.set_gauge("phase_pending", sync_progress.get("tracks_pending_analysis", 0))
        collector.set_gauge("phase_total", sync_progress.get("tracks_total", 0))

        for phase in ("features", "embeddings", "backfill", "melodic", "mood_tags"):
            requeue = sync_progress.get("phase_requeue_attempts", {}).get(phase, 0)
            stalls = sync_progress.get("phase_stall_recoveries", {}).get(phase, 0)
            forced = sync_progress.get("phase_forced_exit_reasons", {}).get(phase)
            collector.set_gauge(f"phase:{phase}:requeue_attempts", requeue)
            collector.set_gauge(f"phase:{phase}:stall_recoveries", stalls)
            if forced:
                collector.set_gauge(f"phase:{phase}:forced_exit_reason", forced)


# Pressure alarm thresholds
ALARM_ANALYSIS_QUEUE_DEPTH = 500
ALARM_ERROR_RATE = 0.05
ALARM_ERROR_RATE_MIN_REQUESTS = 10
ALARM_TASK_FAILURE_RATE = 5
ALARM_STALL_RECOVERIES = 3
ALARM_P95_LATENCY_MS = 5000


def check_pressure_alarms(snapshot: dict, logger: logging.Logger) -> list[str]:
    """Check metrics snapshot against pressure thresholds.

    Returns list of alarm names that fired. Logs a warning for each.
    """
    alarms: list[str] = []
    req = snapshot.get("request_metrics", {})
    bg = snapshot.get("background_gauges", {})

    # High analysis queue depth
    queue_depth = bg.get("analysis_queue_depth", 0)
    if isinstance(queue_depth, (int, float)) and queue_depth > ALARM_ANALYSIS_QUEUE_DEPTH:
        alarms.append("high_analysis_queue_depth")
        logger.warning(
            "Pressure alarm: analysis queue depth %d exceeds threshold %d",
            queue_depth, ALARM_ANALYSIS_QUEUE_DEPTH,
        )

    # High HTTP error rate (with minimum request count guard)
    total_requests = req.get("total_requests", 0)
    error_rate = req.get("error_rate", 0.0)
    if total_requests >= ALARM_ERROR_RATE_MIN_REQUESTS and error_rate > ALARM_ERROR_RATE:
        alarms.append("high_error_rate")
        logger.warning(
            "Pressure alarm: HTTP error rate %.2f%% exceeds threshold %.2f%% (%d requests)",
            error_rate * 100, ALARM_ERROR_RATE * 100, total_requests,
        )

    # High p95 latency
    p95 = req.get("duration_p95_ms", 0.0)
    if isinstance(p95, (int, float)) and p95 > ALARM_P95_LATENCY_MS:
        alarms.append("high_p95_latency")
        logger.warning(
            "Pressure alarm: p95 latency %.0fms exceeds threshold %dms",
            p95, ALARM_P95_LATENCY_MS,
        )

    # High task failure rate
    failure_rate = bg.get("task_failure_rate_per_min", 0)
    if isinstance(failure_rate, (int, float)) and failure_rate > ALARM_TASK_FAILURE_RATE:
        alarms.append("high_task_failure_rate")
        logger.warning(
            "Pressure alarm: task failure rate %d/min exceeds threshold %d/min",
            failure_rate, ALARM_TASK_FAILURE_RATE,
        )

    # Per-phase stall recoveries
    for phase in ("features", "embeddings", "backfill", "melodic", "mood_tags"):
        stalls = bg.get(f"phase:{phase}:stall_recoveries", 0)
        if isinstance(stalls, (int, float)) and stalls > ALARM_STALL_RECOVERIES:
            alarm_name = f"phase_{phase}_stall_recoveries"
            alarms.append(alarm_name)
            logger.warning(
                "Pressure alarm: phase '%s' stall recoveries %d exceeds threshold %d",
                phase, stalls, ALARM_STALL_RECOVERIES,
            )

    return alarms


# Module-level singleton
_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
