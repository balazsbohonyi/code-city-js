import os
from pathlib import Path

import pytest

from compute_complexity import (
    JS_LANG,
    TS_LANG,
    TSX_LANG,
    boolean_groups,
    complexity_of_source,
    complexity_of_vue_template,
    extract_vue_scripts,
    extract_vue_template,
    process_file,
)


def _score_js(src: str) -> int:
    c, _units, _err, _hint = complexity_of_source(src.encode("utf-8"), JS_LANG)
    return c


def _score_ts(src: str) -> int:
    c, _units, _err, _hint = complexity_of_source(src.encode("utf-8"), TS_LANG)
    return c


def _score_tsx(src: str) -> int:
    c, _units, _err, _hint = complexity_of_source(src.encode("utf-8"), TSX_LANG)
    return c


def test_empty_file():
    assert _score_js("") == 0
    assert _score_ts("") == 0


def test_single_if_no_nesting():
    src = "function f(x) { if (x) { return 1; } return 0; }"
    assert _score_js(src) == 1


def test_nested_if_gets_nesting_penalty():
    src = """
    function f(a, b) {
        if (a) {
            if (b) {
                return 1;
            }
        }
        return 0;
    }
    """
    # outer if: +1 (nesting 0)
    # inner if: +1 + 1 (nesting 1) = 2
    # total = 3
    assert _score_js(src) == 3


def test_if_else_chain():
    src = """
    function f(x) {
        if (x === 1) { return 1; }
        else if (x === 2) { return 2; }
        else if (x === 3) { return 3; }
        else { return 0; }
    }
    """
    # if: +1, else-if: +1, else-if: +1, else: +1 = 4
    assert _score_js(src) == 4


def test_for_and_while_loops():
    src = """
    function f(arr) {
        for (let i = 0; i < arr.length; i++) {
            while (arr[i] > 0) {
                arr[i]--;
            }
        }
    }
    """
    # for: +1 (nesting 0)
    # while: +1 + 1 (nesting 1) = 2
    # total = 3
    assert _score_js(src) == 3


def test_catch_clause():
    src = """
    function f() {
        try {
            risky();
        } catch (e) {
            if (e) { log(e); }
        }
    }
    """
    # catch: +1 (nesting 0)
    # if inside catch: +1 + 1 (nesting 1) = 2
    # total = 3
    assert _score_js(src) == 3


def test_switch_statement():
    src = """
    function f(x) {
        switch (x) {
            case 1:
                if (ok()) { return 1; }
                break;
            default:
                break;
        }
    }
    """
    # switch: +1
    # if inside switch: +1 + 1 (nesting 1) = 2
    # total = 3
    assert _score_js(src) == 3


def test_ternary_with_nesting():
    src = "function f(a, b) { return a ? (b ? 1 : 2) : 3; }"
    # outer ternary: +1
    # inner ternary: +1 + 1 (nesting 1) = 2
    # total = 3
    assert _score_js(src) == 3


def test_nullish_coalescing_counts():
    """ADR 0009 intentional delta: ?? is a boolean-group operator."""
    assert _score_js("function f(){ if (a ?? b) {} }") == 2
    assert _score_js("function f(){ if (a && b ?? c) {} }") == 3


def test_boolean_chain_in_if():
    src = "function f(a, b, c) { if (a && b && c) { return 1; } }"
    # if (+1) + contiguous && run (+1) = 2
    assert _score_js(src) == 2

    src_alt = "function f(a, b, c) { if (a && b || c) { return 1; } }"
    # if (+1) + && group (+1) + || group (+1) = 3
    assert _score_js(src_alt) == 3


def test_optional_chaining_is_not_scored():
    # ADR 0009: ?. is not cognitive complexity
    src = "function f(a) { return a?.b?.c?.(); }"
    assert _score_js(src) == 0


def test_top_level_statements_scored():
    # Statements outside any function still count
    src = """
    if (process.env.NODE_ENV === 'test') {
        runTests();
    }
    for (let i = 0; i < 5; i++) {
        log(i);
    }
    """
    # if (+1) + for (+1) = 2
    assert _score_js(src) == 2


def test_typescript_types_ignored():
    src = """
    type MyType<T> = T extends string ? true : false;
    interface Foo {
        bar?: string;
    }
    function f(x: number): boolean {
        return x > 0;
    }
    """
    assert _score_ts(src) == 0


def test_vue_sfc_script_extraction():
    vue = """
    <template>
        <div>{{ count }}</div>
    </template>
    <script lang="ts">
    function f(x: number) {
        if (x > 0) return true;
        return false;
    }
    </script>
    <script setup lang="ts">
    if (a && b) {
        doSomething();
    }
    </script>
    """
    scripts = extract_vue_scripts(vue)
    assert len(scripts) == 2
    assert scripts[0][1] == "ts"
    assert b"function f" in scripts[0][0]
    assert scripts[1][1] == "ts"
    assert b"if (a && b)" in scripts[1][0]


# ---------------------------------------------------------------------------
# Vue SFC template complexity tests (ADR 0012)
# ---------------------------------------------------------------------------


def test_vue_template_empty_and_plain():
    assert extract_vue_template("") is None
    assert extract_vue_template("<script></script>") is None

    plain = "<template><div><p>Hello world</p></div></template>"
    extracted = extract_vue_template(plain)
    assert extracted is not None
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 0


def test_vue_template_v_if():
    tmpl = '<template><div v-if="show"><p>Visible</p></div></template>'
    extracted = extract_vue_template(tmpl)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1
    assert units == 1


def test_vue_template_v_if_else_chain():
    tmpl = """
    <template>
      <div v-if="a">A</div>
      <div v-else-if="b">B</div>
      <div v-else>C</div>
    </template>
    """
    extracted = extract_vue_template(tmpl)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if (1) + v-else-if (1) + v-else (1) = 3
    assert c == 3
    assert units == 3


def test_vue_template_nested_directives_nesting_penalty():
    tmpl = """
    <template>
      <ul v-for="user in users">
        <li v-if="user.isActive">
          <span v-if="user.isAdmin">Admin</span>
        </li>
      </ul>
    </template>
    """
    extracted = extract_vue_template(tmpl)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-for: 1 + nesting(0) = 1 (nesting becomes 1)
    # v-if="user.isActive": 1 + nesting(1) = 2 (nesting becomes 2)
    # v-if="user.isAdmin": 1 + nesting(2) = 3
    # total = 1 + 2 + 3 = 6
    assert c == 6
    assert units == 3


def test_vue_template_boolean_expressions():
    tmpl = '<template><div v-if="a && b || c">Content</div></template>'
    extracted = extract_vue_template(tmpl)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if structural: 1
    # a && b || c: && group (1) + || group (1) = 2
    # total = 1 + 2 = 3
    assert c == 3


def test_vue_template_interpolations_and_bindings():
    tmpl = """
    <div :class="isDark ? 'dark' : 'light'">
      <span>{{ show ? (foo ? 1 : 2) : 3 }}</span>
    </div>
    """
    c, units, err, _ = complexity_of_vue_template(tmpl)
    assert not err
    # :class ternary at nesting 0 -> 1
    # {{ show ? ... }} outer ternary at nesting 0 -> 1, inner ternary at nesting 1 -> 2: sum = 3
    # total = 1 + 3 = 4
    assert c == 4


def test_vue_nested_template_tags():
    vue = """
    <template>
      <div class="wrapper">
        <template v-if="outer">
          <p v-if="inner">Nested</p>
        </template>
      </div>
    </template>
    """
    extracted = extract_vue_template(vue)
    assert extracted is not None
    assert 'template v-if="outer"' in extracted
    assert "</template>" in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if="outer": 1 (nesting 0)
    # v-if="inner": 1 + 1 = 2 (nesting 1)
    # total = 3
    assert c == 3


def test_vue_file_combined_script_and_template(tmp_path):
    vue_file = tmp_path / "Component.vue"
    vue_file.write_text(
        """
        <template>
          <div v-if="visible">
            <span v-if="count > 0">{{ count }}</span>
          </div>
        </template>
        <script setup lang="ts">
        function test(x: number) {
          if (x > 10) {
            return true;
          }
          return false;
        }
        </script>
        """,
        encoding="utf-8",
    )
    rel, cog, units, err, hint = process_file(vue_file)
    assert not err
    # Template: v-if="visible" (1) + v-if="count > 0" (2) = 3
    # Script: if (x > 10) = 1
    # Total cognitive complexity = 4
    assert cog == 4


# ---------------------------------------------------------------------------
# Vue edge cases and probes (ADR 0012 hardening)
# ---------------------------------------------------------------------------


def test_vue_template_interpolation_with_less_than():
    # HTMLParser normally breaks on '<' in text nodes; must be protected
    tmpl1 = "<template><div>{{ count < 10 ? 'lo' : 'hi' }}</div></template>"
    c1, _, err1, _ = complexity_of_vue_template(extract_vue_template(tmpl1))
    assert not err1
    assert c1 == 1

    tmpl2 = "<template><div>{{ a > b ? 1 : 2 }}</div></template>"
    c2, _, err2, _ = complexity_of_vue_template(extract_vue_template(tmpl2))
    assert not err2
    assert c2 == 1

    tmpl3 = "<template><div>{{ a < b }}</div></template>"
    c3, _, err3, _ = complexity_of_vue_template(extract_vue_template(tmpl3))
    assert not err3
    assert c3 == 0


def test_vue_template_ignored_directives():
    # v-show is purely CSS display toggle and does not introduce control flow
    tmpl = '<template><div v-show="a && b ? 1 : 2"></div></template>'
    c, _, err, _ = complexity_of_vue_template(extract_vue_template(tmpl))
    assert not err
    assert c == 0


def test_vue_template_dynamic_bindings_and_events():
    tmpl = """
    <template>
      <div v-html="ok ? a : b"></div>
      <div v-bind="active ? x : y"></div>
      <button @click="canSubmit ? submit() : cancel()"></button>
      <span v-text="valid ? 'yes' : 'no'"></span>
      <input v-model="mode ? first : second" />
    </template>
    """
    c, _, err, _ = complexity_of_vue_template(extract_vue_template(tmpl))
    assert not err
    # Each ternary at nesting 0 = 1; 5 directives = 5
    assert c == 5


def test_vue_template_v_pre_skips_subtree():
    tmpl = """
    <template>
      <div v-pre>
        <span v-if="ok ? 1 : 2">{{ a ? b : c }}</span>
      </div>
    </template>
    """
    c, units, err, _ = complexity_of_vue_template(extract_vue_template(tmpl))
    assert not err
    assert c == 0
    assert units == 0


def test_vue_sfc_script_first_does_not_steal_template():
    vue = """
    <script setup lang="ts">
    const stolenTemplate = '<template v-if="stolen ? 1 : 2">stolen</template>';
    </script>
    <template v-if="count > 0">
      <div>{{ count < 5 ? 1 : 2 }}</div>
    </template>
    """
    extracted = extract_vue_template(vue)
    assert "stolen" not in extracted
    assert 'template v-if="count > 0"' in extracted
    c, _, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # Root tag v-if="count > 0": 1 (nesting 0, nesting becomes 1)
    # {{ count < 5 ? 1 : 2 }}: ternary at nesting 1 = 1 + 1 = 2
    # total = 3
    assert c == 3


def test_vue_template_tag_with_greater_than_in_attr():
    vue = '<template v-if="count > 0"><div>hello</div></template>'
    extracted = extract_vue_template(vue)
    assert extracted is not None
    assert 'v-if="count > 0"' in extracted
    c, _, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1


def test_vue_same_element_v_if_and_v_for():
    # Vue 3 evaluates v-if first, v-for second
    vue = '<template><div v-if="ok" v-for="item in items">{{ item < 5 ? 1 : 2 }}</div></template>'
    extracted = extract_vue_template(vue)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if at nesting 0: +1 (nesting becomes 1)
    # v-for at nesting 1: +1 + 1 = 2 (nesting becomes 2)
    # ternary at nesting 2: 1 + 2 = 3
    # total = 1 + 2 + 3 = 6
    assert c == 6
    assert units == 2


def test_vue_external_template_and_fragments():
    # External src template returns None
    src_vue = '<template src="./external.html"></template>'
    assert extract_vue_template(src_vue) is None

    # Vue 3 multiple root templates (fragments)
    frag_vue = """
    <template v-if="mode === 'a'">
      <div>A</div>
    </template>
    <template v-else>
      <div>B</div>
    </template>
    """
    extracted = extract_vue_template(frag_vue)
    assert extracted is not None
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if (1) + v-else (1) = 2
    assert c == 2


def test_vue_template_expression_error_handling():
    # Malformed JS inside directive logs error hint but does not crash.
    # v-if="a +++ ? :" directive adds 1 (structural branch); expression fails parse -> 0.
    # v-if="ok" adds 1 (structural branch); expression 'ok' -> 0.
    # Total complexity = 2; err is True.
    tmpl = '<template><div v-if="a +++ ? :"></div><p v-if="ok">Valid</p></template>'
    extracted = extract_vue_template(tmpl)
    c, units, err, hint = complexity_of_vue_template(extracted)
    assert err
    assert hint != ""
    assert c == 2


def test_vue_template_closing_tag_in_comment_or_quote():
    # Bug fix: comments containing </template> or quoted attributes with '</template>'
    # must not prematurely terminate the template body.
    sfc = """
    <template>
      <!-- </template> -->
      <!-- <template v-if="commentedOut">Ignored</template> -->
      <div :title="'</template>'">
        <div v-if="active">Active Branch</div>
      </div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert 'v-if="active"' in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if="active" -> 1
    assert c == 1


def test_vue_custom_blocks_and_src_fallback_ignored():
    # Suggestion fix: custom blocks (<docs>, <i18n>) containing sample <template>
    # and <template src=...> with fallback inner markup must be skipped.
    sfc = """
    <docs>
      <template v-if="sample ? 1 : 2">
        <span>Sample code in docs</span>
      </template>
    </docs>
    <i18n>
      { "en": { "hello": "world" } }
    </i18n>
    <template src="./external.html">
      <div v-if="fallbackBranch">Fallback markup</div>
    </template>
    <template>
      <div v-if="realBranch">Live Content</div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert 'sample' not in extracted
    assert 'fallbackBranch' not in extracted
    assert 'realBranch' in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1


def test_vue_v_model_argument_and_modifier_forms():
    # Suggestion fix: v-model:prop and v-model.modifier forms score their expressions.
    tmpl = """
    <template>
      <input v-model:title="ok ? a : b" />
      <input v-model.trim="ready ? x : y" />
      <input v-model:custom.lazy="flag ? 1 : 2" />
    </template>
    """
    extracted = extract_vue_template(tmpl)
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # 3 ternaries = 3
    assert c == 3


def test_vue_method_count_reflects_script_functions_only(tmp_path):
    # Suggestion fix: method_count in complexity-per-file.tsv should strictly count
    # script functions; template directives contribute to cognitive_complexity but not method units.
    sfc_template_only = tmp_path / "TemplateOnly.vue"
    sfc_template_only.write_text(
        """
        <template>
          <div v-if="a">
            <span v-if="b">Test</span>
          </div>
        </template>
        """,
        encoding="utf-8",
    )
    rel, cog, units, err, _ = process_file(sfc_template_only)
    assert not err
    assert cog == 3  # v-if (1) + nested v-if (1 + 1) = 3
    assert units == 0  # 0 script functions, not 2 methods!

    sfc_with_script = tmp_path / "WithScript.vue"
    sfc_with_script.write_text(
        """
        <template>
          <div v-if="a">Branch</div>
        </template>
        <script>
        export default {
          methods: {
            foo() { return 1; },
            bar() { return 2; }
          }
        }
        </script>
        """,
        encoding="utf-8",
    )
    rel2, cog2, units2, err2, _ = process_file(sfc_with_script)
    assert not err2
    assert cog2 == 1  # 1 from v-if
    assert units2 == 2  # 2 functions (foo, bar)


def test_vue_interpolation_containing_closing_template_string():
    # Bug fix: mustaches containing '</template>' string literal must not close the template body.
    sfc = """
    <template>
      <span>{{ '</template>' }}</span>
      <div v-if="afterMustache">Kept</div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert 'afterMustache' in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1


def test_vue_self_closing_template_tags_top_level_and_nested():
    # Bug fix: self-closing <template ... /> must not increment nest depth or eat closers.
    sfc = """
    <template src="./external.html" />
    <template>
      <template #header />
      <div v-if="content">Body</div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert 'content' in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1


def test_vue_src_attribute_scanner_no_false_positives():
    # Bug fix: :src, v-if="src === 'a'", v-if="src==1" must not be mistaken for external src=
    sfc = """
    <template v-if="src === 'a'">
      <img :src="avatarUrl" />
      <div v-if="inner">Branch A</div>
    </template>
    <template v-else-if="a && src == 1">
      <div v-if="nested">Branch B</div>
    </template>
    <template v-else>
      <div>Branch C</div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert "src === 'a'" in extracted
    assert "Branch A" in extracted
    assert "Branch B" in extracted
    assert "Branch C" in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    # v-if (1) + nested v-if (1 + 1) + v-else-if (1) + && group (1) + nested v-if (1 + 1) + v-else (1) = 8
    assert c == 8


def test_has_src_attr_scanner():
    from compute_complexity import has_src_attr
    assert has_src_attr('src="./external.html"') is True
    assert has_src_attr('lang="ts" src="./foo.vue"') is True
    assert has_src_attr('src') is True
    assert has_src_attr(':src="foo"') is False
    assert has_src_attr('v-bind:src="foo"') is False
    assert has_src_attr('data-src="foo"') is False
    assert has_src_attr('v-if="src === \'a\'"') is False
    assert has_src_attr('v-if="a && src == 1"') is False
    assert has_src_attr('v-if="src==1"') is False


def test_has_src_attr_trailing_slash_no_hang():
    # Bug fix: has_src_attr must not spin into an infinite loop on trailing slashes or malformed punctuation
    from compute_complexity import has_src_attr
    assert has_src_attr('v-if="a" / ') is False
    assert has_src_attr('/ >') is False
    assert has_src_attr('===') is False
    assert has_src_attr('src="foo.html" / ') is True


def test_vue_rcdata_tags_inside_template():
    # Bug fix: </template> inside <textarea>, <title>, <script>, or <style> must not close the template body.
    sfc = """
    <template>
      <textarea>
        </template>
      </textarea>
      <script>
        const s = "</template>";
      </script>
      <style>
        /* </template> */
      </style>
      <div v-if="afterRcdata">Kept</div>
    </template>
    """
    extracted = extract_vue_template(sfc)
    assert extracted is not None
    assert 'afterRcdata' in extracted
    c, units, err, _ = complexity_of_vue_template(extracted)
    assert not err
    assert c == 1
