# Renderer delta

This folder is **not** a third-party library tree. The copied generators
(`render_codecity.py`, `render_heatmap.py`, `render_combined.py`) live at the
**repository root** — they *are* the city. This file is the log of that copy:
which revision of Victor's Java Code City we took, and every intentional
difference, so nobody “fixes” `_district` back to the Java rule.

Upstream: [victorrentea/code-city](https://github.com/victorrentea/code-city)
at git SHA `81cfda7`
Copied: 2026-09-17

We copy rather than import because `_district` in the guide collapses every
same-named folder to one district. Do not edit the Java repo.

## `render_codecity.py`

1. Import `district_of` / `building_name` from `citylib`.
2. `_district(path)` → full dotted folder path, not parent-folder-name / `java/` segment.
3. Building `name` strips `.ts/.tsx/.js/…`, not only `.java`.
4. View labels: Files / Folders / Packages (values still `classes` / `packages` / `modules`).
5. Defaults: AREA = file size (`bytes`), HEIGHT = cognitive complexity (v2;
   was LOC in v1), COLOR = commits `/kloc` + `lg`.
6. Overview preset: `bytes`, `cognitive_complexity`, `commits` with kloc/log on
   colour (v2; v1 used `lines` for height until complexity was filled).
7. Public copy (ADR 0007): clone URL `https://github.com/balazsbohonyi/code-city-js`;
   origin + howto credit Wettel and Victor's Java city as the guide; recipe is
   `pip install -r requirements.txt` + `npm install` once, then
   `python generate.py` for JS/TS (React/Vue/none). Howto notes complexity
   height + ⌥ coupling roads; CRAP still later. Filter suggestions from
   `citylib.filter_suggestions` (folders, `use*`, CamelCase prefixes) — not
   `*Service`. Empty filter placeholder is `__FILTER_PLACEHOLDER__` from
   `citylib.filter_placeholder` (top globs for this city), not a hard-coded
   `..lib.* · use*`. Hover "files" not "Java files". Folders knob, not Packages.
8. TSV reads and `codecity.html` write are UTF-8. `Path.write_text()` without
   `encoding=` uses the Windows locale codec (cp1252 on Python 3.14), which
   cannot encode the ⌘/⌥/⇧ in the page.
9. Settings panel and shortcuts card are collapsible: dismiss (top-right on
   both) reopen via icon-only FABs (gear top-left, info bottom-right; same
   40×40 hit target, no filled-circle chrome).
   Icons from Bootstrap Icons 1.11 CDN (`bi-x-lg`, `bi-gear-fill`,
   `bi-info-lg`). Shortcuts card is left-aligned. Key names wrapped in
   `<kbd>`.

## `render_heatmap.py`

1. Scatter labels use `building_name` instead of stripping `.java`.
2. Read the TSV and write `codemap.html` as UTF-8. `generate.py` defaults
   `HEATMAP_OPEN_IN=vscode`, which injects ⌘ (U+2318) into the page; locale
   `open()` crashed the vuejs/core run before the city renderer started.
3. Treemap module bucket via `citylib.treemap_module`: repo-root files go under
   `root` instead of using their filename as the module id (duplicate /
   parent===id blanked the Plotly treemap while the scatter still drew).
4. Treemap `branchvalues: 'remainder'` so module rows with value `0` stay
   grouping-only.

## `render_combined.py`

Write `combined.html` as UTF-8 (TITLE is a repo name; keep the three
writers on one encoding).

## `profile_city.py` / `hover_cost.py`

Copied 2026-09-17 from the same upstream SHA `81cfda7`, **byte-identical**
(no intentional delta). They drive headless Chromium via Playwright against
any `codecity.html` — dismiss the intro, then measure hover / FPS / CPU.
Language-agnostic; the vscode large-repo close used them.

```bash
pip install playwright && playwright install chromium
python hover_cost.py REPO/.codecity/codecity.html label
python profile_city.py REPO/.codecity/codecity.html label
```

Budget inherited from the guide: worst **plain** hover **&lt; 50 ms**. Headless
SwiftShader FPS is a relative signal, not the pass/fail criterion. With v3
coupling inlined, vscode plain hover worst was about **44 ms** (still PASS).
