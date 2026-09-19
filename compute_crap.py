#!/usr/bin/env python3
"""Per-file CRAP and statement coverage from Istanbul coverage-final.json.

CRAP is Alberto Savoia's Change Risk Anti-Patterns metric
(https://testing.googleblog.com/2011/02/this-code-is-crap.html):

    CRAP(m) = CC(m)^2 * (1 - cov(m))^3 + CC(m)

for a single FUNCTION m, where CC is **cyclomatic** complexity (McCabe /
ESLint-style) and cov is the fraction of Istanbul **statements** whose
locations fall inside that function's source range and were hit. Cognitive
complexity (ADR 0009 / height) is a different scale and is never fed in.

Istanbul does not ship COMPLEXITY counters the way JaCoCo does, so this pass
walks tree-sitter for CC and joins statement maps by location (ADR 0011).

Inputs:
  - CODECITY_COVERAGE : paths/globs to coverage-final.json, separated by
    ":" or ",". Unset → glob ``**/coverage/coverage-final.json`` under the
    repo (skipping node_modules / .git / agent-worktree segments).
  - CODECITY_COVERAGE_ACCEPTANCE : optional second JSON → coverage_acceptance
    only (never auto-globbed; no second CRAP).
  - CODECITY_COVERAGE_INCLUDE / CODECITY_COVERAGE_EXCLUDE : optional
    repo-relative path globs (``:`` / ``,``, ``**`` ok). Applied after path
    normalize / source-map remap. Prefer narrowing the test runner's
    coverage.include first; these are a city-side second filter.
  - HEATMAP_REPO / HEATMAP_OUT : working tree and output dir.

When an Istanbul entry still points at emitted JS but carries
``inputSourceMap`` (or a sibling ``.map``), statement locations are remapped
to original sources before joining. Remap failure → that entry is absent.

Output:
  - OUT_DIR/crap-per-file.tsv with the Java column shape. Written only when
    a report was found; an unmeasured file gets no row (absence ≠ zero).
  - No report → stderr + delete any stale TSV so yesterday's coverage cannot
    colour today's city.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from citylib import (
    PRUNE_DIRS,
    counts_toward_diagram,
    posix_path,
    posix_rel,
    repo_rel_parts,
)

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (os.environ.get("HEATMAP_PYLIBS"), os.path.join(_here, ".pylibs")):
    if _p and os.path.isdir(_p):
        sys.path.insert(0, _p)


def _lang(mod_fn):
    try:
        return Language(mod_fn())
    except TypeError:
        return Language(mod_fn(), "x")


JS_LANG = _lang(tsjs.language)
TS_LANG = _lang(tsts.language_typescript)
TSX_LANG = _lang(tsts.language_tsx)

_parsers: dict[str, Parser] = {}


def _parser_for(lang: Language) -> Parser:
    key = str(id(lang))
    p = _parsers.get(key)
    if p is None:
        p = Parser(lang)
        _parsers[key] = p
    return p


def _git_root(start: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return start


REPO_DIR = os.path.abspath(os.environ.get("HEATMAP_REPO") or _git_root(_here))
OUT_DIR = os.path.abspath(os.environ.get("HEATMAP_OUT") or REPO_DIR)
os.makedirs(OUT_DIR, exist_ok=True)
OUT_FILE = os.path.join(OUT_DIR, "crap-per-file.tsv")
EXTRA_PRUNE = frozenset(d for d in os.environ.get("HEATMAP_PRUNE", "").split(",") if d)
PRUNE = PRUNE_DIRS | set(EXTRA_PRUNE)

CRAP_THRESHOLD = 30.0

DEFAULT_GLOBS = ["**/coverage/coverage-final.json"]
SKIP_SEGMENTS = {".claude", ".conductor", "node_modules", ".git", ".codecity"}

JS_EXTS = {".js", ".mjs", ".cjs", ".jsx"}
TS_EXTS = {".ts", ".mts", ".cts"}
TSX_EXTS = {".tsx"}
VUE_EXTS = {".vue"}
SCORE_EXTS = JS_EXTS | TS_EXTS | TSX_EXTS | VUE_EXTS

FUNCTION_DECL = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
}
FUNCTION_EXPR = {"arrow_function", "function_expression", "generator_function"}
CLASS_LIKE = {"class_declaration", "class", "abstract_class_declaration"}

LOGICAL_OPS = {"&&", "||"}  # McCabe / ESLint; ?? is not cyclomatic here

_SCRIPT_RE = re.compile(
    r"<script\b([^>]*)>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def acceptance_paths() -> list[str]:
    """Acceptance-only report(s). Never auto-globbed (ADR 0011)."""
    configured = os.environ.get("CODECITY_COVERAGE_ACCEPTANCE", "").replace(",", ":")
    found: list[str] = []
    for pat in (p for p in configured.split(":") if p.strip()):
        pat = pat if os.path.isabs(pat) else os.path.join(REPO_DIR, pat)
        found.extend(sorted(glob.glob(pat, recursive=True)))
    return [p for p in found if os.path.isfile(p)]


def report_paths() -> list[str]:
    """Every coverage-final.json we should read."""
    configured = os.environ.get("CODECITY_COVERAGE", "").replace(",", ":")
    patterns = [p for p in configured.split(":") if p.strip()]
    if patterns:
        found: list[str] = []
        for pat in patterns:
            pat = pat if os.path.isabs(pat) else os.path.join(REPO_DIR, pat)
            found.extend(sorted(glob.glob(pat, recursive=True)))
        return [p for p in found if os.path.isfile(p)]
    found = []
    for pat in DEFAULT_GLOBS:
        for p in sorted(glob.glob(os.path.join(REPO_DIR, pat), recursive=True)):
            rel_segments = set(os.path.relpath(p, REPO_DIR).split(os.sep))
            if rel_segments & SKIP_SEGMENTS:
                continue
            if os.path.isfile(p):
                found.append(p)
    return found


def _head_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "-C", REPO_DIR, "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def crap(complexity: float, coverage: float) -> float:
    """CRAP(m), coverage as a fraction in [0, 1]."""
    return complexity**2 * (1.0 - coverage) ** 3 + complexity


# ---------------------------------------------------------------------------
# Path normalize (Istanbul keys → city buildings)
# ---------------------------------------------------------------------------


def normalize_report_path(raw: str) -> Optional[str]:
    """Map an Istanbul file key to a repo-relative building path, or None."""
    if not raw:
        return None
    key = raw.replace("\\", "/")
    if key.startswith("file:"):
        # file:///C:/... or file:///home/...
        key = key[5:]
        if key.startswith("///"):
            key = key[3:]
        elif key.startswith("//"):
            key = key[2:]
        if re.match(r"^[A-Za-z]:/", key):
            pass
        elif key.startswith("/") and re.match(r"^/[A-Za-z]:/", key):
            key = key[1:]
    abs_candidate = key
    if not os.path.isabs(abs_candidate):
        abs_candidate = os.path.join(REPO_DIR, key.replace("/", os.sep))
    try:
        abs_resolved = os.path.abspath(abs_candidate)
    except Exception:
        return None
    repo_abs = os.path.abspath(REPO_DIR)
    try:
        common = os.path.commonpath([abs_resolved, repo_abs])
    except ValueError:
        return None
    if os.path.normcase(common) != os.path.normcase(repo_abs):
        return None
    rel = posix_rel(abs_resolved, repo_abs)
    if not counts_toward_diagram(rel):
        return None
    suf = Path(rel).suffix.lower()
    if suf not in SCORE_EXTS:
        return None
    return rel


# ---------------------------------------------------------------------------
# Path globs (city-side include/exclude after normalize/remap)
# ---------------------------------------------------------------------------


def _split_env_globs(name: str) -> list[str]:
    raw = os.environ.get(name, "").replace(",", ":")
    return [p.strip().replace("\\", "/").lstrip("./") for p in raw.split(":") if p.strip()]


def _path_glob_match(rel: str, pattern: str) -> bool:
    """Match repo-relative path against a glob (supports ``**`` via Path.match)."""
    rel_p = PurePosixPath(rel.replace("\\", "/"))
    pat = pattern.replace("\\", "/").lstrip("./")
    try:
        if rel_p.match(pat):
            return True
        # Allow `src/lib/**` style and bare `*.ts` against the basename tree.
        if not pat.startswith("**/") and rel_p.match("**/" + pat):
            return True
    except ValueError:
        return False
    return False


def coverage_path_allowed(rel: str) -> bool:
    """True when rel survives CODECITY_COVERAGE_INCLUDE / _EXCLUDE."""
    includes = _split_env_globs("CODECITY_COVERAGE_INCLUDE")
    excludes = _split_env_globs("CODECITY_COVERAGE_EXCLUDE")
    if includes and not any(_path_glob_match(rel, p) for p in includes):
        return False
    if excludes and any(_path_glob_match(rel, p) for p in excludes):
        return False
    return True


def _filter_coverage_paths(
    coverage: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {rel: entry for rel, entry in coverage.items() if coverage_path_allowed(rel)}


# ---------------------------------------------------------------------------
# Source-map remap (emitted JS → original buildings)
# ---------------------------------------------------------------------------

_VLQ_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_VLQ_VALUES = {c: i for i, c in enumerate(_VLQ_CHARS)}


def _decode_vlq(segment: str) -> list[int]:
    """Decode one source-map VLQ segment into signed integers."""
    values: list[int] = []
    i = 0
    n = len(segment)
    while i < n:
        result = 0
        shift = 0
        while True:
            if i >= n:
                break
            digit = _VLQ_VALUES.get(segment[i])
            i += 1
            if digit is None:
                break
            result |= (digit & 31) << shift
            shift += 5
            if (digit & 32) == 0:
                break
        # sign bit is LSB
        if result & 1:
            values.append(-(result >> 1))
        else:
            values.append(result >> 1)
    return values


class _SourceMapIndex:
    """Minimal consumer: originalPositionFor(gen_line_1based, gen_col_0based)."""

    def __init__(self, sm: dict[str, Any], generated_path: str):
        self.sources = [str(s) for s in (sm.get("sources") or [])]
        self.source_root = str(sm.get("sourceRoot") or "")
        self._generated_dir = os.path.dirname(os.path.abspath(generated_path))
        # list of lines; each line is list of (gen_col, source_idx, orig_line_0, orig_col)
        self._lines: list[list[tuple[int, int, int, int]]] = []
        mappings = sm.get("mappings") or ""
        gen_line_segs = mappings.split(";")
        source_idx = 0
        orig_line = 0
        orig_col = 0
        for line_map in gen_line_segs:
            gen_col = 0
            segs: list[tuple[int, int, int, int]] = []
            if line_map:
                for piece in line_map.split(","):
                    vals = _decode_vlq(piece)
                    if not vals:
                        continue
                    gen_col += vals[0]
                    if len(vals) >= 4:
                        source_idx += vals[1]
                        orig_line += vals[2]
                        orig_col += vals[3]
                        segs.append((gen_col, source_idx, orig_line, orig_col))
            self._lines.append(segs)

    def original_position(
        self, gen_line_1: int, gen_col_0: int
    ) -> Optional[tuple[str, int, int]]:
        """Return (source_path, orig_line_1based, orig_col_0based) or None."""
        idx = gen_line_1 - 1
        if idx < 0 or idx >= len(self._lines):
            return None
        segs = self._lines[idx]
        if not segs:
            return None
        # greatest-lower-bound on generated column
        best: Optional[tuple[int, int, int, int]] = None
        for seg in segs:
            if seg[0] <= gen_col_0:
                best = seg
            else:
                break
        if best is None:
            best = segs[0]
        _gc, sidx, oline0, ocol = best
        if sidx < 0 or sidx >= len(self.sources):
            return None
        return (self.sources[sidx], oline0 + 1, ocol)

    def resolve_source(self, source: str) -> Optional[str]:
        """Map a sources[] entry to a city building path, or None."""
        src = source.replace("\\", "/")
        # Strip common bundler schemes.
        for prefix in (
            "webpack:///",
            "webpack://",
            "vite/",
            "file://",
        ):
            if src.startswith(prefix):
                src = src[len(prefix) :]
                break
        if src.startswith("/"):
            # /C:/... or absolute unix under repo
            if re.match(r"^/[A-Za-z]:/", src):
                src = src[1:]
        if self.source_root:
            root = self.source_root.replace("\\", "/").rstrip("/")
            if not src.startswith(root) and not os.path.isabs(src):
                src = f"{root}/{src.lstrip('/')}"
        # Absolute vs relative to the generated file.
        if not os.path.isabs(src) and not re.match(r"^[A-Za-z]:/", src):
            abs_try = os.path.abspath(os.path.join(self._generated_dir, src.replace("/", os.sep)))
        else:
            abs_try = src
        return normalize_report_path(abs_try)


def _load_raw_source_map(entry: dict[str, Any], generated_abs: str) -> Optional[dict[str, Any]]:
    sm = entry.get("inputSourceMap")
    if isinstance(sm, dict) and sm.get("mappings") is not None:
        return sm
    # Sibling .map next to the generated file (when the report key was absolute-ish).
    map_path = generated_abs + ".map"
    if os.path.isfile(map_path):
        try:
            with open(map_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("mappings") is not None:
                return data
        except (OSError, json.JSONDecodeError):
            pass
    # data:application/json;base64,... inline comment is rare in Istanbul entries;
    # inputSourceMap covers the common case.
    return None


def _extract_statements(
    entry: dict[str, Any],
) -> list[tuple[tuple[int, int, int, int], int]]:
    stmt_map = entry.get("statementMap") or {}
    hits = entry.get("s") or {}
    statements: list[tuple[tuple[int, int, int, int], int]] = []
    for sid, loc in stmt_map.items():
        if not isinstance(loc, dict) or loc.get("skip"):
            continue
        lk = _loc_key(loc)
        if lk is None:
            continue
        try:
            h = int(hits.get(str(sid), hits.get(sid, 0)) or 0)
        except (TypeError, ValueError):
            h = 0
        statements.append((lk, h))
    return statements


def _loc_key(loc: dict) -> Optional[tuple[int, int, int, int]]:
    try:
        s, e = loc["start"], loc["end"]
        return (int(s["line"]), int(s["column"]), int(e["line"]), int(e["column"]))
    except (KeyError, TypeError, ValueError):
        return None


def _statements_via_source_map(
    entry: dict[str, Any],
    raw_key: str,
) -> dict[str, list[tuple[tuple[int, int, int, int], int]]]:
    """Remap statement hits through inputSourceMap → {building_rel: statements}.

    Empty dict means remap failed or nothing mapped to a city building (absence).
    """
    gen_path = entry.get("path") or raw_key
    # Resolve generated file for map sidecar / sourceRoot join.
    gen_abs = gen_path
    if not os.path.isabs(gen_abs):
        gen_abs = os.path.join(REPO_DIR, str(gen_path).replace("/", os.sep))
    gen_abs = os.path.abspath(gen_abs)
    sm_raw = _load_raw_source_map(entry, gen_abs)
    if not sm_raw:
        return {}
    try:
        index = _SourceMapIndex(sm_raw, gen_abs)
    except Exception as e:
        print(f"WARN: source map unusable for {raw_key}: {e}", file=sys.stderr)
        return {}

    out: dict[str, list[tuple[tuple[int, int, int, int], int]]] = defaultdict(list)
    for lk, hits in _extract_statements(entry):
        mapped = index.original_position(lk[0], lk[1])
        if mapped is None:
            continue
        src, oline, ocol = mapped
        rel = index.resolve_source(src)
        if rel is None:
            continue
        # Keep a point-sized loc at the original start; end ≈ start for attribution.
        out[rel].append(((oline, ocol, oline, ocol), hits))
    return dict(out)


# ---------------------------------------------------------------------------
# Istanbul load / merge
# ---------------------------------------------------------------------------


def _load_istanbul(path: str) -> dict[str, dict[str, Any]]:
    """Return {repo_rel: {statements: [(loc_key, hits), ...]}}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: {path} is not parseable ({e}); skipping it", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"WARN: {path} is not an Istanbul object; skipping it", file=sys.stderr)
        return {}
    out: dict[str, dict[str, Any]] = {}
    remapped_entries = 0
    dropped = 0
    for raw_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        rel = normalize_report_path(entry.get("path") or raw_key)
        if rel is not None:
            statements = _extract_statements(entry)
            bucket = out.setdefault(rel, {"statements": []})
            bucket["statements"].extend(statements)
            continue
        # Not a building as-is — try source-map remap to originals.
        remapped = _statements_via_source_map(entry, str(raw_key))
        if not remapped:
            dropped += 1
            continue
        remapped_entries += 1
        for rrel, stmts in remapped.items():
            bucket = out.setdefault(rrel, {"statements": []})
            bucket["statements"].extend(stmts)
    if remapped_entries:
        print(
            f"remapped {remapped_entries} emitted coverage entr"
            f"{'y' if remapped_entries == 1 else 'ies'} via source map",
            file=sys.stderr,
        )
    if dropped:
        print(
            f"dropped {dropped} coverage entr"
            f"{'y' if dropped == 1 else 'ies'} (not a building; remap failed)",
            file=sys.stderr,
        )
    return out


def _merge_file_maps(maps: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Merge reports: same path → max hit count per statement location."""
    merged: dict[str, dict[str, Any]] = {}
    for m in maps:
        for rel, entry in m.items():
            slot = merged.setdefault(rel, {"by_loc": {}})
            for lk, h in entry.get("statements", []):
                prev = slot["by_loc"].get(lk, 0)
                slot["by_loc"][lk] = max(prev, h)
    # Flatten
    return {
        rel: {
            "statements": [(lk, h) for lk, h in sorted(slot["by_loc"].items())],
        }
        for rel, slot in merged.items()
    }


# ---------------------------------------------------------------------------
# Vue script extract (with source offsets for statement join)
# ---------------------------------------------------------------------------


def extract_vue_scripts_with_offset(
    source: str,
) -> list[tuple[bytes, str, int, int]]:
    """Return [(script_bytes, lang_tag, start_line_0based, start_col)]."""
    out: list[tuple[bytes, str, int, int]] = []
    for m in _SCRIPT_RE.finditer(source):
        attrs = m.group(1) or ""
        body = m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.IGNORECASE):
            continue
        lang = "js"
        lm = re.search(r"\blang\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
        if lm:
            tag = lm.group(1).lower()
            if tag in ("ts", "typescript"):
                lang = "ts"
            elif tag == "tsx":
                lang = "tsx"
            elif tag == "jsx":
                lang = "jsx"
        # Body starts after the opening tag; m.start(2) is that offset.
        prefix = source[: m.start(2)]
        start_line = prefix.count("\n")
        last_nl = prefix.rfind("\n")
        start_col = (m.start(2) - last_nl - 1) if last_nl >= 0 else m.start(2)
        out.append((body.encode("utf-8"), lang, start_line, start_col))
    return out


# ---------------------------------------------------------------------------
# Tree helpers + cyclomatic walker
# ---------------------------------------------------------------------------


def node_text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def get_name(node: Node, src: bytes) -> Optional[str]:
    n = node.child_by_field_name("name")
    if n is not None:
        return node_text(n, src)
    for c in node.children:
        if c.type in ("identifier", "property_identifier", "private_property_identifier"):
            return node_text(c, src)
    return None


def binary_op(node: Node, src: bytes) -> str:
    op = node.child_by_field_name("operator")
    if op is not None:
        return node_text(op, src)
    return ""


def _is_scored_unit_expr(node: Node) -> bool:
    if node.type not in FUNCTION_EXPR:
        return False
    parent = node.parent
    if parent is None:
        return True
    if parent.type == "variable_declarator":
        return parent.child_by_field_name("value") == node
    if parent.type == "assignment_expression":
        return parent.child_by_field_name("right") == node
    if parent.type in ("pair", "public_field_definition", "field_definition"):
        return True
    if parent.type == "export_statement":
        return True
    return False


def _function_body(node: Node) -> Optional[Node]:
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for c in reversed(node.children):
        if c.is_named and c.type in (
            "statement_block",
            "expression",
            "binary_expression",
            "ternary_expression",
            "identifier",
            "call_expression",
            "jsx_element",
            "jsx_self_closing_element",
            "parenthesized_expression",
        ):
            return c
    return None


def collect_score_units(root: Node) -> list[Node]:
    units: list[Node] = []

    def visit(node: Node) -> None:
        t = node.type
        if t in FUNCTION_DECL:
            units.append(node)
            for c in node.children:
                visit(c)
            return
        if t in FUNCTION_EXPR and _is_scored_unit_expr(node):
            units.append(node)
            for c in node.children:
                visit(c)
            return
        for c in node.children:
            visit(c)

    visit(root)
    return units


def cyclomatic_of_body(body: Optional[Node], src: bytes) -> int:
    """McCabe / ESLint-style cyclomatic complexity of one function body.

    Base 1. +1 for if, loops, catch, ternary, each switch case (not default),
    each && / ||. Nesting and plain else do not add. Nested scored units are
    skipped (their own CRAP rows).
    """
    if body is None:
        return 1
    total = 1

    def walk(node: Node) -> None:
        nonlocal total
        t = node.type

        if t in CLASS_LIKE:
            return
        if t in FUNCTION_DECL:
            return
        if t in FUNCTION_EXPR:
            if _is_scored_unit_expr(node):
                return
            # Inline lambda: decisions inside still count toward the enclosing
            # method (JaCoCo-ish method grain; ADR AST-owns scored units only).
            lam_body = _function_body(node)
            if lam_body is not None:
                walk(lam_body)
            return

        if t == "if_statement":
            total += 1
            for c in node.children:
                walk(c)
            return

        if t == "ternary_expression":
            total += 1
            for c in node.children:
                walk(c)
            return

        if t in ("for_statement", "for_in_statement", "while_statement", "do_statement"):
            total += 1
            for c in node.children:
                walk(c)
            return

        if t == "catch_clause":
            total += 1
            for c in node.children:
                walk(c)
            return

        if t == "switch_case":
            # `default:` is switch_default in tree-sitter-javascript.
            total += 1
            for c in node.children:
                walk(c)
            return

        if t == "binary_expression":
            op = binary_op(node, src)
            if op in LOGICAL_OPS:
                total += 1
            for c in node.children:
                walk(c)
            return

        for c in node.children:
            walk(c)

    walk(body)
    return total


def unit_label(node: Node, src: bytes) -> str:
    name = get_name(node, src)
    if name:
        return name
    if node.type == "method_definition":
        return "method"
    if node.type in FUNCTION_EXPR:
        return "anonymous"
    return "function"


def lang_for_path(path: Path, vue_lang: str | None = None) -> Language:
    if vue_lang == "ts":
        return TS_LANG
    if vue_lang == "tsx":
        return TSX_LANG
    if vue_lang in ("js", "jsx"):
        return JS_LANG
    suf = path.suffix.lower()
    if suf in TSX_EXTS:
        return TSX_LANG
    if suf in TS_EXTS:
        return TS_LANG
    return JS_LANG


# Point = (line_1based, col_0based) in the *original* file (Istanbul coords).
Point = tuple[int, int]
# Function span in Istanbul coords: start inclusive, end inclusive for containment.
FuncSpan = tuple[Point, Point, str, int]  # start, end, name, cc


def _point_in_span(pt: Point, start: Point, end: Point) -> bool:
    """True if pt is inside [start, end] (Istanbul start/end are inclusive-ish)."""
    if pt < start:
        return False
    if pt > end:
        return False
    return True


def _shift_point(line0: int, col: int, base_line0: int, base_col: int) -> Point:
    """Map a 0-based tree-sitter point inside an extracted script to file 1-based."""
    if line0 == 0:
        return (base_line0 + 1, base_col + col)
    return (base_line0 + line0 + 1, col)


def functions_from_source(
    src: bytes,
    lang: Language,
    *,
    base_line0: int = 0,
    base_col: int = 0,
) -> list[FuncSpan]:
    """Scored function spans in Istanbul (line 1-based, col 0-based) coords."""
    tree = _parser_for(lang).parse(src)
    root = tree.root_node
    units = collect_score_units(root)
    out: list[FuncSpan] = []
    for u in units:
        body = _function_body(u)
        cc = cyclomatic_of_body(body, src)
        # Use the full function node range (decl + body) so statement locs
        # that Istanbul places on the signature still attribute.
        sl, sc = u.start_point
        el, ec = u.end_point
        start = _shift_point(sl, sc, base_line0, base_col)
        end = _shift_point(el, ec, base_line0, base_col)
        out.append((start, end, unit_label(u, src), cc))
    return out


def functions_for_building(abs_path: Path) -> list[FuncSpan]:
    suf = abs_path.suffix.lower()
    try:
        raw = abs_path.read_bytes()
    except OSError as e:
        print(f"warn: cannot read {abs_path}: {e}", file=sys.stderr)
        return []

    if suf in VUE_EXTS:
        text = raw.decode("utf-8", errors="replace")
        spans: list[FuncSpan] = []
        for body, vlang, line0, col in extract_vue_scripts_with_offset(text):
            lang = lang_for_path(abs_path, vlang)
            spans.extend(
                functions_from_source(body, lang, base_line0=line0, base_col=col)
            )
        return spans

    if suf not in SCORE_EXTS:
        return []
    return functions_from_source(raw, lang_for_path(abs_path))


def _innermost_func(
    pt: Point, funcs: list[FuncSpan]
) -> Optional[int]:
    """Index of the innermost function containing pt, or None."""
    best: Optional[int] = None
    best_area: Optional[tuple[Point, Point]] = None
    for i, (start, end, _name, _cc) in enumerate(funcs):
        if not _point_in_span(pt, start, end):
            continue
        if best is None:
            best = i
            best_area = (start, end)
            continue
        assert best_area is not None
        # Smaller span wins (innermost).
        if start >= best_area[0] and end <= best_area[1]:
            best = i
            best_area = (start, end)
    return best


# ---------------------------------------------------------------------------
# Acceptance: file-level statement totals only
# ---------------------------------------------------------------------------


def acceptance_totals(
    reports: list[str],
) -> dict[str, tuple[int, int]]:
    """{rel: (covered, total)} from acceptance JSON statement maps."""
    maps = [_load_istanbul(p) for p in reports]
    merged = _filter_coverage_paths(_merge_file_maps([m for m in maps if m]))
    out: dict[str, tuple[int, int]] = {}
    for rel, entry in merged.items():
        stmts = entry.get("statements") or []
        if not stmts:
            continue
        total = len(stmts)
        covered = sum(1 for _lk, h in stmts if h > 0)
        out[rel] = (covered, total)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    reports = report_paths()
    if not reports:
        print(
            "no coverage-final.json found (set CODECITY_COVERAGE to point at one); "
            "CRAP and coverage will be absent from this city",
            file=sys.stderr,
        )
        if os.path.exists(OUT_FILE):
            os.remove(OUT_FILE)
        return

    maps = [_load_istanbul(p) for p in reports]
    coverage = _filter_coverage_paths(_merge_file_maps([m for m in maps if m]))
    if not coverage:
        print(
            "coverage report(s) found but no city buildings matched; "
            "CRAP and coverage will be absent from this city",
            file=sys.stderr,
        )
        if os.path.exists(OUT_FILE):
            os.remove(OUT_FILE)
        return

    acceptance = acceptance_totals(acceptance_paths())

    # file -> [stmt_covered, stmt_total, worst CRAP, worst method, load, crappy, methods]
    per_file: dict[str, list] = defaultdict(lambda: [0, 0, 0.0, "", 0.0, 0, 0])

    for rel, entry in coverage.items():
        abs_path = Path(REPO_DIR) / rel.replace("/", os.sep)
        if not abs_path.is_file():
            continue
        funcs = functions_for_building(abs_path)
        if not funcs:
            continue

        # Per-function statement tallies.
        fn_cov = [[0, 0] for _ in funcs]  # covered, total
        for lk, hits in entry.get("statements") or []:
            # Attribute by statement start.
            pt: Point = (lk[0], lk[1])
            idx = _innermost_func(pt, funcs)
            if idx is None:
                continue
            fn_cov[idx][1] += 1
            if hits > 0:
                fn_cov[idx][0] += 1

        acc = per_file[rel]
        for i, (start, end, name, cc) in enumerate(funcs):
            covered, total = fn_cov[i]
            if total <= 0:
                # No attributable statements → skip (do not invent 0%/100%).
                continue
            if cc <= 0:
                continue
            cov_frac = covered / total
            value = crap(cc, cov_frac)
            acc[0] += covered
            acc[1] += total
            if value > acc[2]:
                acc[2] = value
                acc[3] = name
            acc[4] += value
            acc[5] += 1 if value > CRAP_THRESHOLD else 0
            acc[6] += 1

    per_file = {rel: acc for rel, acc in per_file.items() if acc[6]}
    rows = sorted(per_file.items(), key=lambda kv: kv[1][2], reverse=True)

    # Header-only TSV would turn HAS_CRAP on in Python while the page still
    # finds no coverage fields — delete instead so absence stays clean.
    if not rows:
        print(
            "coverage report(s) matched buildings but no scored methods; "
            "CRAP and coverage will be absent from this city",
            file=sys.stderr,
        )
        if os.path.exists(OUT_FILE):
            os.remove(OUT_FILE)
        return

    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# code-city coverage baseline, measured at {_head_sha()}\n")
        f.write(
            "file\tcov_covered\tcov_total\tcrap_max\tcrap_max_method\tcrap_load"
            "\tcrappy_methods\tmethods\tacc_covered\tacc_total\n"
        )
        for rel, (lc, lt, worst, worst_name, load, crappy, methods) in rows:
            ac, at = acceptance.get(rel, (0, 0))
            # acceptance totals: covered, total — mirror Java (ac, am+ac) layout
            # where parts[8]=acc_covered, parts[9]=acc_total.
            f.write(
                f"{rel}\t{lc}\t{lt}\t{worst:.1f}\t{worst_name}\t{load:.1f}"
                f"\t{crappy}\t{methods}\t{ac}\t{at}\n"
            )

    covered = sum(v[0] for v in per_file.values())
    total = sum(v[1] for v in per_file.values())
    pct = (100.0 * covered / total) if total else 0.0
    print(
        f"read {len(reports)} Istanbul report(s): {len(rows)} files, "
        f"{pct:.1f}% statement coverage (in scored functions)",
        file=sys.stderr,
    )
    if acceptance:
        acc_covered = sum(v[0] for v in acceptance.values())
        acc_total = sum(v[1] for v in acceptance.values())
        acc_pct = (100.0 * acc_covered / acc_total) if acc_total else 0.0
        print(
            f"...of which the acceptance suite alone reaches {acc_pct:.1f}% "
            f"over {len(acceptance)} files",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
