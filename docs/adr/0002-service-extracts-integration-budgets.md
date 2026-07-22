# The integration owns render/extract/budget; the Playwright Server only provides a browser

Because the external Playwright Server is a raw browser (no HTTP endpoint, no
extraction — see ADR 0001), the integration owns the full pipeline: connect over
websocket, `page.goto`, wait for render, extract main content, apply the Content
Budget. Extraction is done by injecting Readability-style JS into the *remote* browser
page and returning only the compact text over the websocket — so the CPU-heavy parse
runs on the render box, not HA Core.

## Why

Two problems, one decision. Keeping the parse in the remote browser keeps it off HA
Core (consistent with why the browser is external at all) and keeps the websocket
payload small. And Readability-style extraction is the biggest lever on the "content
fetched but answers still bad" failure — it hands the LLM the actual article instead
of nav/boilerplate, which the prior tag-stripping heuristic did poorly.

## Note

An earlier draft of this ADR assumed a smart service would extract and return clean
text over a tiny HTTP contract. That was invalidated once the target container was
pinned to the raw Microsoft Playwright Server. The extraction *location* (remote
browser) is preserved; the *owner* is now the integration, not a service.
