"""`scripts/lint_data_paths.py` catches what it says it catches (ADR-0132 point 2)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lint_data_paths.py"
spec = importlib.util.spec_from_file_location("lint_data_paths", SCRIPT)
assert spec and spec.loader
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def test_a_working_directory_data_path_is_refused():
    [problem] = lint.check('cache = Path("data/transcode_cache")\n', "app/api/routes/x.py")
    assert problem.startswith('app/api/routes/x.py:1: Path("data/transcode_cache")')


def test_the_bare_directory_is_refused_too():
    assert lint.check('root = Path("data") / "x"\n', "app/services/y.py")


def test_a_qualified_call_is_caught():
    assert lint.check('import pathlib\np = pathlib.Path("data/outputs.json")\n', "app/services/z.py")


def test_config_is_where_the_paths_are_defined():
    assert lint.check('data_dir = Path("data")\n', "app/config.py") == []


def test_paths_that_merely_contain_data_are_fine():
    assert lint.check('p = Path("/data/art")\nq = Path("metadata/x")\n', "app/services/y.py") == []


def test_the_tree_is_clean():
    assert lint.main() == 0
