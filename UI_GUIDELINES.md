# UI Guidelines — PyQt6 Download Manager

## Design Language: Samsung One UI 9 inspired

### Core Principles
- Generous whitespace, rounded corners (16–24px radius on cards/buttons)
- Large, legible typography with clear visual hierarchy
- Soft elevation via subtle shadows rather than hard borders
- Content-first layout: minimal chrome, bottom-weighted primary actions
- Smooth, purposeful motion (fade/slide transitions between states)

### Color System
Implement as QSS variables (two palettes, swappable at runtime):

**Light Mode**
- Background: `#F5F5F5` (base), `#FFFFFF` (cards/surfaces)
- Primary accent: `#1A73E8` or Samsung-blue `#1259C3`
- Text: `#1C1C1E` (primary), `#6B6B6F` (secondary)
- Divider: `#E5E5EA`

**Dark Mode**
- Background: `#121212` (base), `#1E1E1E` (cards/surfaces)
- Primary accent: `#4FA0FF` (lighter for contrast on dark)
- Text: `#F2F2F2` (primary), `#A0A0A5` (secondary)
- Divider: `#2C2C2E`

- Provide `theme_light.qss` and `theme_dark.qss`; toggle via a settings
  action that swaps the app's stylesheet at runtime (`QApplication.setStyleSheet`).
- Persist the user's theme choice in `core/config.py`.

### Typography
- Primary font: **Google Sans** (bundle as an embedded font resource;
  fall back to "Roboto" or system sans-serif if not installed, since
  Google Sans isn't freely redistributable — see note below).
- Font weights: Regular (body), Medium (labels/buttons), Bold (headers).
- Base size: 14px body, 12px secondary/meta text, 20–24px headers.

> ⚠️ Note for the agent: Google Sans is a proprietary Google font and
> may not be legally bundled/redistributed in all contexts. Check
> licensing before embedding the font file. If unavailable, use
> **Google Sans Text** alternatives like "Product Sans" clones are also
> restricted — the safest free equivalent is **"Roboto"** or
> **"Noto Sans"**, which are Google-licensed under Apache 2.0 and
> visually close. Use Noto Sans as the practical default, and make the
> font name configurable so the user can point to a local Google Sans
> file if they already have one licensed.

### Khmer + English Language Support
- Use **Noto Sans Khmer** paired with the Latin font for proper Khmer
  glyph rendering (Google Sans/Roboto often lack Khmer coverage).
- Implement font fallback: Latin text → Google Sans/Roboto → Khmer text
  → Noto Sans Khmer, via Qt's font fallback chain or a custom
  `QFontDatabase` setup that loads both and lets Qt pick per-script.
- All UI strings go through a translation layer:
  - `resources/i18n/en.json`
  - `resources/i18n/km.json`
  - A `utils/i18n.py` loader with a simple `tr("key")` function.
- Add a language toggle in settings (flag/label: "EN" / "ខ្មែរ"),
  persisted like the theme choice.
- Right-to-left is NOT needed (Khmer is left-to-right), but verify
  line-height is increased slightly for Khmer script (taller glyphs)
  — recommend 1.4–1.5 line-height when Khmer is active.

### Component Style Notes
- **Buttons**: filled/rounded, primary accent color, 44px min height
  (touch-friendly, One UI style), medium-weight label text.
- **Progress bars**: thick (8–10px), rounded ends, accent color fill,
  track in a muted surface color.
- **Cards (download rows)**: rounded 16px, subtle shadow, padding 12–16px,
  icon/thumbnail + filename + progress + actions laid out horizontally.
- **Settings panel**: grouped list style (like One UI settings pages),
  section headers in secondary text color, toggle switches (not checkboxes).

## Agent Instructions
- Implement theme + language as independent, persisted settings.
- Build `theme_light.qss` / `theme_dark.qss` first, then style widgets
  against those variables — don't hardcode colors in widget code.
- Build the i18n loader before writing UI copy, so all strings route
  through `tr()` from the start.