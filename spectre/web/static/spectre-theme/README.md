# SPECTRE Design System

**Space Planning, Evaluation & Counter-Threat Response Engine**
Version 2.0.0 | UNCLASSIFIED

---

## Package Contents

```
spectre-theme/
├── README.md                  ← You are here
│
├── css/
│   ├── spectre-theme.css      ← Full design system (tokens, components, dark/light mode)
│   └── spectre-icons.css      ← Icon utility classes and sizing
│
├── icons/                     ← Individual SVG icons (24×24 viewBox, currentColor)
│   ├── icon-track.svg
│   ├── icon-threat.svg
│   ├── icon-manoeuvre.svg
│   ├── icon-decision.svg
│   ├── icon-sensor.svg
│   ├── icon-custody.svg
│   ├── icon-pattern-of-life.svg
│   ├── icon-intercept.svg
│   ├── icon-monte-carlo.svg
│   ├── icon-report.svg
│   ├── icon-import.svg
│   ├── icon-export.svg
│   ├── icon-operator.svg
│   ├── icon-notso.svg
│   ├── icon-photometry.svg
│   ├── icon-tle.svg
│   ├── icon-settings.svg
│   ├── icon-dashboard.svg
│   ├── icon-filter.svg
│   ├── icon-search.svg
│   ├── icon-clock.svg
│   ├── icon-orbit.svg
│   ├── icon-alert.svg
│   ├── icon-chevron-right.svg
│   ├── icon-chevron-down.svg
│   ├── icon-close.svg
│   └── icon-menu.svg
│
├── assets/                    ← Logo variants, app icon, splash screen
│   ├── logo-primary.svg       ← Full stacked logo with mark + wordmark + subtitle
│   ├── logo-horizontal.svg    ← Compact inline logo for navbars
│   ├── icon-mark.svg          ← Standalone mark (no text) — for watermarks, favicons
│   ├── app-icon-512.svg       ← App icon with dark background baked in (512×512)
│   └── splash.html            ← Animated splash/boot screen (standalone HTML)
│
└── fonts/                     ← (empty — see Font Setup below)
```

---

## Quick Start

### 1. Link the stylesheets

```html
<link rel="stylesheet" href="css/spectre-theme.css">
<link rel="stylesheet" href="css/spectre-icons.css">
```

### 2. Use the logo

```html
<!-- In a navbar -->
<img src="assets/logo-horizontal.svg" alt="SPECTRE" height="36">

<!-- Full logo on a landing/about page -->
<img src="assets/logo-primary.svg" alt="SPECTRE" width="400">
```

### 3. Use icons

```html
<!-- Inline <img> method (simplest) -->
<img class="spectre-icon spectre-icon-md" src="icons/icon-track.svg" alt="Track">

<!-- In a button -->
<button class="spectre-btn">
  <img class="spectre-icon spectre-icon-sm" src="icons/icon-threat.svg" alt="">
  Flag Threat
</button>

<!-- Inline SVG method (supports currentColor for dynamic theming) -->
<svg class="spectre-icon spectre-icon-lg threat" viewBox="0 0 24 24">
  <!-- paste icon SVG contents here -->
</svg>
```

### 4. Use semantic badges

```html
<span class="spectre-badge spectre-badge-threat">THREAT</span>
<span class="spectre-badge spectre-badge-caution">CAUTION</span>
<span class="spectre-badge spectre-badge-nominal">NOMINAL</span>
<span class="spectre-badge spectre-badge-info">TRACKING</span>
```

### 5. Build a panel

```html
<div class="spectre-panel">
  <div class="spectre-panel-header">
    <span class="spectre-panel-title">Object Tracking</span>
    <span class="spectre-badge spectre-badge-nominal">LIVE</span>
  </div>

  <table class="spectre-table">
    <thead>
      <tr>
        <th>NORAD ID</th>
        <th>Name</th>
        <th>Regime</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>25544</td>
        <td>ISS (ZARYA)</td>
        <td>LEO</td>
        <td><span class="spectre-badge spectre-badge-nominal">NOMINAL</span></td>
      </tr>
      <tr class="caution">
        <td>44238</td>
        <td>COSMOS 2542</td>
        <td>LEO</td>
        <td><span class="spectre-badge spectre-badge-caution">MANOEUVRE</span></td>
      </tr>
    </tbody>
  </table>
</div>
```

---

## Font Setup

### Development (CDN)

The theme CSS imports JetBrains Mono and IBM Plex Sans from Google Fonts automatically.
No action needed for development.

### Production (self-hosted)

For air-gapped or production environments, download and self-host:

1. **JetBrains Mono**: https://www.jetbrains.com/lp/mono/ (SIL Open Font License)
2. **IBM Plex Sans**: https://github.com/IBM/plex (SIL Open Font License)

Place WOFF2 files in the `fonts/` directory and replace the `@import` lines at the
top of `spectre-theme.css` with local `@font-face` declarations:

```css
@font-face {
  font-family: 'JetBrains Mono';
  src: url('../fonts/JetBrainsMono-Regular.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
/* ... repeat for other weights: 300, 500, 600, 700 */
```

---

## Dark / Light Mode

SPECTRE is **dark-first**. Dark mode is the default for operational use.

### Automatic (system preference)

The theme respects `prefers-color-scheme` automatically. No action needed.

### Manual toggle

```html
<!-- Force dark -->
<body data-spectre-theme="dark">

<!-- Force light -->
<body data-spectre-theme="light">

<!-- Or use class -->
<body class="spectre-light">
```

### In Python (for Plotly/Matplotlib integration)

```python
# Palette constants for chart theming
SPECTRE_COLORS = {
    "console_black":    "#0A0C10",
    "deep_space":       "#141820",
    "orbital_grey":     "#1E2430",
    "panel_grey":       "#252B38",
    "sensor_grey":      "#7A8BA6",
    "ice_white":        "#D0D4DC",
    "pure_white":       "#ECEEF2",
    "threat_red":       "#E24B4A",
    "threat_red_dim":   "#A32D2D",
    "caution_amber":    "#EF9F27",
    "nominal_green":    "#1D9E75",
    "intel_blue":       "#378ADD",
}
```

---

## Classification Banner

Every SPECTRE screen should carry a classification banner:

```html
<div class="spectre-classification-banner unclassified">UNCLASSIFIED</div>
```

Available classes: `.unclassified` (green), `.official` (blue), `.secret` (red).

---

## Icon Sizing Quick Reference

| Class               | Size   | Use case                           |
|---------------------|--------|------------------------------------|
| `.spectre-icon-xs`  | 14px   | Inline with small text             |
| `.spectre-icon-sm`  | 16px   | Inside buttons                     |
| `.spectre-icon-md`  | 20px   | Default / standalone               |
| `.spectre-icon-lg`  | 24px   | Panel headers, emphasis            |
| `.spectre-icon-xl`  | 32px   | Feature callouts                   |
| `.spectre-icon-2xl` | 48px   | Empty states, hero sections        |

---

## Design Tokens Quick Reference

All component styles reference CSS custom properties. Override any token to re-theme:

```css
/* Example: change threat colour to orange */
:root {
  --spectre-color-threat-red: #FF6B35;
  --spectre-color-threat-red-dim: #CC5529;
  --spectre-color-threat-red-glow: rgba(255, 107, 53, 0.15);
  --spectre-color-threat-red-bg: rgba(255, 107, 53, 0.08);
}
```

### Token categories

| Prefix                  | Purpose                                |
|-------------------------|----------------------------------------|
| `--spectre-color-*`     | Raw palette values                     |
| `--spectre-surface-*`   | Background fills (mode-aware)          |
| `--spectre-text-*`      | Text colours (mode-aware)              |
| `--spectre-border-*`    | Border colours (mode-aware)            |
| `--spectre-font-*`      | Font family stacks                     |
| `--spectre-size-*`      | Typography size scale                  |
| `--spectre-weight-*`    | Font weights                           |
| `--spectre-leading-*`   | Line heights                           |
| `--spectre-tracking-*`  | Letter spacing                         |
| `--spectre-space-*`     | Spacing scale (4px increments)         |
| `--spectre-radius-*`    | Border radius                          |
| `--spectre-shadow-*`    | Box shadows                            |
| `--spectre-transition-*`| Animation timing                       |
| `--spectre-z-*`         | Z-index layers                         |

---

## Splash Screen

`assets/splash.html` is a standalone boot screen. Integrate it by:

1. **Standalone window** — open it as a loading screen before your main app
2. **Embedded** — load it in an iframe or webview during initialisation
3. **Reference** — use the animation patterns and colour values as a template

The splash auto-cycles through status messages and fills a progress bar over ~3 seconds.

---

## Licence

- **JetBrains Mono**: SIL Open Font License 1.1
- **IBM Plex Sans**: SIL Open Font License 1.1
- **SPECTRE design assets**: Project-internal use
