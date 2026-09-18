# Code City JS

Turn any git checkout of **JavaScript / TypeScript** into a **3-D city you can
walk around**: one building per file, districts per folder, its height and
colour driven by whatever you want to see — size, cognitive complexity, churn,
bug-fixes, and **internal coupling roads**. Plus the 2-D **codemap** it ships
with: a treemap next to a log–log scatter.

This is a port of [Victor Rentea's Code City](https://github.com/victorrentea/code-city)
from Java to the JS/TS world — React, Vue, or no framework. The original is
the **guide**, not a fork we silently diverge from.

Every output is a **single self-contained HTML file** — all data inlined,
libraries from a CDN, no server. Mail it, publish it on Pages, open it from
disk.

<img src="docs/vscode-city.jpg" alt="Visual Studio Code as a Code City" width="100%">

*Visual Studio Code: 9302 source files, 1722 folders — one run, one page.
Height is cognitive complexity (Sonar-style via tree-sitter), colour is
commits per KLOC on a log ramp. Hold ⌥ for internal coupling roads. CRAP is
a later version, not faked from LOC. Plain hover worst ~9.5 ms on this plate
(budget under 50 ms).*

## Install (once per machine / env)

You need **Python 3**, **Node.js on `PATH`**, **npm**, and **git**.

```bash
git clone https://github.com/balazsbohonyi/code-city-js
cd code-city-js
pip install -r requirements.txt   # tree-sitter JS/TS grammars (complexity)
npm install                       # dependency-cruiser + TypeScript + Vue SFC (coupling)
```

On Windows PowerShell, if `npm` is blocked by the execution policy, use
`npm.cmd install` instead.

Do **not** reinstall before every city. Re-run `pip install` / `npm install`
only when `requirements.txt` or `package.json` change, or in a fresh venv.

**Without Node:** `generate.py` still builds a city (size, git, complexity).
Fan-in/out stay `0` and ⌥ roads stay off.

## Quick start (each target repo)

The target must be a **git checkout** of JS/TS sources (full history preferred).

```bash
# from anywhere, after Install above
python /path/to/code-city-js/generate.py /path/to/your-repo

# Windows:  start  your-repo\.codecity\codecity.html
# macOS:    open   your-repo/.codecity/codecity.html
# Linux:    xdg-open your-repo/.codecity/codecity.html
```

```powershell
# Windows example
python D:\develop\playground\code-city-js\generate.py D:\path\to\your-repo
start D:\path\to\your-repo\.codecity\codecity.html
```

Optional second argument = output directory (default `REPO/.codecity`):

```bash
python /path/to/code-city-js/generate.py /path/to/your-repo /tmp/my-city
```

Thin wrappers: `generate.sh` / `generate.ps1` (same args). Env-var knobs:
[Configuration](#configuration-env-vars).

| File | What it is |
| --- | --- |
| `codecity.html` | the 3-D city (Three.js) |
| `codemap.html` | the 2-D treemap + scatter (Plotly) |
| `combined.html` | both, side by side, hover-linked |
| `*.tsv` | the measurements, if you want to plot your own |

Do not commit generated cities. Nothing special is required **inside** the
target repo (no config file, no dependency-cruiser install there).

## What a building is

Java almost gets a free mapping: one class, one file, one package. JS/TS
does not. This port picks the closest honest analog and sticks to it:

| City thing | JS/TS |
| --- | --- |
| Building | one **source file** (`.js` `.jsx` `.mjs` `.cjs` `.ts` `.tsx` `.mts` `.cts` `.vue` `.svelte`) |
| District | the **folder** that contains it (`src/components/charts/BarChart.tsx` lives in `src.components.charts`) |
| Module | the nearest ancestor **`package.json`** (a pnpm/npm workspace package, or the repo root) |

Tests (`*.test.*`, `*.spec.*`, `test/`, `tests/`, `e2e/`, …), `node_modules`,
`dist`, `.next` and other build output are not buildings. Demo trees
(`examples/`, `playground/`) **are** buildings unless you name them in
`HEATMAP_PRUNE` — [Skipping demos](#skipping-demos-heatmap_prune). A function
is not a building, and neither is an exported React component — those are
later lenses if they earn one. An 800-line `utils.ts` is one fat block,
which is the truth.

The city does not special-case “this is a React app.” It special-cases file
kinds.

## What each metric means

The page lets you put any column on **area**, **height** or **colour**. Colour
is often a **ratio** (`/kloc`) on a log ramp, clamped at the p95 so a few
extreme files don't wash out the rest.

**Open a file in your editor:** ⌘/Ctrl-double-click a building. The default
is VS Code (`vscode://file/…`). Unset `HEATMAP_OPEN_IN` to disable it.

| Column | Meaning | Now |
| --- | --- | --- |
| `bytes` / `lines` | file size and line count | computed |
| `commits` | non-merge commits that touched the file (full history) | computed |
| `bug_commits` | of those, commits whose subject matches `fix` / `fixed` / `fixes` / `bugfix` (Conventional Commits and the plain “Fix …” verb) | computed |
| `committers` | distinct author emails that touched the file | computed |
| `cochange_out` | of the commits that touched this file, the share that also reached outside its folder, weighted by how far out | computed |
| `cognitive_complexity` | Sonar-style cognitive complexity, summed over functions in the file (tree-sitter). JS/TS/JSX/TSX, plus Vue `<script>` / `<script setup>` — not templates. `??` counts in boolean groups (intentional); `?.` does not. | computed |
| `fan_in` / `fan_out` | how many **repo** files import this file / it imports | computed |
| `coverage` / `crap_max` / `crap_load` | line coverage and CRAP from a test run | reserved (absent, not zero) |

**Coupling roads.** Hold **⌥ / Alt** over a building to draw roads to the
files it depends on (and that depend on it). Edges come from
[dependency-cruiser](https://github.com/sverweij/dependency-cruiser):
**internal only** (no `node_modules`), **`import type` dropped**, string
`require()` counted, static `import('…')` counted, and **barrels resolved
through** so roads aim at real peers instead of stopping on every `index.ts`.
Road thickness is how often the source names the target; click lands on the
first non-import use when we can find one. CRAP columns stay absent until a
later version — still **not** faked from LOC. Default HEIGHT is cognitive
complexity; COLOR = commits per KLOC is still the churn reading.

**Presets.** **Overview** is absolute complexity (tall = hard to follow).
**Complexity density** puts `/kloc` on height as well — complexity *per
thousand lines* — so large complex files shrink toward the pack and the
skyline looks flatter; that is intentional, not a missing score.

**Absence is not zero.** When coverage/CRAP exist they will be missing on
files the report never measured, and those buildings will be grey, not “0%
covered.” Same rule as the Java city with JaCoCo.

## Skipping demos (`HEATMAP_PRUNE`)

The default skip list is things that are never the product: test folders,
`node_modules`, `dist` / `build` / `.next` / `.nuxt`, coverage, vendored
trees. It does **not** skip `examples/` or `playground/`.

Those folders are source, and they have `package.json` files, so they become
districts *and* modules. On [expressjs/express](https://github.com/expressjs/express)
the plate is mostly `examples/`. On [vitejs/vite](https://github.com/vitejs/vite)
it is worse: most of the buildings are playground fixtures, each its own
tiny package, and the real city (`packages/vite` — `css.ts`, `config.ts`,
the server) sits on the left while the labels drown on the right. The 2-D
scatter already drops files under 50 lines, so it still reads as Vite; the
3-D default cannot, because a two-line `import.mjs` is still a building.

They stay on by default because a repo whose product *is* examples would
vanish, and because the match is a **folder name**, not a path. Pruning
`playground` must drop `repo/playground/hmr` and must not drop a checkout
that happens to live under `…/playground/vite`.

`HEATMAP_PRUNE` is extra names, comma-separated, matched as path segments
*inside the repo*. Rebuild after setting it.

```bash
# bash / Git Bash — Vite product city (drop playground, docs, and create-vite templates)
HEATMAP_PRUNE=playground,docs,create-vite python code-city-js/generate.py /path/to/vite
```

```powershell
# PowerShell
$env:HEATMAP_PRUNE = "playground,docs,create-vite"
python code-city-js/generate.py C:\path\to\vite
```

Useful names: `playground`, `playgrounds`, `examples`, `docs`,
`create-vite`, `packages-private`. The name has to be a directory segment
(`playground`), not a glob and not a repo-relative prefix.
`packages/create-vite/template-*` does **not** go away when you prune
`playground` — those scaffolds live under a folder named `create-vite`, so
name that segment too (as in the Vite recipe above).

Always-on skips (tests, `node_modules`, build output) do not need the knob.
Unset `HEATMAP_PRUNE` is the whole-tree city.

## Pipeline

After [Install](#install-once-per-machine--env):

```bash
python generate.py /path/to/your-repo
```

| Step | Script | Produces |
| --- | --- | --- |
| 1 | `compute_complexity.py` | `complexity-per-file.tsv` (Sonar-style scores) |
| 2 | `compute_fanio.mjs` | `fanio-per-file.tsv` + `coupling-edges.tsv` (needs Node) |
| 3 | `build_heatmap.py` | `codemap.tsv` (git + size + complexity + fanio) + packages/modules + `cochange-edges.tsv` |
| 4 | `render_heatmap.py` | `codemap.html` |
| 5 | `render_codecity.py` | `codecity.html` |
| 6 | `render_combined.py` | `combined.html` |

`citylib.py` is the JS/TS front of inclusion: which files count, how a folder
becomes a district, how a `package.json` becomes a module, which bucket a
file uses in the 2-D treemap (repo-root files under `root`, so Plotly never
sees duplicate ids), and which globs the filter box offers for *this* city
(not a hard-coded `*Service` or a PFA-only `..lib.* · use*` hint).

A later version adds CRAP from Istanbul/c8/Vitest coverage.

## CodeCity

`codecity.html` renders the same TSV as a Three.js CodeCity. Drag to pan,
Cmd/Ctrl-drag to rotate, scroll to zoom around the mouse cursor, and
Cmd/Ctrl-double-click a building to open its file in VS Code. The 2-D layout
is computed in-browser with D3 treemap; Three.js extrudes each file tile
into a building.

**Prior art, and the page says so.** The software city — a building per
compilation unit, a district per containment, metrics mapped to height,
footprint and colour — is [CodeCity](https://wettel.github.io/codecity.html),
by Richard Wettel (Università della Svizzera italiana, 2008). Victor
Rentea re-implemented that picture over a different set of metrics for
**Java**. This repo ports his generators to **JS/TS**. Both credits ride in
the bottom-left corner of every page, because that is where the picture is.

The city **geometry, camera, streets, held-key overlays, change marks and
hover budget** are his renderer, vendored, with the smallest possible delta
(see [The renderer](#the-renderer) below). The long argument for why the
plate is a landscape, why streets narrow with depth, why overlays are a
held key and not a checkbox, lives in [his README](https://github.com/victorrentea/code-city).
This page does not re-litigate it.

What this port changes about the *picture*:

- a **file** is the building, a **folder** is the district, a **package.json**
  is the module;
- the default reading is **area = file size, height = cognitive complexity,
  colour = commits per KLOC** (log);
- the filter dropdown offers folder and name globs that actually occur in
  JS/TS trees (`..components.*`, `use*`, `*Dialog`), not `*Service`.

**Change-set filter.** A generated city is nearly always being read to
answer *what did this change?*, so the page opens on the diff when it can
detect one: the feature-branch range vs the default branch, else uncommitted
work, else the last commit that touched analysed files. Unchanged buildings
drain to grey; files that **grew** carry dashed marks at the old height and
the old footprint.

**Coupling streets (⌥) and co-change (Shift)** are in the page when their
data exists. Co-change comes from git. Coupling roads come from
`compute_fanio.mjs` (after `npm install`). If Node was missing or the cruise
failed, fan-in/out stay `0` and the roads hint is absent — never invented
wires.

## The renderer

The Three.js / Plotly pages are not rewritten in TypeScript. They are
**copied** from Victor's repo (`render_codecity.py`, `render_heatmap.py`,
`render_combined.py`) because the Java `_district` function collapses every
same-named folder into one district — unusable on a JS tree with three
`components/` folders.

`vendor/RENDERER-DELTA.md` is the log of that copy: which upstream revision
we took, and every intentional difference. The Python files themselves live
at the repo root (they are the generators, not a third-party library). Do
not “fix” `_district` back to the Java rule. Do not edit Victor's tree.

The same upstream also ships **`hover_cost.py`** and **`profile_city.py`** —
Playwright probes for the hover budget. They are vendored here too
(byte-identical; see the delta log). A large city is not “done” until plain
hover worst stays under **50 ms**; the current VS Code plate clears that
(about **9.5 ms** worst on the trimmed-edges coupling plate; pre-trim coupling
was **44 ms**; complexity-only close was **7.5 ms**; size/churn close was
**9.8 ms**).

```bash
pip install playwright && playwright install chromium
python hover_cost.py path/to/codecity.html my-repo
python profile_city.py path/to/codecity.html my-repo
```

Large-repo proof includes VS Code (thousands of files). A TypeScript rewrite
of the renderer is allowed; until then, a documented one-function change
beats a new engine.


## Configuration (env vars)

`generate.py` sets these; you can override them for CI:

| Var | Purpose |
| --- | --- |
| `HEATMAP_REPO` | repo root to analyse (default: git toplevel) |
| `HEATMAP_OUT` | directory for `.tsv` / `.html` (default: `REPO/.codecity`) |
| `HEATMAP_PRUNE` | extra folder **names** to skip, comma-separated (`playground,docs`). Path segments inside the repo only — see [Skipping demos](#skipping-demos-heatmap_prune) |
| `HEATMAP_ROAD_EDGE_CAP` | max coupling edges kept **per direction per file** in `coupling-edges.tsv` for ⌥ drawing (default `80`, matches the renderer). `fan_in` / `fan_out` counts stay full |
| `HEATMAP_BUG_COMMIT_REGEX` | regex on the commit subject that flags a bug-fix (`""` disables it) |
| `HEATMAP_TITLE` / `HEATMAP_SUBTITLE` / `CODECITY_TITLE` | page heading text |
| `HEATMAP_OPEN_IN` | `vscode` to enable ⌘/Ctrl-click-to-open (empty = off) |
| `HEATMAP_REPO_ABS` | absolute repo root for editor links (default: `HEATMAP_REPO`) |
| `HEATMAP_CHANGED_BASE` | optional override of the auto-detected change-set base ref |

## Provenance

The software-city picture is Wettel 2008. The generators this port follows
are [victorrentea/code-city](https://github.com/victorrentea/code-city),
written to draw the Spring Framework as a city and recovered, parameterized
and documented there.

This repo redoes the **language front-end** (what a building is, which files
count, how git history joins them, cognitive complexity via tree-sitter,
coupling via dependency-cruiser) and keeps the **city** until there is a
reason not to. CRAP is a later version, not silent zeros.
