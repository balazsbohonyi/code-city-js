#!/usr/bin/env python3
"""Sonar-style cognitive complexity for JS/TS (and Vue SFC scripts).

Ports the algorithm used by Victor's Java Code City
(https://www.sonarsource.com/docs/CognitiveComplexity.pdf) onto
tree-sitter-javascript / tree-sitter-typescript. Writes
`complexity-per-file.tsv` for `build_heatmap.py` to join.

Intentional JS-city delta (ADR 0009): `??` counts in boolean groups like
`&&` / `||`. Optional chaining (`?.`) does not. Vue templates are not scored
— only inline `<script>` / `<script setup>`.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from citylib import (
    PRUNE_DIRS,
    counts_toward_diagram,
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
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return start


REPO = Path(os.environ.get("HEATMAP_REPO") or _git_root(_here)).resolve()
OUT_DIR = Path(os.environ.get("HEATMAP_OUT") or str(REPO)).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)
EXTRA_PRUNE = frozenset(d for d in os.environ.get("HEATMAP_PRUNE", "").split(",") if d)
PRUNE = PRUNE_DIRS | set(EXTRA_PRUNE)

# Extensions we can score. .svelte stays a building with complexity 0 (ADR 0009).
JS_EXTS = {".js", ".mjs", ".cjs", ".jsx"}
TS_EXTS = {".ts", ".mts", ".cts"}
TSX_EXTS = {".tsx"}
VUE_EXTS = {".vue"}
SCORE_EXTS = JS_EXTS | TS_EXTS | TSX_EXTS | VUE_EXTS

# ---------------------------------------------------------------------------
# Vue SFC script extract
# ---------------------------------------------------------------------------

_SCRIPT_RE = re.compile(
    r"<script\b([^>]*)>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def extract_vue_scripts(source: str) -> list[tuple[bytes, str]]:
    """Return [(script_bytes, lang_tag)] for inline script blocks.

    lang_tag is 'ts' or 'js'. External `src=` scripts are skipped (those files
    are buildings on their own if they live in the repo).
    """
    out: list[tuple[bytes, str]] = []
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
            elif tag in ("tsx",):
                lang = "tsx"
            elif tag in ("jsx",):
                lang = "jsx"
        out.append((body.encode("utf-8"), lang))
    return out


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------

FUNCTION_DECL = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
}
# Expressions that may be scored as their own unit or folded as lambdas.
FUNCTION_EXPR = {"arrow_function", "function_expression", "generator_function"}

CLASS_LIKE = {"class_declaration", "class", "abstract_class_declaration"}

NESTING_STRUCTURES = {
    "if_statement",
    "ternary_expression",
    "conditional_type",  # not scored as control flow for values; ignored below
    "switch_statement",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
}

BOOL_OPS = {"&&", "||", "??"}  # ?? = intentional ADR 0009 delta


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


def is_top_level_boolean(node: Node, src: bytes) -> bool:
    """True when this &&/||/?? binary_expression is the top of its chain."""
    parent = node.parent
    if parent is None:
        return True
    if parent.type == "parenthesized_expression":
        # Still top of the *logical* chain for Sonar if the paren wraps the group;
        # only a parent binary with a bool op means we are not the top.
        return True
    if parent.type == "binary_expression" and binary_op(parent, src) in BOOL_OPS:
        return False
    return True


def boolean_groups(expr: Node, src: bytes) -> int:
    """Sonar distinct contiguous runs of && / || / ?? beyond the first group.

    a && b && c     -> 1
    a && b || c     -> 2
    a && b ?? c     -> 2  (?? is a group change under ADR 0009)
    """
    ops: list[str] = []

    def collect(n: Node) -> None:
        if n.type == "binary_expression":
            op = binary_op(n, src)
            if op in BOOL_OPS:
                left = n.child_by_field_name("left")
                right = n.child_by_field_name("right")
                if left is not None:
                    collect(left)
                ops.append(op)
                if right is not None:
                    collect(right)
                return
        if n.type == "parenthesized_expression":
            for c in n.children:
                if c.is_named:
                    collect(c)
            return

    collect(expr)
    if not ops:
        return 0
    groups = 1
    for i in range(1, len(ops)):
        if ops[i] != ops[i - 1]:
            groups += 1
    return groups


def _is_scored_unit_expr(node: Node) -> bool:
    """Arrow/function_expression that should be scored on its own (not a lambda)."""
    if node.type not in FUNCTION_EXPR:
        return False
    parent = node.parent
    if parent is None:
        return True
    # const f = () => {}  /  let f = function(){}
    if parent.type == "variable_declarator":
        return parent.child_by_field_name("value") == node
    # obj.f = () => {}
    if parent.type == "assignment_expression":
        return parent.child_by_field_name("right") == node
    # { f: () => {} } or class fields
    if parent.type in ("pair", "public_field_definition", "field_definition"):
        return True
    # export default () => {}
    if parent.type == "export_statement":
        return True
    return False


def _function_body(node: Node) -> Optional[Node]:
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    # Some grammars put the body as the last named child.
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


# ---------------------------------------------------------------------------
# Complexity walk (one function / lambda body)
# ---------------------------------------------------------------------------


def compute_body_complexity(body: Node, src: bytes, enclosing_name: Optional[str]) -> int:
    """Cognitive complexity of one function body (Sonar rules + ?? delta)."""
    if body is None:
        return 0
    total = 0

    def walk(node: Node, nesting: int) -> None:
        nonlocal total
        t = node.type

        # Nested class bodies are scored via their own methods when collected.
        if t in CLASS_LIKE:
            return

        # Nested function declarations / methods: scored as their own units.
        if t in FUNCTION_DECL:
            return

        # Arrow / function_expression: own unit or lambda.
        if t in FUNCTION_EXPR:
            if _is_scored_unit_expr(node):
                return
            # Lambda: body contributes to enclosing with nesting+1.
            lam_body = _function_body(node)
            if lam_body is not None:
                walk(lam_body, nesting + 1)
            return

        if t == "if_statement":
            total += 1 + nesting
            cond = node.child_by_field_name("condition")
            cons = node.child_by_field_name("consequence")
            alt = node.child_by_field_name("alternative")
            if cond is not None:
                walk(cond, nesting)
            if cons is not None:
                walk(cons, nesting + 1)
            if alt is not None:
                _handle_else(alt, nesting)
            return

        if t == "ternary_expression":
            total += 1 + nesting
            cond = node.child_by_field_name("condition")
            cons = node.child_by_field_name("consequence")
            alt = node.child_by_field_name("alternative")
            # tree-sitter-js often uses anonymous children; fall back.
            if cond is None and cons is None:
                named = [c for c in node.children if c.is_named]
                for i, c in enumerate(named):
                    # condition at nesting, branches at nesting+1
                    walk(c, nesting if i == 0 else nesting + 1)
                return
            if cond is not None:
                walk(cond, nesting)
            if cons is not None:
                walk(cons, nesting + 1)
            if alt is not None:
                walk(alt, nesting + 1)
            return

        if t == "switch_statement":
            total += 1 + nesting
            for c in node.children:
                walk(c, nesting + 1)
            return

        if t in ("for_statement", "for_in_statement", "while_statement", "do_statement"):
            total += 1 + nesting
            body_node = node.child_by_field_name("body")
            body_id = (body_node.start_byte, body_node.end_byte) if body_node else None
            for c in node.children:
                if body_id is not None and (c.start_byte, c.end_byte) == body_id:
                    walk(c, nesting + 1)
                else:
                    walk(c, nesting)
            return

        if t == "catch_clause":
            total += 1 + nesting
            for c in node.children:
                walk(c, nesting + 1)
            return

        if t in ("break_statement", "continue_statement"):
            for c in node.children:
                if c.type == "identifier":
                    total += 1
                    break
            return

        if t == "binary_expression":
            op = binary_op(node, src)
            if op in BOOL_OPS and is_top_level_boolean(node, src):
                total += boolean_groups(node, src)
            # fall through to recurse

        if t == "call_expression" and enclosing_name:
            # Recursion: f(...) where f is the enclosing function name.
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "identifier" and node_text(fn, src) == enclosing_name:
                total += 1
            # fall through

        for c in node.children:
            walk(c, nesting)

    def _handle_else(alt_node: Node, nesting: int) -> None:
        nonlocal total
        # else_clause wrapping an if_statement (else if) or a block (else).
        target = alt_node
        if alt_node.type == "else_clause":
            named = [c for c in alt_node.children if c.is_named]
            target = named[0] if named else alt_node

        if target.type == "if_statement":
            total += 1  # else-if: +1, no extra nesting bump for the else-if itself
            cond2 = target.child_by_field_name("condition")
            cons2 = target.child_by_field_name("consequence")
            alt2 = target.child_by_field_name("alternative")
            if cond2 is not None:
                walk(cond2, nesting)
            if cons2 is not None:
                walk(cons2, nesting + 1)
            if alt2 is not None:
                _handle_else(alt2, nesting)
        else:
            total += 1  # plain else
            walk(target, nesting + 1)

    walk(body, 0)
    return total


def compute_function_complexity(fn_node: Node, src: bytes) -> int:
    return compute_body_complexity(_function_body(fn_node), src, get_name(fn_node, src))


# ---------------------------------------------------------------------------
# Collect score units in a file
# ---------------------------------------------------------------------------


def collect_score_units(root: Node) -> list[Node]:
    """Function-like nodes scored independently (file total = sum)."""
    units: list[Node] = []

    def visit(node: Node) -> None:
        t = node.type
        if t in FUNCTION_DECL:
            units.append(node)
            # Still walk children so nested function_declarations are collected,
            # but skip the body of this function for *expression* discovery? No —
            # we need nested decls inside the body. Recurse into all children;
            # FUNCTION_DECL handler returns early in the complexity walk only.
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


def first_parse_error_hint(root: Node, src: bytes) -> str:
    """Short hint for stderr when tree-sitter marks ERROR/missing nodes.

    Common JS/TSX case: bare ``&`` in JSX text (``Title & Subtitle``) — the
    grammar expects ``&amp;`` or a ``{...}`` expression. We still score the
    file; this is a warning, not a drop.
    """
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            line = n.start_point[0] + 1
            snippet = src[n.start_byte : n.end_byte][:40]
            try:
                text = snippet.decode("utf-8", errors="replace").replace("\n", " ")
            except Exception:
                text = repr(snippet)
            return f"line {line}: {text!r}"
        stack.extend(reversed(n.children))
    return "tree has_error"


def complexity_of_source(src: bytes, lang: Language) -> tuple[int, int, bool, str]:
    """Return (file_complexity, unit_count, had_parse_error, error_hint)."""
    tree = _parser_for(lang).parse(src)
    root = tree.root_node
    had_error = root.has_error
    hint = first_parse_error_hint(root, src) if had_error else ""
    units = collect_score_units(root)
    total = 0
    for u in units:
        total += compute_function_complexity(u, src)

    # Top-level statements outside any scored unit (scripts / bare modules).
    # Avoid double-counting: walk program children that are not units and not
    # containers we already fully covered via units.
    covered = {(u.start_byte, u.end_byte) for u in units}

    def top_level_contrib(node: Node) -> int:
        if (node.start_byte, node.end_byte) in covered:
            return 0
        if node.type in FUNCTION_DECL or (node.type in FUNCTION_EXPR and _is_scored_unit_expr(node)):
            return 0
        if node.type in CLASS_LIKE:
            # methods collected as units; no extra top-level
            return 0
        if node.type in (
            "export_statement",
            "lexical_declaration",
            "variable_declaration",
            "expression_statement",
            "if_statement",
            "for_statement",
            "for_in_statement",
            "while_statement",
            "do_statement",
            "switch_statement",
            "try_statement",
            "labeled_statement",
        ):
            # If this node *contains* only scored units (e.g. export function),
            # still skip adding the wrapper; units already counted.
            if node.type == "export_statement":
                for c in node.children:
                    if c.is_named and (
                        c.type in FUNCTION_DECL
                        or (c.type in FUNCTION_EXPR and _is_scored_unit_expr(c))
                        or c.type in CLASS_LIKE
                    ):
                        return 0
            if node.type in ("lexical_declaration", "variable_declaration"):
                # const f = () => {} — unit already counted; no top-level add.
                for c in node.children:
                    if c.type == "variable_declarator":
                        val = c.child_by_field_name("value")
                        if val is not None and val.type in FUNCTION_EXPR:
                            return 0
            return compute_body_complexity(node, src, None)
        return 0

    if root.type == "program":
        for c in root.children:
            if c.is_named:
                total += top_level_contrib(c)

    return total, len(units), had_error, hint


def lang_for_path(path: Path, vue_lang: str | None = None) -> Language:
    if vue_lang == "ts":
        return TS_LANG
    if vue_lang == "tsx":
        return TSX_LANG
    if vue_lang in ("js", "jsx"):
        return JS_LANG if vue_lang == "js" else JS_LANG
    suf = path.suffix.lower()
    if suf in TSX_EXTS:
        return TSX_LANG
    if suf in TS_EXTS:
        return TS_LANG
    if suf == ".jsx":
        return JS_LANG  # JSX is in the JS grammar
    return JS_LANG


def process_file(abs_path: Path) -> tuple[str, int, int, bool, str]:
    """Return (rel, complexity, unit_count, error, error_hint)."""
    rel = posix_rel(str(abs_path), str(REPO))
    suf = abs_path.suffix.lower()
    try:
        raw = abs_path.read_bytes()
    except OSError as e:
        print(f"warn: cannot read {rel}: {e}", file=sys.stderr)
        return rel, 0, 0, True, str(e)

    if suf in VUE_EXTS:
        text = raw.decode("utf-8", errors="replace")
        scripts = extract_vue_scripts(text)
        if not scripts:
            return rel, 0, 0, False, ""
        total = 0
        units = 0
        err = False
        hint = ""
        for body, vlang in scripts:
            lang = lang_for_path(abs_path, vlang)
            c, u, e, h = complexity_of_source(body, lang)
            total += c
            units += u
            if e and not hint:
                hint = h
            err = err or e
        return rel, total, units, err, hint

    if suf not in SCORE_EXTS:
        return rel, 0, 0, False, ""

    lang = lang_for_path(abs_path)
    c, u, e, h = complexity_of_source(raw, lang)
    return rel, c, u, e, h


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in os.walk(REPO):
        parts = repo_rel_parts(root, str(REPO))
        if any(p == ".git" for p in parts) or any(p in PRUNE for p in parts):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".")]
        for fn in filenames:
            ap = Path(root) / fn
            rel = posix_rel(str(ap), str(REPO))
            if not counts_toward_diagram(rel):
                continue
            if ap.suffix.lower() not in SCORE_EXTS:
                continue
            files.append(ap)
    files.sort()
    return files


def main() -> int:
    files = iter_source_files()
    out_path = OUT_DIR / "complexity-per-file.tsv"
    rows: list[tuple[str, int, int, int]] = []
    errors = 0
    for i, p in enumerate(files):
        rel, cog, units, err, hint = process_file(p)
        if err:
            errors += 1
            extra = f" ({hint})" if hint else ""
            print(f"warn: parse errors in {rel}{extra}", file=sys.stderr)
        # class_count column unused for JS; keep Java TSV shape (file, complexity, …)
        rows.append((rel, cog, 0, units))
        if (i + 1) % 500 == 0:
            print(f"... processed {i + 1}/{len(files)}", file=sys.stderr)

    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("file\tfile_complexity\tclass_count\tmethod_count\n")
        for rel, cog, classes, methods in rows:
            f.write(f"{rel}\t{cog}\t{classes}\t{methods}\n")

    print(f"wrote complexity for {len(rows)} files to {out_path}", file=sys.stderr)
    print(f"files with parse errors: {errors}", file=sys.stderr)
    top = sorted(rows, key=lambda r: r[1], reverse=True)[:10]
    print("top 10 files by complexity:", file=sys.stderr)
    for rel, cog, _c, methods in top:
        print(f"  complexity={cog}  units={methods}  {rel}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
