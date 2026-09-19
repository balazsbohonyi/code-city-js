"""Ctrl/⌘ editor jumps must survive Windows OrbitControls + vscode:// paths.

The v4 CRAP copy pass once dropped the road-jump rotate lock; this asserts the
generated city HTML still contains the lock, the building-dblclick arm, the
Playwright hook, and the Windows path normaliser.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILE_HEADER = (
    "path\tbytes\tlines\tcommits\tbug_commits\tcommits_per_kloc\tbugs_per_kloc\t"
    "bugs_per_commit\tcognitive_complexity\tcomplexity_per_kloc\tfan_in\tfan_out\t"
    "committers\tcochange_out\tcoverage\tcoverage_acceptance\tcrap_max\t"
    "crap_max_method\tcrap_load\tcrap_per_kloc\tcrappy_methods\n"
)


def _render_city(out: Path, repo_abs: str) -> str:
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(out)
    env["HEATMAP_OUT"] = str(out)
    env["HEATMAP_REPO_ABS"] = repo_abs
    env["HEATMAP_OPEN_IN"] = "vscode"
    env["HEATMAP_TITLE"] = "editor-jump-fixture"
    env["PYTHONUTF8"] = "0"
    (out / "codemap.tsv").write_text(
        FILE_HEADER
        + "src/App.vue\t100\t20\t1\t0\t50.00\t0.00\t0.000\t0\t0.00\t0\t0\t1\t0.000\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(ROOT / "render_codecity.py")],
        cwd=str(ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return (out / "codecity.html").read_text(encoding="utf-8")


def test_city_html_locks_rotate_on_ctrl_building_or_road(tmp_path: Path) -> None:
    html = _render_city(tmp_path, r"D:\fake\repo")
    assert "sourceJumpLocksRotate" in html
    assert "armedBuildingPath" in html
    assert "armedRoadJump" in html
    assert "controls.enableRotate = false" in html
    assert "codecity-open-editor" in html
    assert "__codecityPreventEditorNav" in html
    # Windows: vscode://file/D:/... not vscode://fileD:\...
    assert 'abs.startsWith("/")' in html
    assert "vscode://file" in html


def test_city_html_keeps_lane_road_owners(tmp_path: Path) -> None:
    html = _render_city(tmp_path, r"D:\fake\repo")
    assert "lane.userData.roadOwners" in html
