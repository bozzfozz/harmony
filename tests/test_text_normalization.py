"""Tests for text normalisation helpers used by the matching engine."""

from __future__ import annotations

from app.utils import text_normalization as tn


def test_normalize_unicode_and_quotes() -> None:
    quoted = "“Beyoncé”"
    assert tn.normalize_quotes(quoted) == '"Beyoncé"'
    assert tn.normalize_unicode(quoted) == '"beyonce"'


def test_generate_track_variants_conservative_noise_removal() -> None:
    title = "Echoes (Remix) (feat. Guest) - Explicit"
    cleaned = tn.clean_track_title(title)
    assert cleaned == "Echoes (Remix)"

    variants = tn.generate_track_variants(title)
    assert title in variants
    assert cleaned in variants
    assert any("remix" in variant.lower() for variant in variants)
    assert all("explicit" not in variant.lower() for variant in variants if variant == cleaned)


def test_generate_album_variants_editions() -> None:
    title = "Mirage (Deluxe Edition) [Remastered]"
    cleaned = tn.clean_album_title(title)
    assert cleaned == "Mirage"

    variants = tn.generate_album_variants(title)
    assert title in variants
    assert cleaned in variants
    assert "mirage" in variants  # normalized variant

    editions = tn.extract_editions(title)
    assert editions == {"deluxe", "remastered"}
