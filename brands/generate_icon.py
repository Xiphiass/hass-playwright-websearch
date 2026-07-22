"""Generate the brand icon for the Playwright Web Search integration.

The icon is rendered once at 512x512 (the source of truth) and downsampled to
256x256 with a high-quality LANCZOS filter, producing the two PNGs Home Assistant
serves from the integration's own ``brand/`` folder:

    custom_components/playwright_websearch/brand/icon@2x.png  512x512
    custom_components/playwright_websearch/brand/icon.png     256x256

HA (>= 2024.x, present in 2026.7) resolves an integration's brand images from a
local ``brand/`` folder first, falling back to the brands.home-assistant.io CDN
only when it is absent. See homeassistant/components/brands/__init__.py.

Concept: a magnifying glass (web search) over a stylized browser window whose
content lines suggest the *rendered* page text this integration returns. Flat,
high-contrast, transparent background, neutral (non-Home-Assistant) palette.

Run:  python brands/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Work at 4x the 2x target for crisp edges, then downsample.
SUPERSAMPLE = 4
BASE = 512
CANVAS = BASE * SUPERSAMPLE

# Neutral palette — deliberately not Home Assistant's cyan/blue brand colors.
BROWSER_FILL = (39, 46, 61, 255)      # deep slate
BROWSER_CHROME = (58, 68, 88, 255)    # lighter slate top bar
DOT = (120, 132, 156, 255)            # window control dots
LINE = (150, 162, 186, 255)          # page text lines
GLASS_RING = (255, 176, 32, 255)      # warm amber — the search accent
GLASS_LENS = (255, 176, 32, 46)       # faint amber lens tint
GLASS_HANDLE = (255, 176, 32, 255)


def _rounded(draw: ImageDraw.ImageDraw, box, radius, **kw) -> None:
    draw.rounded_rectangle(box, radius=radius, **kw)


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 512.0  # scale unit relative to the nominal 512 design grid

    # Browser window, kept within ~90% of the canvas (trimmed look).
    bx0, by0, bx1, by1 = 64 * u, 96 * u, 448 * u, 416 * u
    _rounded(d, (bx0, by0, bx1, by1), radius=36 * u, fill=BROWSER_FILL)

    # Top chrome bar with three control dots.
    chrome_h = 64 * u
    _rounded(
        d,
        (bx0, by0, bx1, by0 + chrome_h + 24 * u),
        radius=36 * u,
        fill=BROWSER_CHROME,
    )
    # Cover the lower rounded corners of the chrome so only the top is rounded.
    d.rectangle((bx0, by0 + chrome_h - 16 * u, bx1, by0 + chrome_h + 24 * u), fill=BROWSER_FILL)
    dot_y = by0 + chrome_h / 2
    for i, cx in enumerate((100, 132, 164)):
        r = 9 * u
        d.ellipse((cx * u - r, dot_y - r, cx * u + r, dot_y + r), fill=DOT)

    # Rendered "page text" lines in the body.
    line_x0 = 100 * u
    line_widths = (300, 260, 300, 210)
    ly = by0 + chrome_h + 44 * u
    for w in line_widths:
        _rounded(d, (line_x0, ly, line_x0 + w * u, ly + 16 * u), radius=8 * u, fill=LINE)
        ly += 42 * u

    # Magnifying glass over the lower-right, overlapping the window edge.
    cx, cy, ring_r = 330 * u, 300 * u, 92 * u
    ring_w = 28 * u
    # Lens tint fill.
    d.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), fill=GLASS_LENS)
    # Ring.
    d.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline=GLASS_RING,
        width=int(ring_w),
    )
    # Handle.
    import math

    ang = math.radians(45)
    hx0 = cx + (ring_r - ring_w * 0.2) * math.cos(ang)
    hy0 = cy + (ring_r - ring_w * 0.2) * math.sin(ang)
    hx1 = cx + (ring_r + 70 * u) * math.cos(ang)
    hy1 = cy + (ring_r + 70 * u) * math.sin(ang)
    d.line((hx0, hy0, hx1, hy1), fill=GLASS_HANDLE, width=int(ring_w))
    # Rounded handle cap.
    cap_r = ring_w / 2
    d.ellipse((hx1 - cap_r, hy1 - cap_r, hx1 + cap_r, hy1 + cap_r), fill=GLASS_HANDLE)

    return img


def main() -> None:
    # Write directly into the integration's brand/ folder, which HA serves.
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "custom_components" / "playwright_websearch" / "brand"
    out_dir.mkdir(parents=True, exist_ok=True)
    master = render(CANVAS)

    icon2x = master.resize((BASE, BASE), Image.LANCZOS)
    icon1x = master.resize((BASE // 2, BASE // 2), Image.LANCZOS)

    icon2x.save(out_dir / "icon@2x.png", optimize=True)
    icon1x.save(out_dir / "icon.png", optimize=True)
    print(f"Wrote {out_dir/'icon.png'} (256x256) and {out_dir/'icon@2x.png'} (512x512)")


if __name__ == "__main__":
    main()
