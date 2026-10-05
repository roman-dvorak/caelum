from fastapi.testclient import TestClient

from caelum.api.app import create_app


def test_extra_cors_origin_is_allowed():
    client = TestClient(create_app(cors_origins=("https://roman-dvorak.github.io",)))
    res = client.options(
        "/api/files",
        headers={"Origin": "https://roman-dvorak.github.io", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers["access-control-allow-origin"] == "https://roman-dvorak.github.io"


def test_unknown_origin_is_not_allowed():
    client = TestClient(create_app(cors_origins=("https://roman-dvorak.github.io",)))
    res = client.options(
        "/api/files",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in res.headers
