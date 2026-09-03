"""Settings in the deployment files that are load-bearing and silent when wrong.

Every assertion here corresponds to something that broke on 2026-09-02 and gave
no error when it did. That is the common thread: none of these fail loudly. They
degrade — to the CPU, to one worker, to a model directory that is shadowed — and
the system carries on returning correct-looking results.

They are asserted here because the alternative is noticing months later, or not
at all. A stale branch nearly reverted two of them the same day they were added:
one would have removed `compute` from the driver capabilities, the other pinned
the embedder back to a commit that segfaults.

Deliberately reads the files as text and YAML rather than starting anything, so
it runs in CI with no Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "docker" / "docker-compose.prod.yml"
GPU_COMPOSE = REPO_ROOT / "docker" / "docker-compose.gpu.yml"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"


@pytest.fixture(scope="module")
def prod() -> dict:
    if not PROD_COMPOSE.is_file():
        pytest.skip(f"{PROD_COMPOSE} not found")
    return yaml.safe_load(PROD_COMPOSE.read_text())


def _api_environment() -> dict[str, str]:
    """The api service's environment, outside the fixture, for module-level use."""
    entries = yaml.safe_load(PROD_COMPOSE.read_text())["services"]["api"]["environment"]
    out = {}
    for entry in entries:
        key, _, value = str(entry).partition("=")
        out[key] = value
    return out


@pytest.fixture(scope="module")
def api_env(prod: dict) -> dict[str, str]:
    entries = prod["services"]["api"]["environment"]
    out = {}
    for entry in entries:
        key, _, value = str(entry).partition("=")
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------


def test_driver_capabilities_include_compute(api_env: dict[str, str]) -> None:
    """`utility` alone gives nvidia-smi and NVML but **not** `libcuda.so`.

    With only `utility`, the GPU appears present, the devices are injected, and
    CUDA still cannot initialise — so ONNX Runtime falls back to the CPU without
    raising. Everything keeps working at a quarter of the speed.
    """
    caps = api_env.get("NVIDIA_DRIVER_CAPABILITIES", "")
    assert "compute" in caps, (
        "NVIDIA_DRIVER_CAPABILITIES must include `compute`, or libcuda.so never "
        f"reaches the container and the GPU is silently unused (got {caps!r})"
    )


def test_the_gpu_reservation_is_not_in_the_default_compose(prod: dict) -> None:
    """An unsatisfiable device reservation is **fatal**, not ignored.

        Error response from daemon: could not select device driver "nvidia"
        with capabilities: [[gpu]]

    Putting it in the default file stops every installation without an NVIDIA
    card from starting at all.
    """
    reservations = (
        prod["services"]["api"].get("deploy", {}).get("resources", {}).get("reservations", {})
    )
    assert "devices" not in reservations, (
        "the nvidia device reservation belongs in docker-compose.gpu.yml, which "
        "is opted into; in the default file it breaks every GPU-less host"
    )


def test_the_gpu_override_exists_and_requests_a_device() -> None:
    """The opt-in file has to actually do the thing it exists for."""
    if not GPU_COMPOSE.is_file():
        pytest.fail(f"{GPU_COMPOSE} is missing; GPU hosts have nothing to opt into")
    devices = (
        yaml.safe_load(GPU_COMPOSE.read_text())["services"]["api"]["deploy"]["resources"][
            "reservations"
        ]["devices"]
    )
    assert any(d.get("driver") == "nvidia" for d in devices)


# ---------------------------------------------------------------------------
# Throughput
# ---------------------------------------------------------------------------


def test_the_analysis_worker_count_is_set(api_env: dict[str, str]) -> None:
    """Unset means one worker against a six-CPU allowance.

    Measured on the deployment host: 15.7s/track at one worker against 11.3s at
    three. Nothing fails without it; the machine is just mostly idle.
    """
    assert "MAX_ANALYSIS_WORKERS" in api_env, (
        "without this the pool defaults to a single worker and most of the CPU "
        "limit below it goes unused"
    )


# ---------------------------------------------------------------------------
# Model artifacts
# ---------------------------------------------------------------------------


def test_the_model_dir_is_not_inside_a_mounted_volume() -> None:
    """A named volume mounts over whatever the image put at that path.

    Named volumes copy the image's contents in **once, at creation**. Shipping
    the encoders to /app/data/models put them in the image and hid them from
    every container whose volume predated them — while `docker run` with no
    volumes, which is how CI smoke-tests the image, saw them perfectly.
    """
    if not DOCKERFILE.is_file():
        pytest.skip("Dockerfile not found")
    text = DOCKERFILE.read_text()
    line = next(
        (line for line in text.splitlines() if line.strip().startswith("ENV CLAPBACK_MODEL_DIR")),
        None,
    )
    assert line is not None, "CLAPBACK_MODEL_DIR is not set in the image"

    model_dir = line.split("=", 1)[1].strip()
    mounted = {
        str(v).split(":")[1]
        for v in yaml.safe_load(PROD_COMPOSE.read_text())["services"]["api"].get("volumes", [])
        if ":" in str(v)
    }
    for mount in mounted:
        assert not model_dir.startswith(mount.rstrip("/") + "/"), (
            f"CLAPBACK_MODEL_DIR ({model_dir}) is under the volume mounted at "
            f"{mount}, which will hide it on any installation whose volume "
            "predates the artifacts"
        )


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_the_executor_reset_url_in_error_messages_is_real() -> None:
    """The one instruction emitted at the moment you are stuck must work.

    When the process pool breaks, the executor disables itself and logs a URL to
    POST to. That URL was `/api/v1/analysis/reset-executor`, which returns 405 —
    the route is `/analysis/executor/reset` under the library router's prefix.
    Found at 05:00 while trying to un-stick a re-analysis that had been dead for
    half an hour, by following the instruction the software gave.
    """
    root = Path(__file__).resolve().parents[1] / "app"
    executors = root / "services" / "background" / "executors.py"
    routes = root / "api" / "routes" / "library_analysis.py"
    if not executors.is_file() or not routes.is_file():
        pytest.skip("source not found")

    text = executors.read_text()
    assert "/api/v1/analysis/reset-executor" not in text, (
        "that path 405s; the route is /analysis/executor/reset under the library "
        "router's prefix"
    )
    assert '@router.post("/analysis/executor/reset"' in routes.read_text(), (
        "the route named in the error message must exist"
    )
    assert "/api/v1/library/analysis/executor/reset" in text


def test_executor_auto_recovery_is_enabled_in_production() -> None:
    """A broken pool otherwise stays broken until somebody notices.

    One worker crash breaks the ProcessPoolExecutor; every task after it then
    fails against the dead pool until the circuit breaker disables the executor
    outright — 10,283 consecutive failures on 2026-09-03 — and it stays disabled
    until a manual POST. Nothing errors at the API; the library just stops being
    analysed. The default is off, which is defensible for a desktop and wrong for
    an unattended server.
    """
    value = _api_environment().get("EXECUTOR_AUTO_RECOVERY_ENABLED", "")
    # Compose interpolation: `${VAR:-default}` is the right shape here, since an
    # operator may want it off. What must hold is that the *default* is on.
    match = re.fullmatch(r"\$\{[A-Z_]+:-(.*)\}", value.strip())
    effective = match.group(1) if match else value
    assert effective.strip().lower() == "true", (
        "without this a single worker crash halts analysis permanently and "
        f"silently (resolves to {effective!r})"
    )
