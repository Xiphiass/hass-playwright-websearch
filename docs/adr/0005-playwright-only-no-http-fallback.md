# Playwright is the only render backend — no HTTP-fetch fallback

The prior `aiohttp` + BeautifulSoup fetch path is removed, not kept as a fallback tier.
`search_web` and `open_url` render exclusively via the external Playwright Server. If
that server is unconfigured or down, page content is unavailable and the integration
falls back only to the SearXNG Snippet.

## Why record this

The old fetch code works and the tempting move is to keep it as graceful degradation.
We deliberately don't: the whole point of this rewrite is JS-rendered pages, which the
HTTP path cannot handle, and maintaining two extraction pipelines dilutes the focus.
The accepted cost is a hard dependency on the Playwright Server — a future reader
seeing the deleted fetch code should know its removal was intentional, not an
oversight.
