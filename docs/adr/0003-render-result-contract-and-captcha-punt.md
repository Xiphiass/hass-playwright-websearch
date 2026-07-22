# Render results carry a status; keep partial renders; CAPTCHA detection is out of scope for v1

The integration's internal render routine returns a structured result
(`{ status: "ok" | "empty" | "error", title, final_url, text, word_count, error? }`)
rather than raising for render problems, so callers decide fallback from `status` /
`word_count`. On hard failures the integration falls back to the SearXNG Snippet,
preserving the prior integration's behavior. (There is no service HTTP contract — the
raw Playwright Server has no such API, see ADR 0001 — this is an internal shape.)

Two policies:

- **Keep partial renders.** If navigation times out but `word_count` is above a small
  content floor, return `status: "ok"` with what rendered instead of discarding it.
  This is the polling-forever-SPA case: the useful content is already in the DOM.
- **No CAPTCHA / bot-wall detection in v1.** A challenge page returns a DOM, so it
  looks like success but is junk. Heuristic detection is fragile and an endless
  cat-and-mouse. We accept that a bot-walled result occasionally returns junk and rely
  on the LLM having multiple results. Revisit only if it proves common.

## Why record this

The CAPTCHA punt is a deliberate scope boundary a future reader will question ("why
doesn't it handle Cloudflare?"). Recording it stops that being treated as an oversight.
It is also reinforced by the upstream image's own warning that it is not intended for
visiting untrusted sites (ADR 0001).
