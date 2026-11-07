"""The Apple app's embedded visualizer page may call its server's API (ADR-0164 point 2).

It loads from the app bundle as `familiar-visualizer://bundle`. That origin matched nothing, so every
preflight was a 400, and a preflight is what a request carrying `X-Familiar-Token` or `X-Profile-ID`
always triggers. Artwork was exempt, so the page looked fine while track features, the ranking behind
Match to the Music and lyrics all failed. This was measured against a running server on 2026-11-06.
"""

PAGE = "familiar-visualizer://bundle"


def _preflight(client, origin: str, path: str = "/api/v1/tracks/x/lyrics"):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-familiar-token, x-profile-id",
        },
    )


def test_the_page_passes_preflight_with_the_token_and_profile_headers(client):
    response = _preflight(client, PAGE)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == PAGE


def test_the_ranking_post_is_allowed_too(client):
    response = client.options(
        "/api/v1/tracks/x/visualizer-ranking",
        headers={"Origin": PAGE, "Access-Control-Request-Method": "POST"},
    )
    assert response.headers.get("access-control-allow-origin") == PAGE


def test_only_that_scheme_and_host(client):
    for origin in ("familiar-visualizer://elsewhere", "other-scheme://bundle", "null"):
        assert _preflight(client, origin).headers.get("access-control-allow-origin") is None
