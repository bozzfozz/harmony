"""Tests for the Spotify FREE playlist ingest endpoint."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from tests.simple_client import SimpleTestClient

from app.db import session_scope
from app.models import ImportBatch, ImportSession


def _make_playlist_id(index: int) -> str:
    return f"A{index:021d}"[:22]


def test_accepts_valid_playlist_urls_with_query_stripped(
    client: SimpleTestClient,
) -> None:
    response = client.post(
        "/imports/free",
        json={
            "links": [
                "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=foo",
                " https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk \t",
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["accepted_count"] == 2
    assert payload["data"]["skipped"] == []
    assert payload["data"]["rejected"] == []

    session_id = payload["data"]["import_session_id"]

    with session_scope() as db_session:
        session_record = db_session.execute(
            select(ImportSession).where(ImportSession.id == session_id)
        ).scalar_one()
        assert session_record.mode == "FREE"
        batches = (
            db_session.execute(
                select(ImportBatch).where(ImportBatch.session_id == session_id)
            )
            .scalars()
            .all()
        )
        playlist_ids = {batch.playlist_id for batch in batches}
    assert playlist_ids == {"37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DX4JAvHpjipBk"}


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/user/spotify",
        "https://open.spotify.com/artist/42",
        "https://open.spotify.com/album/42",
        "https://open.spotify.com/track/42",
        "spotify:user:foobar",
    ],
)
def test_rejects_non_playlist_urls(url: str, client: SimpleTestClient) -> None:
    response = client.post(
        "/imports/free",
        json={
            "links": [
                url,
                "https://open.spotify.com/playlist/37i9dQZF1DWXRqgorJj26U",
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    rejected = payload["data"]["rejected"]
    reasons = {item["reason"] for item in rejected}
    assert "NOT_A_PLAYLIST_URL" in reasons or "UNSUPPORTED_URL" in reasons
    rejected_urls = {item["url"] for item in rejected}
    assert url.strip() in rejected_urls
    assert payload["data"]["accepted_count"] == 1


def test_deduplicates_same_playlist_multiple_links(client: SimpleTestClient) -> None:
    response = client.post(
        "/imports/free",
        json={
            "links": [
                "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk",
                "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk?si=dup",
                "spotify:playlist:37i9dQZF1DX4JAvHpjipBk",
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["accepted_count"] == 1
    assert len(payload["data"]["skipped"]) == 2
    assert payload["data"]["rejected"] == []


def test_handles_json_csv_txt_payloads(client: SimpleTestClient) -> None:
    csv_body = "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk,https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    txt_body = "https://open.spotify.com/playlist/37i9dQZF1DXbTxeAdrVG2l\nhttps://open.spotify.com/playlist/37i9dQZF1DX1lVhptIYRda"

    csv_response = client.post(
        "/imports/free",
        data=csv_body,
        content_type="text/csv",
    )
    txt_response = client.post(
        "/imports/free",
        data=txt_body,
        content_type="text/plain",
    )

    assert csv_response.status_code == 200
    assert txt_response.status_code == 200
    assert csv_response.json()["data"]["accepted_count"] == 2
    assert txt_response.json()["data"]["accepted_count"] == 2


def test_soft_overlimit_returns_partial_success(client: SimpleTestClient) -> None:
    limit = 1_000
    links = [
        f"https://open.spotify.com/playlist/{_make_playlist_id(i)}"
        for i in range(limit + 200)
    ]
    response = client.post(
        "/imports/free",
        json={"links": links},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["accepted_count"] == limit
    assert len(payload["data"]["skipped"]) == 200

    session_id = payload["data"]["import_session_id"]
    with session_scope() as db_session:
        accepted_batches = (
            db_session.execute(
                select(ImportBatch).where(ImportBatch.session_id == session_id)
            )
            .scalars()
            .all()
        )
    assert len(accepted_batches) == limit


def test_hard_overlimit_returns_413(client: SimpleTestClient) -> None:
    hard_limit = 10_000 + 1
    links = [
        f"https://open.spotify.com/playlist/{_make_playlist_id(i)}"
        for i in range(hard_limit)
    ]
    response = client.post(
        "/imports/free",
        json={"links": links},
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["ok"] is False
    error = payload["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "exceeds hard limit" in error["message"]
