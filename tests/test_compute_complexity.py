"""Unit tests for Sonar-style cognitive complexity (ADR 0009)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compute_complexity import (  # noqa: E402
    JS_LANG,
    TS_LANG,
    complexity_of_source,
    extract_vue_scripts,
)


def _score(src: str, lang=JS_LANG) -> int:
    c, _units, _err = complexity_of_source(src.encode("utf-8"), lang)
    return c


def test_empty_function():
    assert _score("function f(){}") == 0


def test_if_else_elseif():
    assert _score("function f(){ if (a) {} }") == 1
    assert _score("function f(){ if (a) {} else {} }") == 2
    assert _score("function f(){ if (a) {} else if (b) {} else {} }") == 3


def test_nesting():
    # outer if +1; inner if +1 + nesting1 = +2 → 3
    assert _score("function f(){ if (a) { if (b) {} } }") == 3


def test_boolean_groups():
    assert _score("function f(){ if (a && b && c) {} }") == 2
    assert _score("function f(){ if (a && b || c) {} }") == 3


def test_nullish_coalescing_counts():
    """ADR 0009 intentional delta: ?? is a boolean-group operator."""
    assert _score("function f(){ if (a ?? b) {} }") == 2
    assert _score("function f(){ if (a && b ?? c) {} }") == 3


def test_optional_chain_does_not_count():
    assert _score("function f(){ const x = a?.b?.c; }") == 0


def test_ternary_for_switch_catch():
    assert _score("function f(){ return a ? 1 : 2 }") == 1
    assert _score("function f(){ for (;;) {} }") == 1
    assert _score("function f(){ switch (x) { case 1: break } }") == 1
    assert _score("function f(){ try {} catch (e) {} }") == 1


def test_arrow_unit_and_lambda():
    assert _score("const f = () => { if (a) {} }") == 1
    # lambda body at nesting+1 → if costs 2
    assert _score("function f(){ x.map(y => { if (y) {} }) }") == 2


def test_nested_function_scored_separately():
    # outer empty of structures; inner if = 1; file sum = 1
    src = "function f(){ function g(){ if (a) {} } }"
    c, units, err = complexity_of_source(src.encode(), JS_LANG)
    assert not err
    assert units == 2
    assert c == 1


def test_typescript_types_do_not_inflate():
    src = """
    type Foo = { a: string };
    interface Bar { b: number }
    function f(x: Foo | Bar) { if (x) {} }
    """
    assert _score(src, TS_LANG) == 1


def test_vue_script_extract_and_score():
    vue = """
    <template><div v-if="x">{{ y }}</div></template>
    <script setup lang="ts">
    function f(){ if (a) { if (b) {} } }
    </script>
    """
    scripts = extract_vue_scripts(vue)
    assert len(scripts) == 1
    assert scripts[0][1] == "ts"
    c, units, err = complexity_of_source(scripts[0][0], TS_LANG)
    assert not err
    assert units == 1
    assert c == 3


def test_vue_skips_external_src():
    vue = '<script src="./foo.ts"></script>\n<script>function f(){ if (a) {} }</script>'
    scripts = extract_vue_scripts(vue)
    assert len(scripts) == 1
    c, _, _ = complexity_of_source(scripts[0][0], JS_LANG)
    assert c == 1
