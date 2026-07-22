"""Content Budget truncation.

The character allowance for Rendered Content returned to the LLM (CONTEXT.md). Truncation
cuts on the nearest paragraph boundary below the cap, falling back to a word boundary, and
never splits a word. Kept a standalone pure function so it is unit-testable and reusable by
both budget tiers (``search_web``'s per-result cap and ``open_url``'s full-page cap).
"""

from __future__ import annotations


def truncate_to_cap(text: str, cap: int) -> str:
    """Return ``text`` trimmed to at most ``cap`` characters.

    Prefers cutting on the nearest paragraph boundary (``\\n\\n``) at or below the cap;
    if there is none, cuts on the nearest whitespace boundary so a word is never split.
    Text already within the cap is returned unchanged (only trailing whitespace stripped
    when a cut is made).
    """
    if cap <= 0:
        return ""
    if len(text) <= cap:
        return text

    window = text[:cap]

    # Prefer a paragraph boundary within the window.
    para = window.rfind("\n\n")
    if para > 0:
        return window[:para].rstrip()

    # Fall back to the last whitespace so we never split a word. A word that ends
    # exactly at the cap keeps a trailing space here, so rstrip the result.
    space = window.rfind(" ")
    if space > 0:
        return window[:space].rstrip()

    # A single word longer than the cap: hard-cut rather than return nothing.
    return window.rstrip()
