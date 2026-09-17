#!/usr/bin/env python3
"""Build a Code City (and the 2-D codemap) for a JS/TS git checkout.

    python generate.py [REPO] [OUT]

REPO defaults to this process's git toplevel; OUT defaults to REPO/.codecity.
Both are the friendlier spellings of HEATMAP_REPO / HEATMAP_OUT.

v1 walks sources, joins git history, and renders. It does not parse JS for
complexity, coupling or CRAP — those columns stay zero or absent.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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

    print("[1/4] join git history + size into codemap.tsv...", flush=True)
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

    print("[2/4] render interactive HTML...", flush=True)
    _run("render_heatmap.py", env)

    print("[3/4] render Code City HTML...", flush=True)
    _run("render_codecity.py", env, {"HEATMAP_TITLE": env["CODECITY_TITLE"]})

    print("[4/4] render combined side-by-side...", flush=True)
    _run("render_combined.py", env)

    print(f"done -> {out / 'codemap.html'}")
    print(f"city -> {out / 'codecity.html'}")
    print(f"both -> {out / 'combined.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
