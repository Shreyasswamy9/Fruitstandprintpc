# Branding

Reference: www.fruitstandny.com, inspected 2026-10-28.

## Taken from the site (verified)

| Element | Source | Use in the hub |
|---|---|---|
| Monogram (mirrored E/S mark, 720×720 PNG) | `/cdn/shop/t/10/assets/fruitstandlogo.png` | Header, favicon, sign-in page |
| FRUITSTAND wordmark (2940×359 PNG) | `/cdn/shop/files/Fruitstand_Wordmark_….png` | Header, sign-in page, test page |
| Black / white base, light grays `#e3e3e3`, `#d3d3d3` | theme stylesheet `theme.css` | Surfaces, lines |
| Accent `#c2410c` (burnt orange) with `#fed7aa` (peach) | theme button hover/active rules | Accent, selection, hover |
| Uppercase display type | theme `text-transform` rules, wordmark | Headings, labels, buttons |
| Button radius capped at 5px, modal radius 10px | theme `border-radius` rules | Buttons, cards, dialogs |
| Motion: 175 ms linear; `cubic-bezier(.2,1,.3,1)` | theme transitions | All transitions |

Logo files are copied into `frontend/public/brand/` and served locally. In dark mode they're inverted with a CSS filter rather than redrawn.

## Missing (not invented)

- **Brand typeface.** The site sets its font stacks and color-scheme variables inline in the page HTML, which returned rate-limit errors (HTTP 429) during inspection. The UI uses a system sans stack (Avenir Next → Helvetica Neue → Ubuntu/Noto Sans) as a placeholder. To fix: get the font name and a license that permits self-hosting, put the `.woff2` files in `frontend/public/fonts/`, add `@font-face` rules and update `--font-brand` in `frontend/src/styles/tokens.css`.
- **Full color scheme values** (scheme backgrounds/text set inline). Confirm the palette above against the brand guide if one exists.
- **Printer illustrations** are generic line drawings made for the hub, not Fruitstand assets or product photos.
