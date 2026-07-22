"""A minimal pure-Python client for the external Playwright Server.

Why this exists: the ``playwright`` PyPI package ships no ``musllinux`` wheel, so it
cannot install on the Alpine-based Home Assistant OS / Container images that most users
run (its wheel also bundles a Node.js "driver" binary that isn't built for musl). Per
ADR 0001 this integration embeds no browser — it only *connects* to an external
``playwright run-server`` over a websocket — yet the full package would be dragged in
just to act as that client. So we speak the server's wire protocol directly here and
drop the dependency entirely.

The public surface deliberately mirrors the slice of the real Playwright async API that
:mod:`.render` uses (``async_playwright() -> pw.chromium.connect() -> browser
.new_context() -> context.new_page() -> page.goto()/evaluate()/url -> browser.close()``)
plus a :class:`TimeoutError`. That keeps ``render.py`` and every test fake unchanged: the
fake boundary is still ``render.async_playwright``.

Wire protocol (undocumented, reverse-engineered against ``playwright run-server``): one
JSON object per websocket **text** frame, no length prefix. A method call is
``{id, guid, method, params, metadata}``; the reply is ``{id, result}`` or
``{id, error:{error:{name,message,stack}}}``. The server also pushes object-lifecycle
frames ``{guid, method:"__create__", params:{type, guid, initializer}}`` and per-object
events such as ``navigated``. The graph is addressed by ``guid``; we track only the few
objects we need. Connecting with ``?browser=chromium`` puts the server in launch mode and
exposes a ``preLaunchedBrowser`` on the root ``Playwright`` object's initializer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

# aiohttp caps incoming frames at 4 MiB by default; a rendered page's extracted text can
# exceed that, so lift the limit (0 = unbounded) to avoid truncating large results.
_MAX_MSG_SIZE = 0


class Error(Exception):
    """A render/connection problem surfaced by the client.

    ``render_page`` wraps every client call in ``try/except Exception`` and turns any
    raise into a structured ``status:"error"`` result (ADR 0003), so raising here never
    escapes to callers.
    """


class TimeoutError(Error):  # noqa: A001 - mirrors playwright's TimeoutError name
    """Raised when a navigation exceeds its timeout (server error name ``TimeoutError``).

    ``render.py`` imports this as ``PlaywrightTimeoutError`` and keeps whatever rendered.
    """


def _with_browser_query(ws_url: str) -> str:
    """Return ``ws_url`` with ``browser=chromium`` in its query string.

    The raw ``playwright run-server`` reads the browser to launch from the ``browser``
    query param; without it the server errors on ``initialize``. An explicitly configured
    ``browser`` is left untouched.
    """
    parts = urlparse(ws_url)
    query = dict(parse_qsl(parts.query))
    query.setdefault("browser", "chromium")
    return urlunparse(parts._replace(query=urlencode(query)))


def _deserialize_value(value: Any) -> Any:
    """Convert a Playwright ``SerializedValue`` into a plain Python value.

    Only the shapes ``_EXTRACT_JS`` can produce need to round-trip: strings ``{s}``,
    numbers ``{n}``, booleans ``{b}``, null/undefined ``{v}``, objects ``{o:[{k,v}]}``
    and arrays ``{a}``. Anything else degrades to ``None`` rather than raising.
    """
    if not isinstance(value, dict):
        return value
    if "s" in value:
        return value["s"]
    if "n" in value:
        return value["n"]
    if "b" in value:
        return value["b"]
    if "v" in value:
        # "null"/"undefined"/"NaN"/"Infinity"/"-Infinity" — none are meaningful here.
        return None
    if "o" in value:
        return {item["k"]: _deserialize_value(item["v"]) for item in value["o"]}
    if "a" in value:
        return [_deserialize_value(item) for item in value["a"]]
    return None


class _Connection:
    """Owns the websocket, request/response correlation, and the object graph."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ws = ws
        self._last_id = 0
        self._callbacks: dict[int, asyncio.Future[Any]] = {}
        # guid -> initializer dict, populated from __create__ frames.
        self._initializers: dict[str, dict[str, Any]] = {}
        # main-frame guid -> latest navigated URL.
        self.frame_urls: dict[str, str] = {}
        self._closed_error: Exception | None = None
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._dispatch(json.loads(msg.data))
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception as err:  # noqa: BLE001 - reader failure fails pending calls
            self._fail_all(err)
            return
        self._fail_all(Error("Playwright server connection closed"))

    def _fail_all(self, err: Exception) -> None:
        self._closed_error = err
        for fut in self._callbacks.values():
            if not fut.done():
                fut.set_exception(err)
        self._callbacks.clear()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg_id:
            fut = self._callbacks.pop(msg_id, None)
            if fut is None or fut.done():
                return
            error = msg.get("error")
            if error and not msg.get("result"):
                detail = error.get("error", error)
                message = detail.get("message", "Playwright error")
                if detail.get("name") == "TimeoutError":
                    fut.set_exception(TimeoutError(message))
                else:
                    fut.set_exception(Error(message))
            else:
                fut.set_result(msg.get("result"))
            return

        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "__create__":
            self._initializers[params["guid"]] = params.get("initializer", {})
        elif method == "navigated" and "url" in params:
            self.frame_urls[msg["guid"]] = params["url"]

    def initializer(self, guid: str) -> dict[str, Any]:
        """Return the initializer the server sent for ``guid`` (``{}`` if unseen)."""
        return self._initializers.get(guid, {})

    async def send(
        self, guid: str, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send one method call and await its result (raises on server error)."""
        if self._closed_error is not None:
            raise self._closed_error
        self._last_id += 1
        msg_id = self._last_id
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._callbacks[msg_id] = fut
        await self._ws.send_str(
            json.dumps(
                {
                    "id": msg_id,
                    "guid": guid,
                    "method": method,
                    "params": params or {},
                    "metadata": {},
                }
            )
        )
        return await fut

    async def close(self) -> None:
        """Cancel the reader and close the websocket (best effort)."""
        self._reader.cancel()
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass


class Page:
    """The slice of the Playwright ``Page`` that :mod:`.render` drives."""

    def __init__(self, connection: _Connection, main_frame_guid: str) -> None:
        self._connection = connection
        self._main_frame_guid = main_frame_guid
        self._goto_url = ""

    async def goto(
        self, url: str, wait_until: str | None = None, timeout: int | None = None
    ) -> None:
        """Navigate the main frame; raise :class:`TimeoutError` on nav timeout."""
        self._goto_url = url
        params: dict[str, Any] = {"url": url}
        if wait_until is not None:
            params["waitUntil"] = wait_until
        if timeout is not None:
            params["timeout"] = timeout
        await self._connection.send(self._main_frame_guid, "goto", params)

    async def evaluate(self, expression: str) -> Any:
        """Evaluate ``expression`` (a JS function) in the main frame and return its value."""
        result = await self._connection.send(
            self._main_frame_guid,
            "evaluateExpression",
            {
                "expression": expression,
                "isFunction": True,
                "arg": {"value": {"v": "undefined"}, "handles": []},
            },
        )
        return _deserialize_value((result or {}).get("value"))

    @property
    def url(self) -> str:
        """The main frame's current URL (final URL after redirects, if navigated)."""
        return self._connection.frame_urls.get(self._main_frame_guid, self._goto_url)


class Context:
    """A browser context that yields a single page."""

    def __init__(self, connection: _Connection, guid: str) -> None:
        self._connection = connection
        self._guid = guid

    async def new_page(self) -> Page:
        result = await self._connection.send(self._guid, "newPage", {})
        page_guid = result["page"]["guid"]
        main_frame_guid = self._connection.initializer(page_guid)["mainFrame"]["guid"]
        return Page(self._connection, main_frame_guid)


class Browser:
    """A connected browser; closing it tears down the whole connection (ADR 0001)."""

    def __init__(self, connection: _Connection, guid: str) -> None:
        self._connection = connection
        self._guid = guid

    async def new_context(self) -> Context:
        result = await self._connection.send(self._guid, "newContext", {})
        return Context(self._connection, result["context"]["guid"])

    async def close(self) -> None:
        try:
            await self._connection.send(self._guid, "close", {})
        except Exception:  # noqa: BLE001 - server may already be gone; still tear down
            pass
        await self._connection.close()


class BrowserType:
    """The ``chromium`` entry point exposing :meth:`connect`."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def connect(self, ws_url: str, timeout: int | None = None) -> Browser:
        """Open the websocket, handshake, and return a connect-per-call :class:`Browser`.

        ``timeout`` is in milliseconds (matching the real API); it bounds the connect and
        handshake. Any failure raises, and ``render.py`` maps it to a structured error.
        """
        timeout_s = (timeout / 1000) if timeout else None
        try:
            return await asyncio.wait_for(self._connect(ws_url), timeout_s)
        except asyncio.TimeoutError as err:
            raise TimeoutError(
                f"Timed out connecting to Playwright server at {ws_url}"
            ) from err

    async def _connect(self, ws_url: str) -> Browser:
        ws = await self._session.ws_connect(
            _with_browser_query(ws_url), max_msg_size=_MAX_MSG_SIZE
        )
        connection = _Connection(ws)
        try:
            result = await connection.send("", "initialize", {"sdkLanguage": "python"})
            playwright_guid = result["playwright"]["guid"]
            prelaunched = connection.initializer(playwright_guid)["preLaunchedBrowser"]
            return Browser(connection, prelaunched["guid"])
        except Exception:
            await connection.close()
            raise


class Playwright:
    """Top-level handle mirroring the object yielded by ``async_playwright()``."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.chromium = BrowserType(session)


@asynccontextmanager
async def async_playwright() -> Any:
    """Yield a :class:`Playwright`, owning the aiohttp session for the call's lifetime.

    A fresh session per call keeps ``render_page``'s signature unchanged (no ``hass`` to
    thread through) and matches the connect-per-call lifecycle of ADR 0001; the session
    and any open websocket are closed on exit.
    """
    session = aiohttp.ClientSession()
    try:
        yield Playwright(session)
    finally:
        await session.close()
