"""HTML writers must be UTF-8: Windows cp1252 cannot encode ⌘."""
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


def _run_renderer(script: str, out: Path, extra_env: dict | None = None) -> None:
    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(out)
    env["HEATMAP_OUT"] = str(out)
    env["HEATMAP_REPO_ABS"] = str(out)
    env["HEATMAP_OPEN_IN"] = "vscode"
    env["HEATMAP_TITLE"] = "utf8-fixture"
    # UTF-8 mode would hide the bug: locale open() on Windows is cp1252.
    env["PYTHONUTF8"] = "0"
    if extra_env:
        env.update(extra_env)
    subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=str(ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    )


def test_heatmap_html_keeps_command_glyph(tmp_path: Path) -> None:
    (tmp_path / "codemap.tsv").write_text(
        FILE_HEADER + "src/App.vue\t100\t20\t1\t0\t50.00\t0.00\t0.000\t0\t0.00\t0\t0\t1\t0.000\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    _run_renderer("render_heatmap.py", tmp_path)
    html = (tmp_path / "codemap.html").read_text(encoding="utf-8")
    assert "\u2318" in html
    raw = (tmp_path / "codemap.html").read_bytes()
    assert "\u2318".encode("utf-8") in raw


def test_heatmap_html_normalises_vscode_path(tmp_path: Path) -> None:
    (tmp_path / "codemap.tsv").write_text(
        FILE_HEADER + "src/App.vue\t100\t20\t1\t0\t50.00\t0.00\t0.000\t0\t0.00\t0\t0\t1\t0.000\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    _run_renderer("render_heatmap.py", tmp_path, {"HEATMAP_REPO_ABS": r"D:\fake\repo"})
    html = (tmp_path / "codemap.html").read_text(encoding="utf-8")
    assert "vscode://file" in html
    assert 'abs.startsWith("/")' in html


def test_city_html_keeps_command_glyph(tmp_path: Path) -> None:
    (tmp_path / "codemap.tsv").write_text(
        FILE_HEADER + "src/App.vue\t100\t20\t1\t0\t50.00\t0.00\t0.000\t0\t0.00\t0\t0\t1\t0.000\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    _run_renderer("render_codecity.py", tmp_path)
    html = (tmp_path / "codecity.html").read_text(encoding="utf-8")
    assert "\u2318" in html


def test_combined_html_is_utf8(tmp_path: Path) -> None:
    _run_renderer("render_combined.py", tmp_path, {"CODECITY_TITLE": "Code City: café"})
    html = (tmp_path / "combined.html").read_text(encoding="utf-8")
    assert "café" in html


if __name__ == "__main__":
    import tempfile

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                print(f"ok  {fn.__name__}")
            except Exception as e:
                failed += 1
                print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failed else 0)
