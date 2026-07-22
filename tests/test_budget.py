"""Tests for the Content Budget truncation helper."""

from __future__ import annotations

from custom_components.playwright_websearch.budget import truncate_to_cap


def test_under_cap_is_unchanged() -> None:
    text = "short body of text"
    assert truncate_to_cap(text, 100) == text


def test_prefers_paragraph_boundary() -> None:
    text = "First paragraph.\n\nSecond paragraph that overflows the cap here."
    # Cap lands inside the second paragraph; cut back to the paragraph boundary.
    result = truncate_to_cap(text, 30)
    assert result == "First paragraph."


def test_falls_back_to_word_boundary() -> None:
    text = "one two three four five six seven eight nine ten"
    result = truncate_to_cap(text, 15)
    assert len(result) <= 15
    # Never splits a word: every whitespace-separated token is a whole word.
    assert result == "one two three"


def test_never_splits_a_word() -> None:
    text = "alpha bravo charlie delta echo foxtrot"
    result = truncate_to_cap(text, 20)
    # The kept text is a whole-word prefix of the original.
    assert text.startswith(result)
    assert text[len(result) : len(result) + 1] in ("", " ")


def test_single_word_longer_than_cap_hard_cuts() -> None:
    text = "supercalifragilisticexpialidocious"
    result = truncate_to_cap(text, 10)
    assert result == text[:10]


def test_zero_cap_returns_empty() -> None:
    assert truncate_to_cap("anything", 0) == ""
