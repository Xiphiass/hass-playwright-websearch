# Rendering runs in an external, configurable Playwright Server — not inside HA Core

The integration does not embed Playwright/Chromium. It connects over websocket to an
external, off-the-shelf Playwright Server (`mcr.microsoft.com/playwright` running
`playwright run-server`) whose endpoint the user configures, exactly as the existing
SearXNG URL is configured. We do not own or build that container.

## Why

Running headless Chromium inside the HA Core process is the tempting default but is
hostile: Chromium is ~300MB+ and spawns a browser process per render, which risks
OOM/multi-second stalls on the Raspberry Pi–class hardware many HA users run; HACS
cannot cleanly ship the Chromium binary; and a heavy render competes with HA's single
asyncio event loop. An HA add-on would isolate it but only works on HA OS/Supervised,
excluding Core-venv and Container installs.

An external container works across all HA install types, isolates the browser from HA
Core, lets constrained users point at a beefier machine, and mirrors the operational
model users already accept for SearXNG.

## What this image is (and is not)

The Microsoft image is a *raw* Playwright Server: a websocket the client drives via
`browserType.connect`. It exposes no HTTP render endpoint and does no content
extraction, and its docs warn it is intended for testing, not visiting untrusted
sites. Consequently the integration — not the container — owns all navigation, wait,
extraction, and safety logic. See ADR 0002.
