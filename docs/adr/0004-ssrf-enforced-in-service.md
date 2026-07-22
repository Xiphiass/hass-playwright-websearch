# SSRF protection is enforced in the integration before driving the remote browser

The integration resolves each LLM-chosen target hostname and refuses loopback,
RFC1918, link-local (169.254/16, incl. cloud metadata), and ULA ranges — checking
after resolution to defeat DNS rebinding — *before* telling the remote browser to
navigate there. The prior `_validate_url` no-op (it returned `True` for everything) is
replaced.

## Why enforcement lives here

The raw Playwright Server does no validation of its own (ADR 0001), and it sits in the
Docker network with internal reach — a browser will happily render internal
dashboards, routers, other containers, or `169.254.169.254`. Since the integration is
the only thing driving it and there is no service layer to enforce a boundary, the
check must live in the integration, before `page.goto`.

## The trade-off recorded

LLM-chosen URLs pointing at private IPs are refused — even though the user's own
SearXNG and Playwright Server endpoints are on private IPs. Those configured endpoints
are trusted config, categorically different from an untrusted, LLM-chosen URL. A page
the LLM just read can prompt-inject it into calling `open_url` against an internal
target. A future reader will ask "why can't I render my internal page when SearXNG is
also internal?" — this is the answer.
