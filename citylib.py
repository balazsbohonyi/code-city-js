"""JS/TS inclusion rules, districts and modules for the v1 city.

The Java guide keys a building on a `.java` file, a district on the path after
`src/main/java`, and a module on the nearest `pom.xml`. Those three coincidences
do not hold here, so the rules live in one place and both the walker and the
tests import them. Path separators are forced to `/` because git log on Windows
still speaks POSIX and the renderer splits on `/`.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from functools import lru_cache

_CAMEL_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*")

# Longer suffixes first so Foo.tsx loses `.tsx`, not `.ts`.
SOURCE_SUFFIXES = (
    ".tsx",
    ".ts",
    ".jsx",
    ".mjs",
    ".cjs",
    ".js",
    ".mts",
    ".cts",
    ".vue",
    ".svelte",
)

PRUNE_DIRS = {
    "node_modules",
    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",
    ".output",
    "coverage",
    ".git",
    ".turbo",
    ".cache",
    "vendor",
    ".venv",
    ".claude",
    ".conductor",
    ".idea",
    "playwright-report",
    "test-results",
}

# Node's `test/`, Vite's `tests/`, Jest's `__tests__/`. A production folder
# actually named `test` is rare; Express would otherwise paint its suite as a
# district of the city.
TEST_DIR_SEGMENTS = {
    "test",
    "tests",
    "__tests__",
    "e2e",
    "cypress",
    "playwright",
}

# Dot-token before the extension: Foo.test.tsx, Foo.test-d.ts (Vue dts-test).
# `test-d` is not the token `test`, so it must be listed explicitly.
TEST_INFIXES = {"test", "spec", "stories", "test-d"}


def posix_rel(path: str, root: str) -> str:
    rel = os.path.relpath(path, root).replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    return rel


def posix_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def repo_rel_parts(root: str, repo_dir: str) -> tuple[str, ...]:
    """Path segments of `root` relative to `repo_dir` (empty at the repo root).

    Prune checks must use these — never absolute `os.walk` parts — otherwise a
    checkout living under a folder named like a prune entry (e.g.
    `…/playground/vite` with `HEATMAP_PRUNE=playground`) skips the whole tree.
    """
    rel = os.path.relpath(root, repo_dir)
    if rel in (".", ""):
        return ()
    return tuple(posix_path(rel).split("/"))


def _extension_ok(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(".d.ts") or lower.endswith(".d.mts") or lower.endswith(".d.cts"):
        return False
    if lower.endswith(".min.js") or lower.endswith(".min.mjs"):
        return False
    return any(lower.endswith(suf) for suf in SOURCE_SUFFIXES)


def _is_colocated_test(name: str) -> bool:
    """Foo.test.tsx, Foo.spec.ts, Button.stories.jsx, Foo.test-d.ts —
    not Foo.testimonial.ts.

    The infix has to be its own dot-separated token, the way the test runners
    themselves match. Vue's `*.test-d.ts` type tests use the token `test-d`.
    """
    parts = name.split(".")
    if len(parts) < 3:
        return False
    return parts[-2].lower() in TEST_INFIXES


def counts_toward_diagram(rel: str) -> bool:
    """True when this repo-relative path is a building in the current tree.

    Used both for the working-tree walk and for whether a git-history path
    counts toward package/module commit sets — same rule, so a commit that
    only moved tests does not light up a district.
    """
    rel = posix_path(rel)
    if not rel or rel == ".":
        return False
    parts = rel.split("/")
    name = parts[-1]
    if not name or not _extension_ok(name) or _is_colocated_test(name):
        return False
    for seg in parts[:-1]:
        if seg in PRUNE_DIRS or seg in TEST_DIR_SEGMENTS or (seg.startswith(".") and seg != "."):
            return False
    return True


def district_of(rel: str) -> str:
    """Dotted folder path of a file, no filename.

    `src/features/billing/api.ts` → `src.features.billing`. A file at the repo
    root lives in `root`, matching the Java fallback when there is no package.
    Dots rather than slashes because the vendored renderer already treats a
    district as a dotted package when it draws streets and parent floors.
    """
    rel = posix_path(rel)
    parts = rel.split("/")
    if len(parts) <= 1:
        return "root"
    return ".".join(parts[:-1])


def parent_district(district: str) -> str:
    if not district or district == "root" or "." not in district:
        return "root" if district != "root" else ""
    return district.rsplit(".", 1)[0]


def building_name(rel: str) -> str:
    """Filename with the source suffix stripped, for roof labels."""
    name = posix_path(rel).rsplit("/", 1)[-1]
    lower = name.lower()
    for suf in SOURCE_SUFFIXES:
        if lower.endswith(suf):
            return name[: len(name) - len(suf)]
    if lower.endswith(".java"):
        return name[: -len(".java")]
    return name


def treemap_module(rel: str) -> str:
    """Top-level bucket for the 2-D Plotly treemap.

    Repo-root files (`eslint.config.js`) must not use their own name as the
    module id — that duplicates the file node and blanks the treemap.
    """
    rel = posix_path(rel)
    return rel.split("/", 1)[0] if "/" in rel else "root"


def _is_package_json(fn: str) -> bool:
    return fn == "package.json"


@lru_cache(maxsize=1)
def discover_module_dirs(repo_dir: str, extra_prune: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Repo-relative directories that contain a package.json, root as ''.

    `node_modules` is pruned before we look, so a dependency's own
    package.json never becomes a module of the city.
    """
    dirs: set[str] = set()
    prune = PRUNE_DIRS | set(extra_prune)
    for root, subdirs, files in os.walk(repo_dir):
        parts = repo_rel_parts(root, repo_dir)
        if any(p == ".git" for p in parts) or any(p in prune for p in parts):
            subdirs[:] = []
            continue
        subdirs[:] = [d for d in subdirs if d not in prune and not d.startswith(".")]
        if any(_is_package_json(fn) for fn in files):
            rel = os.path.relpath(root, repo_dir).replace("\\", "/")
            dirs.add("" if rel == "." else rel)
    return tuple(sorted((m for m in dirs if m), key=len, reverse=True)) + (("",) if "" in dirs else ())


def module_of(rel: str, repo_dir: str, extra_prune: frozenset[str] = frozenset()) -> str:
    """Nearest ancestor package.json directory, '' = repo root."""
    rel = posix_path(rel)
    d = rel.rsplit("/", 1)[0] if "/" in rel else ""
    modules = [m for m in discover_module_dirs(repo_dir, extra_prune) if m]
    for m in modules:  # longest first — the tuple is sorted that way
        if d == m or d.startswith(m + "/"):
            return m
    return ""


# Trailing tokens that actually cluster in React/Vue trees. `Service` is a Java
# family; it is not offered unless the names themselves form it.
_NAME_SUFFIXES = ("Dialog", "Chart", "Workspace", "Settings", "Provider", "Store")


def filter_suggestions(rows: list[dict], folder_min: int = 4, name_min: int = 3,
                       folder_limit: int = 8, prefix_limit: int = 12) -> list[dict]:
    """Globs for the filter dropdown: folders, CamelCase prefixes, hooks, suffixes.

    The Java city offered `..repo.*` and `*Service`. JS/TS has folders and
    `use*` hooks instead of a Service suffix, so the suggestions have to be
    rebuilt from the names on the plate or the box keeps advertising a Java
    convention this repo does not follow.
    """
    leaves: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    suffixes: Counter[str] = Counter()
    use_n = 0
    for row in rows:
        district = row.get("district") or ""
        name = row.get("name") or ""
        if district and district != "root":
            leaves[district.rsplit(".", 1)[-1]] += 1
        tokens = _CAMEL_TOKEN.findall(name)
        if len(tokens) >= 2:
            prefixes[tokens[0]] += 1
        if name.startswith("use") and len(name) > 3:
            use_n += 1
        for suf in _NAME_SUFFIXES:
            if name.endswith(suf) and len(name) > len(suf):
                suffixes[suf] += 1

    folder_globs = [
        {"glob": f"..{leaf}.*", "count": n}
        for leaf, n in sorted(leaves.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= folder_min
    ][:folder_limit]
    prefix_globs = [
        {"glob": f"..{prefix}*", "count": n}
        for prefix, n in sorted(prefixes.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= name_min
    ][:prefix_limit]
    extra: list[dict] = []
    if use_n >= name_min:
        extra.append({"glob": "..use*", "count": use_n})
    for suf, n in sorted(suffixes.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= name_min:
            extra.append({"glob": f"*{suf}", "count": n})

    seen: set[str] = set()
    out: list[dict] = []
    for item in folder_globs + prefix_globs + extra:
        if item["glob"] in seen:
            continue
        seen.add(item["glob"])
        out.append(item)
    return out


def filter_placeholder(rows: list[dict], n: int = 2) -> str:
    """Hint text for the empty filter box — top globs from this city, not a
    hard-coded PFA/React sample (`..lib.* · use*`).
    """
    globs = [s["glob"] for s in filter_suggestions(rows)[:n]]
    if not globs:
        return "folder or name glob"
    return " · ".join(globs)
