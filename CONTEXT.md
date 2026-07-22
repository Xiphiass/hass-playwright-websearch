# HASS Playwright Web Search

A Home Assistant custom integration that gives a conversation agent's LLM web-search
tools which return the *rendered* text of result pages, not just search snippets.
It fixes two failures of the prior HTTP-fetch approach: JavaScript-rendered pages
returning empty shells, and poor extraction/budgeting starving the LLM of the
relevant passage.

## Language

**Integration**:
The Home Assistant custom component that runs inside HA Core. It registers the LLM
tools AND owns all render/extract/budget logic. It drives a remote browser over
websocket using the Playwright client library (a manifest dependency); it does not run
Chromium itself.

**Playwright Server**:
The external, off-the-shelf `mcr.microsoft.com/playwright` (a.k.a. Docker Hub
`microsoft/playwright`) container running `playwright run-server`. It exposes only a
raw websocket the integration connects to via `browserType.connect`; it provides a
browser and nothing else — no HTTP render endpoint, no extraction. Its endpoint is
user-configurable, mirroring the SearXNG dependency. We do not own or build it.
_Avoid_: rendering service, render service, browser service (it is not a service that
renders-to-text; it is a raw browser server)

**SearXNG**:
The user-supplied metasearch instance queried for result URLs and snippets. Existing
dependency, unchanged.

**Snippet**:
The short text SearXNG returns per result. The *only* fallback when a render fails or
the Playwright Server is unavailable — there is no HTTP-fetch fallback tier.

**Rendered Content**:
The readable text the integration extracts from a page *after* the remote browser
executes its JavaScript. Extraction runs as JS injected into the remote browser page
(Readability-style), so the heavy parse stays off HA Core; only compact text returns
over the websocket.
_Avoid_: page content, extracted text (use "Rendered Content")

**Content Budget**:
The character allowance for Rendered Content returned to the LLM. Two-tier: `search_web`
returns a short per-result extract (per-page cap, capped by a total ceiling) so the LLM
can judge relevance; `open_url` returns the full article (large single-page cap) for a
deep read. Truncation cuts on the nearest paragraph boundary below the cap, never
mid-word. Replaces the old even-divided global budget.
