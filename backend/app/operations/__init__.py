"""Application operations: one use case each, no HTTP (ADR-0130 point 4).

An operation is constructed with the collaborators it needs — from `app.container.Services`, by
a dependency in `app/api/deps.py` or by whoever else is the caller — and invoked. It decides the
transaction and job boundaries and returns a domain value; the route that calls it serialises that
value and nothing more. `scripts/lint_boundaries.py` holds this package to that: nothing here may
import FastAPI or Starlette.
"""
