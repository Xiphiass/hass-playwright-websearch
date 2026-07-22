Guidance for AI agents working in this repo. Human-facing overview lives in
[`README.md`](README.md); domain vocabulary in [`CONTEXT.md`](CONTEXT.md).

## What this is

A Home Assistant custom integration that gives a conversation agent's LLM web-search
tools returning the *rendered* text of pages, not just snippets. The integration runs in
HA Core and owns all render/extract/budget logic; it drives an **external** Playwright
Server over websocket (`browserType.connect`) and embeds no Chromium itself. SearXNG
supplies result URLs/snippets. See [`CONTEXT.md`](CONTEXT.md) for the glossary and
`docs/adr/` for the six architecture decisions.

## Layout

- `custom_components/playwright_websearch/` — the integration.
  - `render.py` — **the single seam.** `render_page()` does connect-per-call, renders, and
    returns a structured `RenderResult` (`{status, title, final_url, text, word_count,
    error?}`); it never raises for render problems (ADR 0003). All fake-boundary tests
    patch `render.async_playwright`.
  - `pw_client.py` — vendored pure-Python client for the Playwright Server wire protocol
    (ADR 0006). `render.py` imports `async_playwright`/`TimeoutError` from here, not the
    `playwright` package (which has no musllinux wheel). Mirrors just the object surface
    `render.py` uses, so the fake boundary is unchanged.
  - `llm_api.py` — `WebSearchAPI(llm.API)` + the `Tool` subclasses (currently `open_url`).
  - `config_flow.py` — config flow (SearXNG + Playwright ws URLs) and options flow (tunables).
  - `const.py` — `DOMAIN`, config keys, and `DEFAULT_*` tunables.
- `tests/` — `pytest-homeassistant-custom-component`. `conftest.py` holds the fake
  Playwright client and fake SearXNG response — the baseline all tests build on.

## Conventions

- **Respect the ADRs** in `docs/adr/` — they encode deliberate decisions (external
  browser, integration-owns-extraction, structured render result, SSRF-in-integration,
  no HTTP fallback, vendored wire-protocol client). Don't reintroduce an
  `aiohttp`/BeautifulSoup fetch path, and don't re-add the `playwright` dependency
  (ADR 0006: no musllinux wheel).
- **Test through the fake boundary**, not internals: fake the Playwright client + SearXNG
  response and assert the tools' returned structure. No real Chromium, no network.
- Run tests with `pytest` (see [`README.md`](README.md) for venv setup).
- This is an active rewrite; several features (`search_web`, budget, SSRF, extraction,
  snippet fallback) are planned but not yet built — check open issues before assuming.

## Workflow

- Whenever working on a new feature, pull the latest changes from `main` and create a new branch for your work.
- You are allowed to push changes and open PRs automatically (via the `gh` CLI) without asking for confirmation first.
