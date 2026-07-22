# Brand assets

Brand icon for this integration (`domain: playwright_websearch`).

Home Assistant does **not** load icons from the integration repo — they are served
from the central [`home-assistant/brands`](https://github.com/home-assistant/brands)
repo, keyed by domain. These files are kept here for provenance and easy resubmission.

## Files

- `icon.png` — 256×256, transparent, trimmed.
- `icon@2x.png` — 512×512, transparent, trimmed.
- `generate_icon.py` — deterministic Pillow script that produces both PNGs.

## Regenerate

```sh
python brands/generate_icon.py
```

Requires Pillow (already in the project `.venv`).

## Submit to home-assistant/brands

The assets are consumed by a separate PR against `home-assistant/brands`. Copy them to:

```
custom_integrations/playwright_websearch/icon.png
custom_integrations/playwright_websearch/icon@2x.png
```

Requirements met: PNG, transparent, trimmed, square (256²/512²), and **no Home
Assistant branding** (required for custom integrations).
