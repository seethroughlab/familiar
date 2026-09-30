"""Run inside the sandbox by the spike app. Prints one JSON object."""
import json, os, sys, traceback

results = {}

def record(name, fn):
    try:
        results[name] = {"ok": True, "detail": fn()}
    except BaseException as e:  # noqa: BLE001
        results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}

def _square(x):
    return x * x

def _numpy_sum(n):
    import numpy as np
    return float(np.arange(n, dtype="float64").sum())

def spawn_pool():
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with ctx.Pool(2) as pool:
        return pool.map(_square, [1, 2, 3])

def process_pool_executor():
    # What the backend's analysis pool actually is (services/background/executors.py).
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as ex:
        return list(ex.map(_numpy_sum, [10, 100]))

def onnxruntime_loads():
    import onnxruntime
    return {"version": onnxruntime.__version__, "providers": onnxruntime.get_available_providers()}

def music_folder():
    folder = sys.argv[1]
    out = {
        "can_list": sorted(os.listdir(folder)),
        "os_access_W_OK_folder": os.access(folder, os.W_OK),
        "os_access_W_OK_file": os.access(os.path.join(folder, "track.flac"), os.W_OK),
        "os_access_R_OK_file": os.access(os.path.join(folder, "track.flac"), os.R_OK),
    }
    try:
        with open(os.path.join(folder, "written-by-sandbox.txt"), "w") as f:
            f.write("x")
        out["write_new_file"] = "SUCCEEDED (zero-touch broken)"
    except OSError as e:
        out["write_new_file"] = f"denied: {e.strerror} (errno {e.errno})"
    try:
        with open(os.path.join(folder, "track.flac"), "a") as f:
            f.write("x")
        out["append_existing"] = "SUCCEEDED (zero-touch broken)"
    except OSError as e:
        out["append_existing"] = f"denied: {e.strerror} (errno {e.errno})"
    return out

if __name__ == "__main__":
    # The fix under test: sandboxed POSIX semaphores must be named "<app group>/…", and Python
    # takes the prefix of every semaphore name from here.
    if os.environ.get("SPIKE_SEMPREFIX"):
        import multiprocessing
        multiprocessing.current_process()._config["semprefix"] = os.environ["SPIKE_SEMPREFIX"]
        results["semprefix"] = {"ok": True, "detail": os.environ["SPIKE_SEMPREFIX"]}
    record("spawn_pool", spawn_pool)
    record("process_pool_executor", process_pool_executor)
    record("onnxruntime_loads", onnxruntime_loads)
    record("music_folder", music_folder)
    print(json.dumps(results))
