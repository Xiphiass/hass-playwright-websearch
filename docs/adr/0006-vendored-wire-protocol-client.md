# The integration speaks the Playwright Server wire protocol directly — no `playwright` dependency

The integration no longer depends on the `playwright` PyPI package. `render.py` connects
to the external `playwright run-server` through a small vendored pure-Python client
(`pw_client.py`) that speaks the server's websocket wire protocol directly over
`aiohttp` (already a Home Assistant dependency). `manifest.json` lists no requirements.

## Why

The `playwright` wheel has **no `musllinux` build** — only `manylinux` (glibc), macOS,
and Windows. Home Assistant OS / Supervised / Container installs run on Alpine Linux
(musl libc), so the config flow failed at dependency install with *"no wheels with a
matching platform tag (e.g. `musllinux_1_2_x86_64`)"*. This is true for every version
(checked through 1.61.0), so bumping the pin cannot fix it. The wheel also bundles a
prebuilt Node.js "driver" binary that isn't built for musl.

Per ADR 0001 this integration embeds no browser — it is purely a websocket *client* that
does `browserType.connect(ws_url)`. But `playwright.connect()` tunnels its frames through
that bundled Node driver, so the whole musl-incompatible package would be dragged in just
to act as a client. Talking the protocol ourselves removes the dependency entirely and
lets the integration install on all HA platforms.

## What the client is (and is not)

`pw_client.py` reproduces only the narrow slice of the async API `render.py` uses —
`async_playwright() -> pw.chromium.connect() -> browser.new_context() ->
context.new_page() -> page.goto()/evaluate()/url -> browser.close()`, plus a
`TimeoutError`. Its public surface deliberately mirrors the real objects so `render.py`
and every test fake stay unchanged; the fake boundary is still `render.async_playwright`.
It is not a general Playwright client and implements no feature beyond that render path.

The wire protocol is one JSON object per websocket text frame: a method call
`{id, guid, method, params, metadata}` gets `{id, result}` or
`{id, error:{error:{name,message,stack}}}` back, alongside object-lifecycle frames
(`__create__`) and per-object events (`navigated`). Connecting with `?browser=chromium`
puts the server in launch mode and exposes a `preLaunchedBrowser` on the root object.

## Cost and risk

This protocol is undocumented and carries no cross-version compatibility guarantee. The
client was built and verified against `playwright run-server` **v1.55.0**
(`mcr.microsoft.com/playwright:v1.55.0-jammy`); a future server version could change the
message shapes. Mitigations: the surface we depend on is tiny and stable (connect →
context → page → goto → evaluate → close), and any protocol/handshake failure degrades to
a structured `status:"error"` (ADR 0003) rather than crashing. A reader tempted to
"just add the `playwright` dependency back" should know it was removed deliberately —
it cannot install on the majority of HA hosts.
