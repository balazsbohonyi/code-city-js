"""Unit + fixture tests for v4 CRAP (ADR 0011)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compute_crap import (  # noqa: E402
    JS_LANG,
    _function_body,
    _parser_for,
    _path_glob_match,
    collect_score_units,
    coverage_path_allowed,
    crap,
    cyclomatic_of_body,
    functions_for_building,
    normalize_report_path,
)

FIXTURE = ROOT / "tests" / "fixtures" / "crap"


def _cc(src: str) -> int:
    tree = _parser_for(JS_LANG).parse(src.encode("utf-8"))
    units = collect_score_units(tree.root_node)
    assert len(units) == 1
    body = _function_body(units[0])
    return cyclomatic_of_body(body, src.encode("utf-8"))


def test_crap_formula_examples():
    assert crap(1, 1.0) == 1.0
    assert crap(1, 0.0) == 2.0
    assert crap(5, 1.0) == 5.0
    assert crap(5, 0.0) == 30.0
    assert crap(10, 0.0) == 110.0
    assert crap(2, 0.5) == 2.5
    assert crap(6, 0.0) == 42.0


def test_cyclomatic_straight_and_branches():
    assert _cc("function f(){ return 1; }") == 1
    assert _cc("function f(){ if (a) { return 1; } }") == 2
    assert _cc("function f(){ if (a) {} else {} }") == 2  # else does not add
    assert _cc("function f(){ if (a) {} else if (b) {} }") == 3
    assert _cc("function f(){ return a ? 1 : 2; }") == 2
    assert _cc("function f(){ for (;;) {} }") == 2
    assert _cc("function f(){ while (a) {} }") == 2
    assert _cc("function f(){ try {} catch (e) {} }") == 2
    assert _cc("function f(){ if (a && b) {} }") == 3  # if + &&
    assert _cc("function f(){ if (a || b || c) {} }") == 4  # if + two ||
    assert _cc("function f(){ switch (x) { case 1: break; case 2: break; default: break; } }") == 3


def test_nullish_not_cyclomatic():
    """?? is cognitive (ADR 0009) but not McCabe here."""
    assert _cc("function f(){ return a ?? b; }") == 1


def test_fixture_function_spans_and_cc():
    straight = functions_for_building(FIXTURE / "src" / "straight.js")
    assert len(straight) == 1
    assert straight[0][2] == "straight"
    assert straight[0][3] == 1

    branched = functions_for_building(FIXTURE / "src" / "branched.js")
    assert branched[0][2] == "branched"
    assert branched[0][3] == 2

    risky = functions_for_building(FIXTURE / "src" / "risky.js")
    assert risky[0][2] == "risky"
    assert risky[0][3] == 6


def test_vue_script_function_spans_in_sfc_coords():
    """ADR 0011: report key is the .vue file; score <script> in file line coords."""
    vue = functions_for_building(FIXTURE / "src" / "Widget.vue")
    assert len(vue) == 1
    start, end, name, cc = vue[0]
    assert name == "score"
    assert cc == 2
    # Function lives in the SFC script block (not template-relative 1..n).
    assert start[0] == 6
    assert end[0] == 11


def test_normalize_relative_under_repo(monkeypatch):
    monkeypatch.setattr("compute_crap.REPO_DIR", str(FIXTURE))
    assert normalize_report_path("src/straight.js") == "src/straight.js"
    assert normalize_report_path(str(FIXTURE / "src" / "branched.js")) == "src/branched.js"
    assert normalize_report_path("src/Widget.vue") == "src/Widget.vue"
    assert normalize_report_path("src/missing-not-a-building.txt") is None


@pytest.fixture()
def crap_tsv(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    env["CODECITY_COVERAGE"] = str(FIXTURE / "coverage" / "coverage-final.json")
    env["CODECITY_COVERAGE_ACCEPTANCE"] = str(
        FIXTURE / "coverage" / "acceptance-final.json"
    )
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    tsv = out / "crap-per-file.tsv"
    assert tsv.is_file(), proc.stderr
    return tsv, proc.stderr


def _rows(tsv: Path) -> dict[str, dict[str, str]]:
    lines = tsv.read_text(encoding="utf-8").splitlines()
    header = None
    rows = {}
    for line in lines:
        if line.startswith("#"):
            continue
        if header is None:
            header = line.split("\t")
            continue
        parts = line.split("\t")
        row = dict(zip(header, parts))
        rows[row["file"]] = row
    return rows


def test_fixture_crap_goldens(crap_tsv):
    tsv, _err = crap_tsv
    rows = _rows(tsv)

    s = rows["src/straight.js"]
    assert s["crap_max_method"] == "straight"
    assert float(s["crap_max"]) == pytest.approx(1.0)
    assert int(s["cov_covered"]) == 1
    assert int(s["cov_total"]) == 1
    assert int(s["crappy_methods"]) == 0
    # Acceptance touched straight fully.
    assert int(s["acc_covered"]) == 1
    assert int(s["acc_total"]) == 1

    b = rows["src/branched.js"]
    assert b["crap_max_method"] == "branched"
    assert float(b["crap_max"]) == pytest.approx(2.5)
    assert int(b["cov_covered"]) == 1
    assert int(b["cov_total"]) == 2
    # Acceptance listed branched at 0/2.
    assert int(b["acc_covered"]) == 0
    assert int(b["acc_total"]) == 2

    r = rows["src/risky.js"]
    assert r["crap_max_method"] == "risky"
    assert float(r["crap_max"]) == pytest.approx(42.0)
    assert int(r["crappy_methods"]) == 1
    assert int(r["cov_covered"]) == 0
    assert int(r["cov_total"]) == 2
    # No acceptance row → 0 of 0 in TSV (join treats as unmeasured).
    assert int(r["acc_covered"]) == 0
    assert int(r["acc_total"]) == 0

    v = rows["src/Widget.vue"]
    assert v["crap_max_method"] == "score"
    assert float(v["crap_max"]) == pytest.approx(2.5)  # CC=2, cov=0.5
    assert int(v["cov_covered"]) == 1
    assert int(v["cov_total"]) == 2


def test_no_report_clears_stale_tsv(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "crap-per-file.tsv"
    stale.write_text("file\tcov_covered\n", encoding="utf-8")
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(empty_repo)
    env["HEATMAP_OUT"] = str(out)
    env.pop("CODECITY_COVERAGE", None)
    env.pop("CODECITY_COVERAGE_ACCEPTANCE", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not stale.exists()
    assert "no coverage-final.json" in proc.stderr


def test_default_glob_finds_fixture_coverage(tmp_path):
    """When CODECITY_COVERAGE is unset, **/coverage/coverage-final.json is used."""
    out = tmp_path / "out"
    out.mkdir()
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    env.pop("CODECITY_COVERAGE", None)
    env.pop("CODECITY_COVERAGE_ACCEPTANCE", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    rows = _rows(out / "crap-per-file.tsv")
    assert "src/risky.js" in rows
    assert float(rows["src/risky.js"]["crap_max"]) == pytest.approx(42.0)
    assert "src/Widget.vue" in rows


def test_no_scored_methods_deletes_tsv_not_header_only(tmp_path):
    """Report matches a building but nothing is scoreable → delete, no header-only file."""
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "crap-per-file.tsv"
    stale.write_text("# stale\nfile\tcov_covered\n", encoding="utf-8")
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    env["CODECITY_COVERAGE"] = str(
        FIXTURE / "coverage" / "coverage-empty-methods.json"
    )
    env.pop("CODECITY_COVERAGE_ACCEPTANCE", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not stale.exists(), proc.stderr
    assert "no scored methods" in proc.stderr


def test_path_glob_match_and_include_exclude(monkeypatch):
    assert _path_glob_match("src/lib/foo.ts", "src/lib/**")
    assert _path_glob_match("src/lib/foo.ts", "src/lib/*")
    assert not _path_glob_match("src/components/X.tsx", "src/lib/**")
    monkeypatch.setenv("CODECITY_COVERAGE_INCLUDE", "src/lib/**")
    monkeypatch.delenv("CODECITY_COVERAGE_EXCLUDE", raising=False)
    assert coverage_path_allowed("src/lib/a.ts")
    assert not coverage_path_allowed("src/components/a.tsx")
    monkeypatch.setenv("CODECITY_COVERAGE_EXCLUDE", "src/lib/secret.ts")
    assert not coverage_path_allowed("src/lib/secret.ts")
    assert coverage_path_allowed("src/lib/a.ts")


def test_source_map_remap_emitted_js_to_building(tmp_path):
    """Emitted build/out.js + inputSourceMap → CRAP on src/straight.js."""
    out = tmp_path / "out"
    out.mkdir()
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    env["CODECITY_COVERAGE"] = str(
        FIXTURE / "coverage" / "coverage-emitted-with-map.json"
    )
    env.pop("CODECITY_COVERAGE_ACCEPTANCE", None)
    env.pop("CODECITY_COVERAGE_INCLUDE", None)
    env.pop("CODECITY_COVERAGE_EXCLUDE", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "remapped" in proc.stderr
    rows = _rows(out / "crap-per-file.tsv")
    assert "src/straight.js" in rows
    assert "build/out.js" not in rows
    assert float(rows["src/straight.js"]["crap_max"]) == pytest.approx(1.0)


def test_include_glob_filters_buildings(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    env["CODECITY_COVERAGE"] = str(FIXTURE / "coverage" / "coverage-final.json")
    env["CODECITY_COVERAGE_INCLUDE"] = "src/straight.js"
    env.pop("CODECITY_COVERAGE_ACCEPTANCE", None)
    env.pop("CODECITY_COVERAGE_EXCLUDE", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "compute_crap.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    rows = _rows(out / "crap-per-file.tsv")
    assert set(rows) == {"src/straight.js"}
