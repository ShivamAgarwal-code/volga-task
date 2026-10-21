"""Smoke tests for the API surface.

These stub out storage and the Celery enqueue so the tests run with no Postgres,
Redis, MinIO, or Whisper model present — they exercise the HTTP contract, not the
transcription itself. A real suite would add an integration test that runs a tiny
clip end-to-end through a worker.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Patch external side-effects before importing the app.
    with patch("app.storage.ensure_bucket"), \
         patch("app.storage.put_audio"), \
         patch("app.database.init_db"), \
         patch("app.worker.transcribe_job.delay"):
        from app.main import app
        with TestClient(app) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_rejects_non_audio(client):
    resp = client.post(
        "/transcriptions",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415


def test_accepts_audio_returns_job_id(client):
    with patch("app.main.put_audio"):
        resp = client.post(
            "/transcriptions",
            files={"file": ("clip.mp3", b"\x00\x01\x02", "audio/mpeg")},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "pending"
