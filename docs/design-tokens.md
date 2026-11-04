# Design tokens

Sampled 2026-11-04 from the pik-potsdam.de theme CSS (`pik-plone-4.3-theme/css/theme.css`).
Used as a style reference only; the dashboard shows no PIK logo unless that is approved.

| Token | Value | Use on pik-potsdam.de → dashboard |
|---|---|---|
| `--ink` | `#344643` | Dark slate green: primary text, nav, headings |
| `--sand` | `#e1e3d4` | Sand: section backgrounds, table header fill |
| `--cream` | `#f3f3e4` | Cream: card / page tint |
| `--accent` | `#91cdcd` | Teal accent: active tab, highlights, focus ring |
| `--surface` | `#ffffff` | Page background (light) |
| `--muted-bg` | `#f5f6f6` | Subtle row striping |
| `--muted` | `#6c757d` | Secondary text |
| `--rule` | `#dee2e6` | Hairlines |
| `--ok` / `--warn` / `--bad` | `#28a745` / `#ffc107` / `#dc3545` | Status only (Bootstrap defaults used on the site) |

Typography: **IBM Plex Sans** (body), **IBM Plex Sans Condensed** (labels, nav, table headers),
**IBM Plex Serif** (large headings). The fonts are SIL OFL licensed, so they can be inlined as woff2 into the
single HTML file (~60–100 kB for Latin subsets). If size matters, fall back to `system-ui`.

Dark theme: derive from `--ink` as the background (`#1e2a28`-ish) with `--cream` text. It is validated in Phase 3.
