"""Render a page via the external Playwright Server.

This module is the single fake-boundary seam for the whole render pipeline. Everything
above ``page`` (result assembly, and — in later tickets — extraction, budgeting, and
SSRF checks) is exercised in tests by faking the Playwright client here, so no real
Chromium and no network are needed.

Per ADR 0001 the integration embeds no browser: it connects over websocket to an
off-the-shelf Playwright Server via ``browserType.connect`` using a fresh connection
per call (ADR 0001 lifecycle), and per ADR 0003 the render routine returns a structured
result rather than raising for render problems.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from playwright.async_api import async_playwright

_LOGGER = logging.getLogger(__name__)


class RenderResult(TypedDict, total=False):
    """Internal render-result shape (ADR 0003)."""

    status: str  # "ok" | "empty" | "error"
    title: str | None
    final_url: str
    text: str
    word_count: int
    error: str


async def render_page(
    ws_url: str, target_url: str, timeout: int
) -> RenderResult:
    """Connect-per-call, render ``target_url``, return a structured result.

    Never raises for render/connection problems — callers decide fallback from
    ``status`` / ``word_count`` (ADR 0003). A fresh browser connection and context are
    created and torn down per call so the integration survives the Playwright Server
    restarting between calls (ADR 0001).
    """
    timeout_ms = timeout * 1000

    async with async_playwright() as pw:
        browser = None
        try:
            browser = await pw.chromium.connect(ws_url, timeout=timeout_ms)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(
                target_url, wait_until="networkidle", timeout=timeout_ms
            )
            text = await page.inner_text("body")
            title = await page.title()
            final_url = page.url
            word_count = len(text.split())
            return RenderResult(
                status="ok" if word_count else "empty",
                title=title,
                final_url=final_url,
                text=text,
                word_count=word_count,
            )
        except Exception as err:  # noqa: BLE001 - render problems become structured errors
            _LOGGER.debug("Render failed for %s: %s", target_url, err)
            return RenderResult(
                status="error",
                title=None,
                final_url=target_url,
                text="",
                word_count=0,
                error=str(err),
            )
        finally:
            if browser is not None:
                await browser.close()
