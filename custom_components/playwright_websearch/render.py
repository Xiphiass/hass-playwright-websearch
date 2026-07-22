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

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

_LOGGER = logging.getLogger(__name__)

# Readability-style extraction injected into the remote page (ADR 0002): the heavy
# parse runs on the render box, and only compact text crosses the websocket. It clones
# the body, strips boilerplate (script/nav/header/footer/aside/forms/…), then picks the
# densest text container among article/main/div candidates, falling back to the cleaned
# body. Returns ``{title, text}``.
_EXTRACT_JS = """() => {
  const clone = document.body ? document.body.cloneNode(true) : null;
  if (!clone) {
    return { title: document.title || null, text: "" };
  }
  const strip = "script, style, noscript, nav, header, footer, aside, form, iframe";
  clone.querySelectorAll(strip).forEach((el) => el.remove());
  const candidates = [clone, ...clone.querySelectorAll("article, main, div")];
  let best = clone;
  let bestLen = (clone.innerText || "").trim().length;
  for (const el of candidates) {
    const len = (el.innerText || "").trim().length;
    if (len > bestLen) {
      best = el;
      bestLen = len;
    }
  }
  return { title: document.title || null, text: (best.innerText || "").trim() };
}"""


class RenderResult(TypedDict, total=False):
    """Internal render-result shape (ADR 0003)."""

    status: str  # "ok" | "empty" | "error"
    title: str | None
    final_url: str
    text: str
    word_count: int
    error: str


async def render_page(
    ws_url: str, target_url: str, timeout: int, content_floor: int
) -> RenderResult:
    """Connect-per-call, render ``target_url``, return a structured result.

    Never raises for render/connection problems — callers decide fallback from
    ``status`` / ``word_count`` (ADR 0003). A fresh browser connection and context are
    created and torn down per call so the integration survives the Playwright Server
    restarting between calls (ADR 0001).

    The ``networkidle`` wait is bounded by ``timeout`` (seconds). A navigation that
    times out is not discarded: extraction still runs against whatever is in the DOM,
    and the render is kept as ``ok`` when its ``word_count`` reaches ``content_floor``
    (the polling-forever-SPA case, ADR 0003); below the floor it is ``empty``.
    """
    timeout_ms = timeout * 1000

    async with async_playwright() as pw:
        browser = None
        try:
            browser = await pw.chromium.connect(ws_url, timeout=timeout_ms)
            context = await browser.new_context()
            page = await context.new_page()
            timed_out = False
            try:
                await page.goto(
                    target_url, wait_until="networkidle", timeout=timeout_ms
                )
            except PlaywrightTimeoutError:
                # Keep whatever rendered; extraction below decides ok vs empty.
                timed_out = True
            extracted = await page.evaluate(_EXTRACT_JS)
            text = extracted["text"]
            title = extracted["title"]
            final_url = page.url
            word_count = len(text.split())
            if timed_out:
                status = "ok" if word_count >= content_floor else "empty"
            else:
                status = "ok" if word_count else "empty"
            return RenderResult(
                status=status,
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
