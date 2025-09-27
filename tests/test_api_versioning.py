from tests.helpers import api_path


def test_versioned_root_available(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"


def test_legacy_path_disabled_by_default(client) -> None:
    legacy_response = client.get(api_path("/status"))
    assert legacy_response.status_code == 200

    response = client.get("/status", use_raw_path=True)
    assert response.status_code == 404
    problem = response.json()
    assert problem.get("detail") == "Not Found"
