from __future__ import annotations

from app.db import session_scope
from app.utils.service_health import (collect_missing_credentials,
                                      evaluate_service_health)


def test_evaluate_service_health_handles_mixed_case_service_names() -> None:
    with session_scope() as session:
        result = evaluate_service_health(session, "SpOtIfY")

    assert result.service == "spotify"


def test_collect_missing_credentials_handles_mixed_case_names() -> None:
    with session_scope() as session:
        missing = collect_missing_credentials(session, ("Spotify",))

    assert missing == {} or "spotify" in missing
