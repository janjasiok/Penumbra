# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Penumbra is a **single-file** Python program ([penumbra.py](penumbra.py), ~1070 lines) that renders one
equirectangular day/night world map (terminator at the current time) to `penumbra.png` and sets it as the
desktop wallpaper on Windows/macOS. It does not loop or self-refresh — a task scheduler (Windows Task
Scheduler) or cron re-runs it on an interval (~10 min). One render takes ~13–15 s.

## Commands

```bash
pip install -r requirements.txt   # Pillow, numpy, sgp4 (optional), tzdata (Windows only)
python penumbra.py                # render penumbra.png + set as wallpaper
```

There are no tests, no linter config, and no build step. To validate a change, run the script and inspect
`penumbra.png` (or temporarily set `SCREEN = (1920, 1080)` for a fixed-size render). `build_wallpaper(when=...)`
accepts a `datetime` (UTC, tz-aware) so you can render any moment without waiting for real time — useful when
checking terminator, satellite, or moon-phase rendering.

## Conventions

- **All comments, docstrings, and user-facing strings are in Czech.** Match this when editing — do not
  translate existing text or introduce English comments.
- Network features (`sgp4` satellites, NOAA aurora, NASA GIBS live clouds) **degrade silently**: every fetch
  is wrapped in try/except that falls back to disk cache and then to skipping the feature. Preserve this — a
  missing dependency, no internet, or a failed download must never crash the render.
- The big tunable config block lives at the top of the file (`CITY` through `FONT_*`, roughly lines 33–143),
  with a "table of contents" comment at line 34 indexing where each group lives. New options go here.
- **Optional dependencies are imported lazily, inside the function that needs them** (`from sgp4.api import
  Satrec`, `import urllib.request`, `from zoneinfo import ZoneInfo`) — never at module top. This keeps startup
  fast and lets the script run when `sgp4`/network are absent. Only the always-required `os/sys/math/json/
  ctypes/datetime/subprocess`, `numpy`, and `PIL` are imported at the top.
- **Private/internal helpers are prefixed with `_`** (`_marker_*`, `_text`, `_dashed_line`, `_sat_tle`,
  `_moon_subpoint`); the public-ish pipeline functions are not (`subsolar`, `load_font`, `build_wallpaper`).
- **String formatting uses `%`-style throughout** (`"tle_%s.txt" % catnr`, `"%.1f km/s"`), not f-strings or
  `.format()`. Match this. Display text uses the Unicode minus `−` (U+2212), not ASCII `-`, for offsets/labels.
- **Image math is numpy `float32`**, accumulated additively across layers, and clipped to `0–255` / cast to
  `uint8` only at the final `Image.fromarray`. Don't clip intermediate layers.
- **Quality comes from supersampling**: marker glyphs render at a local `SS = 4` and the whole map at
  `SUPERSAMPLE`×, then both are `Image.LANCZOS`-downscaled. New drawn elements should follow the same
  render-big-then-resize pattern rather than drawing at final resolution.
- **Module-level caches use a global sentinel** (`_TZCACHE = None`, lazily filled in `load_timezones()`);
  shared constants like `_SHADOW` are module-level. Keep cache state out of `build_wallpaper`.
- Section banners use the `# ===…` comment style; inline comments are short and right-of-code or above a block.

## Architecture (single render pipeline)

Everything flows through `build_wallpaper()` (line ~541), which builds the image in layers. Order matters —
later layers composite over earlier ones:

1. **Earth base** — loads 8K equirectangular textures (`assets/textures/`) via numpy float32 arrays, or falls
   back to flat colors drawn from `assets/data/land.json` polygons when `USE_TEXTURE=False` or textures are
   missing. Optional cloud texture is blended in and slowly drifted by time (`CLOUD_DRIFT`).
2. **Twilight shading** — per-pixel solar elevation (`elev`) computed from the subsolar point drives a layered
   brightness ramp (day → civil → nautical → astronomical → night), plus a terminator glow and city-lights
   emission on the night side. This is the core day/night effect.
3. **Supersample → downscale → roll to center** — rendered at `SUPERSAMPLE`× (capped to protect memory at 4K),
   LANCZOS-downscaled, then `np.roll`-ed horizontally so the chosen city/longitude is centered seam-free.
4. **Vector overlays** drawn as separate RGBA layers and alpha-composited: graticule, timezone fills/borders
   (`assets/data/timezones.json`, Natural Earth), aurora oval, sun/moon ground-track dashed paths, satellite
   ground tracks, then marker glyphs (sun, moon-with-phase, city beacon, satellite reticles) with labels.
5. **Compose to screen** — `MAP_FILL="cover"` crops the map to fill the display; `"contain"` letterboxes it on
   a starfield. Finally a top/bottom linear vignette.

Key helpers:
- **Astronomy** (lines ~145–192): `subsolar()`, `_moon_subpoint()`, `_moon_phase()` — low-precision closed-form
  formulas, no ephemeris files. All take a UTC `datetime` and return lat/lon (or phase fraction).
- **Coordinate mapping**: inside `build_wallpaper`, `sx(lon)`/`sy(lat)` convert geographic degrees to pixel x/y
  *after* centering. Any new geographic feature must use these. Polylines crossing the date line are split when
  `abs(dx) > map_w*0.5` to avoid horizontal seam streaks (this pattern recurs for tz borders, paths, tracks).
- **Markers** (`_marker_*`): each builds a small supersampled RGBA glyph (glow + rings/disk) and returns
  `(image, pad)`; pasted at `position - pad`. `_text()` draws text with a blurred drop shadow; `_SHADOW` is the
  shared shadow offset used everywhere for visual consistency.
- **External data**: `_sat_tle()` (CelesTrak TLE, ~3 h cache), `get_aurora()` (NOAA OVATION, 15 min cache),
  `fetch_live_clouds()` (NASA GIBS, `CLOUDS_LIVE_HOURS` cache). All cache into `.cache/` (gitignored) and key
  off file mtime for freshness.

## Assets

`assets/` is required and bundled: `textures/` (earth_day/night/clouds 8K JPGs), `fonts/`
(Inter-SemiBold + DMMono-Medium — NASA Horizon Design System), `data/` (timezones.json, land.json). `load_font`
and the texture/data loaders fall back to system fonts / flat rendering if a file is absent, so the script
still produces output, just degraded.
