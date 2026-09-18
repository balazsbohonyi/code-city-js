"""v3 coupling: dependency-cruiser fanio + barrel / type-only / require rules."""
from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
FIXTURE = HERE / "tests" / "fixtures" / "coupling"


def _node() -> str | None:
    return shutil.which("node") or shutil.which("node.exe")


@pytest.fixture(scope="module")
def fanio_out(tmp_path_factory):
    node = _node()
    if not node:
        pytest.skip("node not on PATH")
    if not (HERE / "node_modules" / "dependency-cruiser").exists():
        pytest.skip("dependency-cruiser not installed (npm install)")

    out = tmp_path_factory.mktemp("fanio")
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(FIXTURE)
    env["HEATMAP_OUT"] = str(out)
    proc = subprocess.run(
        [node, str(HERE / "compute_fanio.mjs")],
        cwd=str(HERE),
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return out


def _read_tsv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines, path
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append(dict(zip(headers, parts)))
    return rows


def test_fixture_resolves_through_barrel(fanio_out: Path):
    edges = _read_tsv(fanio_out / "coupling-edges.tsv")
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("src/app.ts", "src/components/Button.js") in pairs
    assert ("src/app.ts", "src/components/index.js") not in pairs
    # Non-index export-only module also resolves through (gap 4).
    assert ("src/via-barrel.ts", "src/components/Button.js") in pairs
    assert ("src/via-barrel.ts", "src/components/ui.js") not in pairs


def test_fixture_drops_import_type(fanio_out: Path):
    edges = _read_tsv(fanio_out / "coupling-edges.tsv")
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("src/app.ts", "src/types.ts") not in pairs


def test_fixture_counts_string_require(fanio_out: Path):
    edges = _read_tsv(fanio_out / "coupling-edges.tsv")
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("src/cjs-user.js", "src/helper.js") in pairs


def test_fixture_first_use_line_and_weight(fanio_out: Path):
    edges = _read_tsv(fanio_out / "coupling-edges.tsv")
    app_btn = next(
        e
        for e in edges
        if e["source"] == "src/app.ts" and e["target"] == "src/components/Button.js"
    )
    assert int(app_btn["weight"]) >= 1
    # return Button(); — not the import line
    assert int(app_btn["line"]) > 1
    # Alias import { Button as Btn } — body uses Btn (ADR 0010 weight/line).
    via = next(
        e
        for e in edges
        if e["source"] == "src/via-barrel.ts"
        and e["target"] == "src/components/Button.js"
    )
    assert int(via["weight"]) >= 1
    assert int(via["line"]) > 1


def test_fixture_fanio_aggregates(fanio_out: Path):
    rows = {r["file"]: r for r in _read_tsv(fanio_out / "fanio-per-file.tsv")}
    assert int(rows["src/app.ts"]["fan_out"]) == 1
    assert int(rows["src/components/Button.js"]["fan_in"]) >= 1


def test_trim_coupling_edges_caps_per_direction():
    node = _node()
    if not node:
        pytest.skip("node not on PATH")
    script = r"""
import { trimCouplingEdges } from './compute_fanio.mjs';
const edges = [];
for (let i = 0; i < 120; i++) {
  edges.push({ source: 'hub.js', target: `t${i}.js`, weight: i + 1, line: 1 });
}
for (let i = 0; i < 120; i++) {
  edges.push({ source: `s${i}.js`, target: 'hub.js', weight: i + 1, line: 1 });
}
const { kept, dropped } = trimCouplingEdges(edges, 80);
const out = kept.filter(e => e.source === 'hub.js').length;
const inn = kept.filter(e => e.target === 'hub.js').length;
console.log(JSON.stringify({ dropped, out, inn, kept: kept.length }));
"""
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=str(HERE),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    import json

    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["out"] <= 80
    assert data["inn"] <= 80
    assert data["dropped"] > 0
    # Heaviest outbound from hub kept
    assert data["kept"] >= 80
