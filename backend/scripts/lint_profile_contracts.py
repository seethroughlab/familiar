#!/usr/bin/env python3
"""Lint: ensure mutating route handlers enforce profile authentication.

Scans all route files for POST/PUT/DELETE/PATCH endpoints and checks that
they include RequiredProfile (or CurrentProfile) in their function signature.

Routes in admin/system modules or explicitly allowlisted functions are exempt.
Also checks for non-canonical auth error messages (ad-hoc string raises instead
of FamiliarError subclasses from deps.py).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROUTES_DIR = Path(__file__).resolve().parent.parent / "app" / "api" / "routes"

MUTATING_METHODS = {"post", "put", "delete", "patch"}

# Modules where ALL routes are admin/system operations (no profile needed)
ALLOWLISTED_MODULES = {
    "health",
    "settings",
    "library_sync",
    "library_aggregations",
    "library_albums",
    "library_analysis",
    "library_artists",
    "library_maps",
    "library_missing",
    "library_discover",
    "library_deduplicate",
    "organizer",
    "proposed_changes",
    "outputs",
    "artwork",
    "analysis",
    "background",
    # Still exempt after ADR-0086. Every video operation is keyed by a track, and a video
    # belongs to the library rather than to a listener, so none of them is profile state.
    # The one column that would change this is `track_videos.match_confirmed_by`, which
    # ADR-0085 point 7's match-and-download action is the only plausible caller for — if
    # that ships and writes it, this entry comes off.
    "videos",
    "updates",
    "s3_backup",
    "library",
    # Subpackage modules
    "library_import/quick",
    "library_import/preview",
    "export_import/library",
    "tracks/metadata",
    "tracks/identification",
    "tracks/streaming",
    "tracks/discovery",
}

# Individual functions exempt in otherwise-profiled modules
ALLOWLISTED_FUNCTIONS = {
    # The server token (ADR-0045) is server configuration, not listener state — ADR-0029 point 2's
    # category one. Requiring a profile here would be actively *weaker*: profile IDs are public
    # (GET /api/v1/profiles lists them all, unauthenticated), so it would gate token rotation behind
    # something anyone can read. These routes check the current token instead, which is the
    # credential that actually means something. Listed per-function rather than as a module, because
    # ADR-0045 point 2 sends ALLOWLISTED_MODULES to zero and a new module entry moves it the wrong
    # way.
    ("auth", "issue_token"),
    ("auth", "revoke_token"),
    # Ambient (ADR-0106). Both are POSTs because they carry a body, not because they mutate
    # anything: they rank the library against a track and return the result. There is no profile
    # state to protect, and `AMBIENT`'s `taste_weight` and `max_negative_penalty` are both 0, so a
    # profile id would change no ordering — `radio.py`'s docstring draws exactly this contrast and
    # says radio does not inherit the exemption.
    #
    # **Per-function, and the previous entry was not.** A bare `"ambient"` sat in
    # ALLOWLISTED_MODULES from before ADR-0077 deleted the routes, and stayed there afterwards
    # exempting nothing. It would not have covered this file either way: module keys are paths
    # (`get_module_key`), the routes now live under `listening/`, and the key is
    # `listening/ambient`. The dead entry is removed rather than repointed, per the note above
    # about ADR-0045 point 2 sending ALLOWLISTED_MODULES to zero.
    ("listening/ambient", "seed"),
    ("listening/ambient", "candidates"),
    # Profile creation/registration can't require an existing profile
    ("profiles", "create_profile"),
    ("profiles", "register_profile"),
    ("profiles", "update_profile"),
    ("profiles", "delete_profile"),
    ("profiles", "upload_avatar"),
    ("profiles", "delete_avatar"),
    # Chat uses CurrentProfile (optional context for LLM)
    ("chat", "chat"),
    ("chat", "cancel_chat"),
    # Diagnostics accepts anonymous client logs / admin clear
    ("diagnostics", "ingest_frontend_logs"),
    ("diagnostics", "clear_frontend_logs"),
    # Last.fm uses CurrentProfile (callback flow)
    ("lastfm", "handle_callback"),
    ("lastfm", "disconnect"),
    ("lastfm", "scrobble_track"),
    ("lastfm", "update_now_playing"),
    # Bandcamp search is read-like
    ("bandcamp", "search_bandcamp"),
    # Tracks batch listing uses CurrentProfile
    ("tracks/listing", "get_tracks_batch"),
    # Playlists creation needs profile but is already enforced
    ("playlists/crud", "create_playlist"),
}

# Non-canonical auth error message patterns (should use FamiliarError from deps.py)
AUTH_ERROR_PATTERNS = [
    "Missing profile",
    "Profile required",
    "profile is required",
    "No profile",
    "Unauthorized",
    "Not authenticated",
    "Authentication required",
]


def get_module_key(filepath: Path) -> str:
    """Get module key relative to routes dir (e.g. 'playlists/crud')."""
    rel = filepath.relative_to(ROUTES_DIR)
    parts = list(rel.parts)
    # Remove .py extension from last part
    parts[-1] = parts[-1].removesuffix(".py")
    # Skip __init__ files
    if parts[-1] == "__init__":
        return "/".join(parts[:-1])
    return "/".join(parts)


def find_route_decorators(node: ast.FunctionDef) -> list[str]:
    """Return list of HTTP methods from @router.X decorators."""
    methods = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
            if (
                isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
                and decorator.func.attr in MUTATING_METHODS
            ):
                methods.append(decorator.func.attr.upper())
    return methods


def has_profile_param(node: ast.FunctionDef) -> bool:
    """Check if function has RequiredProfile or CurrentProfile annotation."""
    for arg in node.args.args:
        if arg.annotation:
            ann_str = ast.dump(arg.annotation)
            if "RequiredProfile" in ann_str or "CurrentProfile" in ann_str:
                return True
    return False


def check_auth_error_strings(filepath: Path) -> list[str]:
    """Check for non-canonical auth error message patterns."""
    violations = []
    source = filepath.read_text()
    for i, line in enumerate(source.splitlines(), 1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for pattern in AUTH_ERROR_PATTERNS:
            if pattern.lower() in line.lower() and ("raise" in line.lower() or "HTTPException" in line):
                violations.append(f"  {filepath.relative_to(ROUTES_DIR)}:{i}: non-canonical auth message: {pattern!r}")
    return violations


def lint_file(filepath: Path) -> tuple[list[str], list[str]]:
    """Lint a single route file. Returns (profile_violations, auth_violations)."""
    module_key = get_module_key(filepath)

    # Skip fully allowlisted modules
    if module_key in ALLOWLISTED_MODULES:
        return [], []

    source = filepath.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"  {filepath}: SyntaxError — could not parse"], []

    profile_violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        methods = find_route_decorators(node)
        if not methods:
            continue

        # Check if this specific function is allowlisted
        if (module_key, node.name) in ALLOWLISTED_FUNCTIONS:
            continue

        if not has_profile_param(node):
            method_str = "/".join(methods)
            profile_violations.append(
                f"  {filepath.relative_to(ROUTES_DIR)}:{node.lineno}: "
                f"{method_str} {node.name}() missing RequiredProfile"
            )

    auth_violations = check_auth_error_strings(filepath)

    return profile_violations, auth_violations


def main() -> int:
    route_files = sorted(ROUTES_DIR.rglob("*.py"))
    route_files = [f for f in route_files if f.name != "__init__.py"]

    all_profile_violations: list[str] = []
    all_auth_violations: list[str] = []

    for filepath in route_files:
        pv, av = lint_file(filepath)
        all_profile_violations.extend(pv)
        all_auth_violations.extend(av)

    ok = True

    if all_profile_violations:
        print(f"❌ {len(all_profile_violations)} mutating route(s) missing RequiredProfile:")
        for v in all_profile_violations:
            print(v)
        ok = False

    if all_auth_violations:
        print(f"❌ {len(all_auth_violations)} non-canonical auth error message(s):")
        for v in all_auth_violations:
            print(v)
        ok = False

    if ok:
        print(f"✅ Profile contract lint passed ({len(route_files)} route files checked)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
