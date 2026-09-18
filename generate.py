#!/usr/bin/env python3
"""Build a Code City (and the 2-D codemap) for a JS/TS git checkout.

    python generate.py [REPO] [OUT]

REPO defaults to this process's git toplevel; OUT defaults to REPO/.codecity.
Both are the friendlier spellings of HEATMAP_REPO / HEATMAP_OUT.

Walks sources for Sonar-style cognitive complexity, internal coupling
(dependency-cruiser via Node), joins git history, and renders. CRAP stays
absent until v4.

Install once in this repo: `pip install -r requirements.txt` and
`npm install` (Node on PATH for coupling roads).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from citylib import write_include_rules_json

HERE = Path(__file__).resolve().parent


def _git_toplevel(start: Path) -> Path:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(out)
    except Exception:
        return start


def _run(script: str, env: dict, extra_env: dict | None = None) -> str:
    cmd_env = env.copy()
    if extra_env:
        cmd_env.update(extra_env)
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / script)],
            cwd=str(HERE),
            env=cmd_env,
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        if e.stdout:
            sys.stdout.write(e.stdout)
        if e.stderr:
            sys.stderr.write(e.stderr)
        raise
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.stderr


def _clear_coupling_artifacts(out: Path) -> None:
    """Empty fanio/edges so a skipped or failed cruise cannot leave stale roads."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "fanio-per-file.tsv").write_text(
        "file\tfan_in\tfan_out\n", encoding="utf-8", newline="\n"
    )
    (out / "coupling-edges.tsv").write_text(
        "source\ttarget\tweight\tline\n", encoding="utf-8", newline="\n"
    )


def _run_node(script: str, env: dict, out: Path) -> str:
    """Run a Node step next to generate.py (v3 coupling).

    Prefers `node` on PATH. On Windows also tries `node.exe`. Missing Node or a
    failed cruise clears coupling artifacts (ADR 0010 — no stale roads).
    """
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        print(
            "WARN: node not on PATH — skipping coupling (fan-in/out stay 0)",
            flush=True,
        )
        _clear_coupling_artifacts(out)
        return ""
    try:
        proc = subprocess.run(
            [node, str(HERE / script)],
            cwd=str(HERE),
            env=env,
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        # ADR 0010: empty coupling on failure — do not abort the city.
        if e.stdout:
            sys.stdout.write(e.stdout)
        if e.stderr:
            sys.stderr.write(e.stderr)
        print(
            f"WARN: {script} failed (exit {e.returncode}); continuing with empty coupling",
            flush=True,
        )
        _clear_coupling_artifacts(out)
        return (e.stderr or "") + (e.stdout or "")
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.stderr


def main(argv: list[str]) -> int:
    repo = Path(argv[1]).resolve() if len(argv) > 1 else _git_toplevel(Path.cwd())
    out = Path(argv[2]).resolve() if len(argv) > 2 else repo / ".codecity"
    out.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HEATMAP_REPO"] = str(repo)
    env["HEATMAP_OUT"] = str(out)
    env["HEATMAP_REPO_ABS"] = str(repo)
    env.setdefault("HEATMAP_OPEN_IN", "vscode")
    env.setdefault("HEATMAP_TITLE", f"{repo.name} Codemap")
    env.setdefault("CODECITY_TITLE", f"Code City: {repo.name}")

    print(f"repo:  {repo}", flush=True)
    print(f"out:   {out}", flush=True)

    print("[1/6] cognitive complexity (tree-sitter JS/TS + Vue script)...", flush=True)
    _run("compute_complexity.py", env)

    print("[2/6] coupling (dependency-cruiser fan-in/out + edges)...", flush=True)
    # Keep Node include rules in sync with citylib.py (single source of truth).
    write_include_rules_json(HERE / "citylib_include.json")
    _run_node("compute_fanio.mjs", env, out)

    print("[3/6] join git history + size into codemap.tsv...", flush=True)
    log = _run("build_heatmap.py", env)

    tsv = out / "codemap.tsv"
    files = max(sum(1 for _ in tsv.open(encoding="utf-8")) - 1, 0) if tsv.exists() else 0
    try:
        commits = subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        commits = "?"
    bugfix = "0"
    for line in log.splitlines():
        if "flagged as bug-linked" in line:
            # walked N commits, M flagged as bug-linked
            parts = line.split()
            for i, p in enumerate(parts):
                if p.isdigit() and i + 1 < len(parts) and parts[i + 1] == "flagged":
                    bugfix = p
    env["HEATMAP_SUBTITLE"] = (
        f"{files} source JS/TS files · {commits} commits walked · {bugfix} bug-fix commits."
    )

    print("[4/6] render interactive HTML...", flush=True)
    _run("render_heatmap.py", env)

    print("[5/6] render Code City HTML...", flush=True)
    _run("render_codecity.py", env, {"HEATMAP_TITLE": env["CODECITY_TITLE"]})

    print("[6/6] render combined side-by-side...", flush=True)
    _run("render_combined.py", env)

    print(f"done -> {out / 'codemap.html'}")
    print(f"city -> {out / 'codecity.html'}")
    print(f"both -> {out / 'combined.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
