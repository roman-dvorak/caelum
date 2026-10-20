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


def test_default_origins_include_the_viewer_domain(monkeypatch):
    from caelum.settings import load_settings

    monkeypatch.delenv("CAELUM_CORS_ORIGINS", raising=False)
    assert "https://viewer.caelum.astrometers.eu" in load_settings().cors_origins
