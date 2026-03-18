#!/usr/bin/env python3
"""Lint Alembic migration files for chain integrity and convention compliance.

Validates:
  - All revision IDs are ≤ 32 characters (alembic_version column limit)
  - No duplicate revision IDs
  - Every down_revision references an existing revision (or is None for the base)
  - Merge migrations with tuple down_revision have both parents present
  - downgrade() functions have either actual logic or a ``# One-way:`` comment

Exit code 0 on success, 1 with details on failure.
"""

import ast
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
MAX_REVISION_LENGTH = 32


def extract_migration_info(filepath: Path) -> dict:
    """Parse a migration file and extract revision metadata."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))

    info: dict = {"file": filepath.name, "path": filepath}

    def _extract_assign(name: str, value_node: ast.expr) -> None:
        if name == "revision":
            if isinstance(value_node, ast.Constant):
                info["revision"] = value_node.value
        elif name == "down_revision":
            if isinstance(value_node, ast.Constant):
                info["down_revision"] = value_node.value
            elif isinstance(value_node, ast.Tuple):
                info["down_revision"] = tuple(
                    e.value
                    for e in value_node.elts
                    if isinstance(e, ast.Constant)
                )

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and node.value:
                    _extract_assign(target.id, node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value:
                _extract_assign(node.target.id, node.value)

    # Check downgrade function body
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            body = node.body
            # Check if downgrade is just `pass`
            is_bare_pass = (
                len(body) == 1
                and isinstance(body[0], ast.Pass)
            )
            # Check if downgrade is pass with a comment or just an expression string
            is_expr_pass = (
                len(body) == 1
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            )

            if is_bare_pass or is_expr_pass:
                # Check source for "# One-way:" comment
                downgrade_start = node.lineno
                downgrade_end = node.end_lineno or node.lineno
                lines = source.splitlines()
                downgrade_lines = lines[downgrade_start - 1 : downgrade_end]
                has_one_way_comment = any(
                    "# One-way:" in line or "# One-way " in line
                    for line in downgrade_lines
                )
                info["downgrade_type"] = "one-way" if has_one_way_comment else "bare-pass"
            else:
                info["downgrade_type"] = "real"

    return info


def lint_migrations() -> list[str]:
    """Run all lint checks and return a list of error messages."""
    errors: list[str] = []

    if not MIGRATIONS_DIR.is_dir():
        errors.append(f"Migrations directory not found: {MIGRATIONS_DIR}")
        return errors

    files = sorted(MIGRATIONS_DIR.glob("*.py"))
    if not files:
        errors.append("No migration files found")
        return errors

    migrations = []
    for f in files:
        try:
            info = extract_migration_info(f)
            migrations.append(info)
        except Exception as e:
            errors.append(f"{f.name}: Failed to parse: {e}")

    # Build revision index
    revisions: dict[str, dict] = {}

    for m in migrations:
        rev = m.get("revision")
        if not rev:
            errors.append(f"{m['file']}: Missing 'revision' variable")
            continue

        # Check revision ID length
        if len(rev) > MAX_REVISION_LENGTH:
            errors.append(
                f"{m['file']}: Revision ID '{rev}' is {len(rev)} chars "
                f"(max {MAX_REVISION_LENGTH})"
            )

        # Check for duplicates
        if rev in revisions:
            errors.append(
                f"{m['file']}: Duplicate revision ID '{rev}' "
                f"(also in {revisions[rev]['file']})"
            )
        else:
            revisions[rev] = m

    # Validate down_revision references
    for m in migrations:
        rev = m.get("revision")
        down = m.get("down_revision")

        if down is None:
            # Base migration — OK
            continue

        if isinstance(down, tuple):
            # Merge migration
            for parent in down:
                if parent not in revisions:
                    errors.append(
                        f"{m['file']}: Merge down_revision parent '{parent}' "
                        f"not found in any migration"
                    )
        elif isinstance(down, str):
            if down not in revisions:
                errors.append(
                    f"{m['file']}: down_revision '{down}' not found "
                    f"in any migration"
                )

    # Check downgrade() functions
    for m in migrations:
        dt = m.get("downgrade_type")
        if dt == "bare-pass":
            errors.append(
                f"{m['file']}: downgrade() has bare `pass` without "
                f"`# One-way: <reason>` comment"
            )

    return errors


def main() -> int:
    errors = lint_migrations()

    if errors:
        print(f"Migration lint FAILED ({len(errors)} error(s)):\n")
        for err in errors:
            print(f"  - {err}")
        return 1

    # Count migrations for summary
    files = list(MIGRATIONS_DIR.glob("*.py"))
    print(f"Migration lint OK: {len(files)} migrations validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
