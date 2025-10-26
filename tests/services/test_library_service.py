import pytest

from app.schemas.common import ID
from app.services.library_service import LibraryService


@pytest.fixture()
def library_service() -> LibraryService:
    service = LibraryService()
    service.add_albums(
        [
            {
                "id": "6akEvsycLGftJxYudPjmqK",
                "name": "Discovery",
                "artists": [
                    {
                        "name": "Daft Punk",
                    }
                ],
            }
        ]
    )
    return service


def test_get_album_returns_match_for_string_identifier(library_service: LibraryService) -> None:
    album = library_service.get_album("6akEvsycLGftJxYudPjmqK")

    assert album is not None
    assert str(album.id) == "6akEvsycLGftJxYudPjmqK"


def test_get_album_returns_match_for_id_type(library_service: LibraryService) -> None:
    album = library_service.get_album(ID.validate("6akEvsycLGftJxYudPjmqK"))

    assert album is not None
    assert str(album.id) == "6akEvsycLGftJxYudPjmqK"


def test_get_album_returns_none_for_mismatched_identifier(library_service: LibraryService) -> None:
    assert library_service.get_album("1cTZMwcBJT0Ka3UJPXOeeN") is None
