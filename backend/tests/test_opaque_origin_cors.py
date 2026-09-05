"""A sandboxed visualizer can read cover art.

**The bug this pins renders as a grid of plain white cubes, with no error anywhere.** A visualizer
plugin is loaded in an iframe with `sandbox="allow-scripts"` and without `allow-same-origin`
(ADR-0087 point 1), which gives it an opaque origin, so every CORS-checked request it makes arrives
as `Origin: null`. That is not a URL, so it matches neither the allow-list nor `allow_origin_regex`,
and `CORSMiddleware` sends no `Access-Control-Allow-Origin` header.

`beat-tiles` loads the cover with `THREE.TextureLoader` and `setCrossOrigin('anonymous')`. A refused
read lands in its error callback, which sets the texture to `null` — and the scene happily draws
untextured cubes. Nothing logs, nothing throws, and the visualizer looks like it was written that
way.

`familiar-apple` hit the same class of failure for the plugin's *own folder* and fixed it in its
custom scheme handler. Artwork is served from here, so it needs the same answer here.
"""

from __future__ import annotations

import pytest


class TestAnOpaqueOriginMayReadMedia:
    """The headline: `Origin: null` must get a usable header on media reads."""

    @pytest.mark.parametrize("path", ["/api/v1/tracks/x/artwork", "/api/v1/tracks/x/stream"])
    def test_media_answers_a_null_origin(self, client, path):
        # The track need not exist — CORS is decided by middleware, so a 404 carries the header
        # just as a 200 does, and using a real id would make this depend on a seeded library.
        response = client.get(path, headers={"Origin": "null"})
        assert response.headers.get("access-control-allow-origin") == "*", (
            "a sandboxed visualizer cannot read this, and draws untextured white cubes instead"
        )

    def test_credentials_are_not_offered_to_an_opaque_origin(self, client):
        """The narrow part of the fix, and the reason it is not one line in the allow-list.

        Adding `"null"` to `allow_origins` would have let *any* sandboxed document make credentialed
        requests to *every* endpoint. This says only "a drawing surface may see the album cover".
        """
        response = client.get("/api/v1/tracks/x/artwork", headers={"Origin": "null"})
        assert response.headers.get("access-control-allow-credentials") != "true"


class TestItStaysNarrow:
    def test_a_null_origin_gets_nothing_on_a_non_media_path(self, client):
        """An opaque origin has no business reading the library, and does not need to."""
        response = client.get("/api/v1/library/stats", headers={"Origin": "null"})
        assert response.headers.get("access-control-allow-origin") is None

    def test_a_null_origin_cannot_write(self, client):
        """Read-only. The method check is what keeps this from being a general opening."""
        response = client.post("/api/v1/tracks/x/artwork", headers={"Origin": "null"})
        assert response.headers.get("access-control-allow-origin") is None


class TestNormalOriginsAreUnaffected:
    """Blast radius. `CORSMiddleware` still owns every origin that is a real URL."""

    def test_a_browser_origin_still_gets_its_own_echo_not_a_wildcard(self, client):
        response = client.get(
            "/api/v1/tracks/x/artwork", headers={"Origin": "http://localhost:5173"}
        )
        # Echoed rather than `*`, because that request may carry credentials and a wildcard would
        # be rejected by the browser for it.
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_a_request_with_no_origin_gains_no_header(self, client):
        response = client.get("/api/v1/tracks/x/artwork")
        assert response.headers.get("access-control-allow-origin") is None
