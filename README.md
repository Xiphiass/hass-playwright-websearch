# hass-playwright-websearch

A Home Assistant custom integration that gives a conversation agent's LLM web-search
tools which return the *rendered* text of result pages, not just search snippets.

It fixes two failures of the prior HTTP-fetch approach: JavaScript-rendered pages coming
back as empty shells, and poor extraction/budgeting starving the LLM of the relevant
passage. Instead of fetching HTML with `aiohttp`, the integration drives a **real
browser** — an external, off-the-shelf Playwright Server — renders each page (executing
its JavaScript), and returns clean readable text.

## Architecture

- **Integration** — this custom component. It runs inside HA Core, registers the LLM
  tools, and owns all render/extract/budget logic. It drives a remote browser over
  websocket via a small vendored wire-protocol client (no `playwright` dependency — that
  package has no musllinux wheel and won't install on HA OS/Container; see ADR 0006); it
  does **not** run Chromium itself.
- **Playwright Server** — an external `mcr.microsoft.com/playwright` container running
  `playwright run-server`. It exposes a raw websocket the integration connects to via
  `browserType.connect`. Its endpoint is user-configurable, mirroring SearXNG. We do not
  own or build it.
- **SearXNG** — the user-supplied metasearch instance queried for result URLs and
  snippets.

Keeping the browser external works across all HA install types (OS, Supervised,
Container, Core-venv), keeps heavy rendering off HA Core's event loop, and lets
constrained users (e.g. a Raspberry Pi) point at beefier hardware. See `docs/adr/` for
the architectural decisions and `CONTEXT.md` for the glossary.

## Tools

- **`open_url`** — open a single URL and return its full rendered readable text for a
  deep read.
- **`search_web`** — query SearXNG, render each result page in a real browser, and return a budgeted extract. Results past the total ceiling appear as lightweight stubs (url + title) so the LLM can still see the full set and decide to `open_url` one.

## Status

Early development. The current tracer bullet
([issue #2](https://github.com/Xiphiass/hass-playwright-websearch/issues/2)) establishes
the installable skeleton, the config flow, and a working `open_url` path end-to-end
(config → websocket connect → render → tool result), plus the fake-boundary test harness.

`search_web` is now implemented: it queries SearXNG, renders each result page in a real
browser, and returns a budgeted extract. Results past the total ceiling appear as
lightweight stubs (url + title, `source: "stub"`) so the LLM can still see the full set
and decide to `open_url` one. The two-tier Content Budget (total ceiling + per-result cap)
is in place.

All planned features for the tracer bullet are now implemented: paragraph-boundary
truncation, Readability-style extraction, SSRF protection, SearXNG-snippet fallback,
full-page cap, and the two-tier Content Budget. The integration is functional and
ready for real-world testing.

## Requirements

- **Home Assistant 2026.8.1 or newer** — the integration targets versions >= 2026.8.1.

## Installation

1. Copy `custom_components/playwright_websearch/` into your Home Assistant `config/`
   directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for
   **Playwright Web Search**.
4. Enter your SearXNG URL and the Playwright Server websocket URL (e.g.
   `ws://playwright.local:3000`). Tunable defaults (number of results, render timeout,
   content budget, concurrency) can be adjusted later via the integration's options.
5. Assign the **Playwright Web Search** LLM API to your conversation agent.

## Configuration

| Setting | Description |
| --- | --- |
| SearXNG URL | Base URL of your SearXNG metasearch instance. |
| Playwright Server websocket URL | `ws://` endpoint of a Playwright Server. |
| Number of results | How many results to render (breadth vs. speed/tokens). |
| Render timeout | Per-page render time bound, in seconds. |
| Content budget | Per-result cap, total ceiling, and full-page cap (characters). |
| Concurrency | Bound on concurrent page renders within one search. |

## Development

Requirements and tests use `pytest-homeassistant-custom-component`. The one seam is the
Playwright client boundary plus the SearXNG response; both are faked, so the whole
pipeline is testable with no real Chromium and no network.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```
