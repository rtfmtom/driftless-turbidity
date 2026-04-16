"""Lightweight smoke tests that don't require a live database."""

from __future__ import annotations


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "db" in body
    assert "scheduler" in body


def test_imports() -> None:
    """Key modules should import without side effects."""
    import driftless.main  # noqa: F401
    from driftless.config import get_settings
    from driftless.ingest import usgs, sites  # noqa: F401

    get_settings()
