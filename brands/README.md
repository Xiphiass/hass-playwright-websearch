# Brand assets

Source and generator for this integration's brand icon (`domain: playwright_websearch`).

Home Assistant serves an integration's brand images from a local `brand/` folder
**inside the integration directory** first, falling back to the
[`brands.home-assistant.io`](https://brands.home-assistant.io) CDN only when that
folder is absent (see `homeassistant/components/brands/__init__.py`,
`BrandsIntegrationView`). So the icon ships in this repo and needs no external
submission.

## Served files (generated)

- `custom_components/playwright_websearch/brand/icon.png` — 256×256, transparent, trimmed
- `custom_components/playwright_websearch/brand/icon@2x.png` — 512×512, transparent, trimmed

The presence of the `brand/` folder is what activates local serving
(`Integration.has_branding`).

## Regenerate

```sh
python brands/generate_icon.py
```

Requires Pillow (already in the project `.venv`). The script writes both PNGs into
the integration's `brand/` folder.

## Notes

- No Home Assistant branding is used (required for custom integrations).
- Allowed image names: `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`, and their
  `dark_*` variants. HA fills missing sizes/variants from the ones present
  (e.g. `icon@2x.png` → `icon.png`).
