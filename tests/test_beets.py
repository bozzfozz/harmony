from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.beets_client import BeetsClient, BeetsClientError
from app.routers import beets_router


@pytest.fixture()
def api_client() -> TestClient:
    app = FastAPI()
    app.include_router(beets_router.router, prefix="/beets")
    return TestClient(app)


def _completed(args: Sequence[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=list(args), returncode=0, stdout=stdout, stderr="")


DEFAULT_RUN_KWARGS = {
    "capture_output": True,
    "text": True,
    "check": True,
    "timeout": 60.0,
}


def _assert_run_called(
    mock_run: MagicMock,
    expected_args: Sequence[str],
    *,
    env: dict | None = None,
) -> None:
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert list(args[0]) == list(expected_args)
    expected_kwargs = dict(DEFAULT_RUN_KWARGS)
    if env is not None:
        expected_kwargs["env"] = env
    assert kwargs == expected_kwargs


class TestImportFile:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "import", "-q", "track.mp3"], "imported\n")

        client = BeetsClient()

        result = client.import_file("track.mp3")

        assert result == "imported"
        _assert_run_called(mock_run, ["beet", "import", "-q", "track.mp3"])

    @patch("app.core.beets_client.subprocess.run")
    def test_options(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "import", "-A", "file.mp3"])

        client = BeetsClient()

        client.import_file(Path("file.mp3"), quiet=False, autotag=False)

        _assert_run_called(mock_run, ["beet", "import", "-A", "file.mp3"])

    @patch("app.core.beets_client.subprocess.run")
    def test_called_process_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "import"], stderr="boom"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.import_file("track.mp3")

    @patch("app.core.beets_client.subprocess.run")
    def test_unexpected_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("missing beet")

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.import_file("track.mp3")


class TestUpdate:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "update"], "done\n")

        client = BeetsClient()

        result = client.update()

        assert result == "done"
        _assert_run_called(mock_run, ["beet", "update"])

    @patch("app.core.beets_client.subprocess.run")
    def test_with_path(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "update", "/library"])

        client = BeetsClient()

        client.update("/library")

        _assert_run_called(mock_run, ["beet", "update", "/library"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, ["beet", "update"])

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.update()


class TestListAlbums:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "ls", "-a"], "One\nTwo\n")

        client = BeetsClient()

        result = client.list_albums()

        assert result == ["One", "Two"]
        _assert_run_called(mock_run, ["beet", "ls", "-a"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, ["beet", "ls", "-a"])

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.list_albums()


class TestListTracks:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed([
            "beet",
            "ls",
            "-f",
            "$title",
        ], "Foo\nBar\n")

        client = BeetsClient()

        result = client.list_tracks()

        assert result == ["Foo", "Bar"]
        _assert_run_called(mock_run, ["beet", "ls", "-f", "$title"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "ls", "-f", "$title"]
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.list_tracks()


class TestStats:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "stats"], "tracks: 42\n")

        client = BeetsClient()

        result = client.stats()

        assert result == {"tracks": "42"}
        _assert_run_called(mock_run, ["beet", "stats"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, ["beet", "stats"])

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.stats()

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "stats"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.stats()

        assert str(exc.value) == "Command timed out"


class TestAvailability:
    @patch("app.core.beets_client.subprocess.run")
    def test_available(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "version"], "beets 1.6\n")

        client = BeetsClient()

        assert client.is_available() is True
        _assert_run_called(mock_run, ["beet", "version"])

    @patch("app.core.beets_client.subprocess.run")
    def test_not_available(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, ["beet", "version"])

        client = BeetsClient()

        assert client.is_available() is False


class TestRemove:
    @patch("app.core.beets_client.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            ["beet", "remove", "genre:rock"], "Removed 2 items\n"
        )

        client = BeetsClient()

        result = client.remove("genre:rock")

        assert result == {"success": True, "removed": 2}
        _assert_run_called(mock_run, ["beet", "remove", "genre:rock"])

    @patch("app.core.beets_client.subprocess.run")
    def test_force(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed([
            "beet",
            "remove",
            "-f",
            "genre:rock",
            "year:2020",
        ], "Removed 10 items\n")

        client = BeetsClient()

        result = client.remove("genre:rock year:2020", force=True)

        assert result == {"success": True, "removed": 10}
        _assert_run_called(
            mock_run,
            ["beet", "remove", "-f", "genre:rock", "year:2020"],
        )

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "remove", "genre:rock"], stderr="error"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.remove("genre:rock")

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "remove"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.remove("genre:rock")

        assert str(exc.value) == "Command timed out"

    def test_empty_query(self) -> None:
        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.remove(" ")


class TestMove:
    @patch("app.core.beets_client.subprocess.run")
    def test_without_query(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "move"], "Moved 5 items\n")

        client = BeetsClient()

        result = client.move()

        assert result == {"success": True, "moved": 5}
        _assert_run_called(mock_run, ["beet", "move"])

    @patch("app.core.beets_client.subprocess.run")
    def test_with_query(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            ["beet", "move", "artist:Radiohead"], "Moved 1 items\n"
        )

        client = BeetsClient()

        result = client.move("artist:Radiohead")

        assert result == {"success": True, "moved": 1}
        _assert_run_called(mock_run, ["beet", "move", "artist:Radiohead"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "move"], stderr="fail"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.move()

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "move"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.move()

        assert str(exc.value) == "Command timed out"


class TestWrite:
    @patch("app.core.beets_client.subprocess.run")
    def test_without_query(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "write"], "Wrote 4 items\n")

        client = BeetsClient()

        result = client.write()

        assert result == {"success": True, "written": 4}
        _assert_run_called(mock_run, ["beet", "write"])

    @patch("app.core.beets_client.subprocess.run")
    def test_with_query(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(
            ["beet", "write", "year:2020"], "No changes"
        )

        client = BeetsClient()

        result = client.write("year:2020")

        assert result == {"success": True, "output": "No changes"}
        _assert_run_called(mock_run, ["beet", "write", "year:2020"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "write"], stderr="fail"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.write()

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "write"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.write()

        assert str(exc.value) == "Command timed out"


class TestFields:
    @patch("app.core.beets_client.subprocess.run")
    def test_fields(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed([
            "beet",
            "fields",
        ], "artist\nalbum\n")

        client = BeetsClient()

        result = client.fields()

        assert result == ["artist", "album"]
        _assert_run_called(mock_run, ["beet", "fields"])

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "fields"], stderr="oops"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.fields()

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "fields"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.fields()

        assert str(exc.value) == "Command timed out"


class TestQuery:
    @patch("app.core.beets_client.subprocess.run")
    def test_query(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed([
            "beet",
            "ls",
            "-f",
            "$artist - $title",
            "genre:rock",
            "year:1990",
        ], "Artist - Song\n")

        client = BeetsClient()

        result = client.query("genre:rock year:1990", fmt="$artist - $title")

        assert result == ["Artist - Song"]
        _assert_run_called(
            mock_run,
            [
                "beet",
                "ls",
                "-f",
                "$artist - $title",
                "genre:rock",
                "year:1990",
            ],
        )

    def test_invalid_query(self) -> None:
        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.query("\"")

    @patch("app.core.beets_client.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["beet", "ls"], stderr="boom"
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError):
            client.query("genre:rock")

    @patch("app.core.beets_client.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["beet", "ls"], timeout=60.0
        )

        client = BeetsClient()

        with pytest.raises(BeetsClientError) as exc:
            client.query("genre:rock")

        assert str(exc.value) == "Command timed out"


class TestEnvironment:
    @patch("app.core.beets_client.subprocess.run")
    def test_env_passed(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(["beet", "stats"], "")

        client = BeetsClient(env={"BEETSDIR": "/tmp/beets"})

        client.stats()

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["env"]["BEETSDIR"] == "/tmp/beets"
        assert kwargs["timeout"] == 60.0


class TestRouterImport:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_import_options(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = "Imported"

        response = api_client.post(
            "/beets/import",
            json={"path": "music", "quiet": False, "autotag": False},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "Imported"}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "import_file"
        assert call_args.args[1] == "music"
        assert call_args.kwargs == {"quiet": False, "autotag": False}


class TestRouterRemove:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_remove(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = {"success": True, "removed": 5}

        response = api_client.post(
            "/beets/remove",
            json={"query": "artist:Metallica year:1986", "force": True},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "removed": 5}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "remove"
        assert call_args.args[1:] == ("artist:Metallica year:1986",)
        assert call_args.kwargs == {"force": True}

    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_remove_invalid_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.side_effect = BeetsClientError("Invalid query syntax: missing quote")

        response = api_client.post(
            "/beets/remove",
            json={"query": "artist:'Bad", "force": False},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid query syntax"

    def test_remove_empty_query(self, api_client: TestClient) -> None:
        response = api_client.post("/beets/remove", json={"query": ""})

        assert response.status_code == 400
        assert response.json()["detail"] == "Query must not be empty"


class TestRouterMove:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_move_with_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = {"success": True, "moved": 2}

        response = api_client.post(
            "/beets/move",
            json={"query": "artist:Radiohead"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "moved": 2}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "move"
        assert call_args.args[1:] == ("artist:Radiohead",)
        assert call_args.kwargs == {}

    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_move_without_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = {"success": True, "moved": 4}

        response = api_client.post("/beets/move", json={})

        assert response.status_code == 200
        assert response.json() == {"success": True, "moved": 4}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "move"
        assert call_args.args[1:] == (None,)
        assert call_args.kwargs == {}

    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_move_client_error(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.side_effect = BeetsClientError("Command failed")

        response = api_client.post("/beets/move", json={})

        assert response.status_code == 500
        assert response.json()["detail"] == "Command failed"


class TestRouterWrite:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_write_with_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = {"success": True, "written": 3}

        response = api_client.post(
            "/beets/write",
            json={"query": "year:2020"},
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "written": 3}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "write"
        assert call_args.args[1:] == ("year:2020",)
        assert call_args.kwargs == {}

    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_write_without_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = {"success": True, "output": "done"}

        response = api_client.post("/beets/write", json={})

        assert response.status_code == 200
        assert response.json() == {"success": True, "output": "done"}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "write"
        assert call_args.args[1:] == (None,)
        assert call_args.kwargs == {}


class TestRouterFields:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_fields(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = ["artist", "album"]

        response = api_client.get("/beets/fields")

        assert response.status_code == 200
        assert response.json() == {"fields": ["artist", "album"]}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "fields"
        assert call_args.args[1:] == ()
        assert call_args.kwargs == {}


class TestRouterQuery:
    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_query(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.return_value = ["Artist - Song"]

        response = api_client.post(
            "/beets/query",
            json={"query": "genre:rock", "format": "$artist - $title"},
        )

        assert response.status_code == 200
        assert response.json() == {"results": ["Artist - Song"]}
        mock_pool.assert_awaited_once()
        call_args = mock_pool.await_args
        method = call_args.args[0]
        assert method.__self__ is beets_router.beets_client
        assert method.__name__ == "query"
        assert call_args.args[1:] == ("genre:rock",)
        assert call_args.kwargs == {"fmt": "$artist - $title"}

    @patch("app.routers.beets_router.run_in_threadpool", new_callable=AsyncMock)
    def test_query_invalid(self, mock_pool: AsyncMock, api_client: TestClient) -> None:
        mock_pool.side_effect = BeetsClientError("Invalid query syntax: ")

        response = api_client.post(
            "/beets/query",
            json={"query": '"'},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid query syntax"

