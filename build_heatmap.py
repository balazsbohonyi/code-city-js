#!/usr/bin/env python3
"""Join git history and file size into the TSV the city renderer eats.

Complexity comes from `complexity-per-file.tsv` when present (v2 /
`compute_complexity.py`); otherwise it stays 0. Fan-in/out come from
`fanio-per-file.tsv` when present (v3 / `compute_fanio.mjs`); otherwise 0.
CRAP / coverage come from `crap-per-file.tsv` when present (v4 /
`compute_crap.py`); an unmeasured file stays blank, not zero. Co-change
comes out of the same history walk, so it is free and we keep it.

Path separators are normalised to `/` before anything is keyed: git log on
Windows still emits POSIX paths, os.walk does not.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict

from citylib import (
    PRUNE_DIRS,
    counts_toward_diagram,
    discover_module_dirs,
    district_of,
    module_of,
    posix_path,
    posix_rel,
    repo_rel_parts,
)

_here = os.path.dirname(os.path.abspath(__file__))


def _git_root(start):
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
EXTRA_PRUNE = frozenset(d for d in os.environ.get("HEATMAP_PRUNE", "").split(",") if d)
BUG_FILE = os.environ.get("HEATMAP_BUG_FILE", os.path.join(OUT_DIR, "bug_issues.txt"))

# Same default as the Java guide. Conventional Commits (`fix:`) and the plain
# "Fix ..." verb both match; "Fixture" does not, because of the word boundary.
DEFAULT_BUG_SUBJECT_RE = r"^(fix|fixed|fixes|bugfix)\b"
_bug_subj_env = os.environ.get("HEATMAP_BUG_COMMIT_REGEX")
_bug_subj_is_default = _bug_subj_env is None
if _bug_subj_is_default:
    _bug_subj_src = DEFAULT_BUG_SUBJECT_RE
else:
    _bug_subj_src = _bug_subj_env or None
BUG_SUBJECT_RE = re.compile(_bug_subj_src, re.IGNORECASE) if _bug_subj_src else None

OUT_FILE = os.path.join(OUT_DIR, "codemap.tsv")
COMPLEXITY_FILE = os.path.join(OUT_DIR, "complexity-per-file.tsv")
FANIO_FILE = os.path.join(OUT_DIR, "fanio-per-file.tsv")
CRAP_FILE = os.path.join(OUT_DIR, "crap-per-file.tsv")

bug_ids = set()
if os.path.exists(BUG_FILE):
    with open(BUG_FILE) as f:
        bug_ids = {int(line.strip()) for line in f if line.strip()}
print(f"loaded {len(bug_ids)} bug/regression issue numbers", file=sys.stderr)
if BUG_SUBJECT_RE:
    origin = "default heuristic" if _bug_subj_is_default else "HEATMAP_BUG_COMMIT_REGEX override"
    print(f"flagging bug commits via subject regex ({origin}): {_bug_subj_src!r}", file=sys.stderr)
else:
    print("subject-regex heuristic disabled; relying solely on the bug-issue list", file=sys.stderr)

GH_RE = re.compile(r"\bgh-(\d+)\b", re.IGNORECASE)
HASH_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)

SENT = "___COMMIT___"
FSENT = "___FILES___"
fmt = f"{SENT}%n%H%n%ae%n%s%n%b%n{FSENT}"
proc = subprocess.Popen(
    ["git", "-C", REPO_DIR, "log", "--no-merges", "--name-only", f"--pretty=format:{fmt}"],
    stdout=subprocess.PIPE,
    text=True,
    errors="replace",
)
assert proc.stdout

commits_per_file = defaultdict(int)
bug_commits_per_file = defaultdict(int)
committers_per_file = defaultdict(set)
total_commits = 0
total_bug_commits = 0

commits_per_package = defaultdict(set)
bug_commits_per_package = defaultdict(set)
committers_per_package = defaultdict(set)
commits_per_module = defaultdict(set)
bug_commits_per_module = defaultdict(set)
committers_per_module = defaultdict(set)

PRUNE = PRUNE_DIRS | set(EXTRA_PRUNE)
MODULE_EXTRA = EXTRA_PRUNE

# Prime the module cache once so every _module call is a prefix check.
_MODULE_DIRS = discover_module_dirs(REPO_DIR, MODULE_EXTRA)
print(f"discovered {len([m for m in _MODULE_DIRS if m]) + (1 if '' in _MODULE_DIRS else 0)} package.json module dir(s)", file=sys.stderr)


def _district(path):
    return district_of(path)


def _module(path):
    return module_of(path, REPO_DIR, MODULE_EXTRA)


def _counts(fp):
    return counts_toward_diagram(fp)


COCHANGE_MAX_FILES = int(os.environ.get("HEATMAP_COCHANGE_MAX_FILES", "30"))
COCHANGE_MIN_SHARED = int(os.environ.get("HEATMAP_COCHANGE_MIN_SHARED", "2"))
COCHANGE_TOP = int(os.environ.get("HEATMAP_COCHANGE_TOP", "20"))


def _scope_distance(a, b, sep):
    if a == b:
        return 0
    x = a.split(sep) if a else []
    y = b.split(sep) if b else []
    i = 0
    while i < len(x) and i < len(y) and x[i] == y[i]:
        i += 1
    return (len(x) - i) + (len(y) - i)


def _escape_weight(d):
    return d / (d + 2.0) if d > 0 else 0.0


_COCHANGE_LEVELS = (
    ("classes", lambda p: p, lambda p: _district(p), "."),
    ("packages", lambda p: _district(p), lambda p: _district(p), "."),
    ("modules", lambda p: _module(p), lambda p: _module(p), "/"),
)
cochange_escape = {lv: defaultdict(float) for lv, _u, _s, _sep in _COCHANGE_LEVELS}
cochange_seen = {lv: defaultdict(int) for lv, _u, _s, _sep in _COCHANGE_LEVELS}
cochange_pairs = {lv: defaultdict(int) for lv, _u, _s, _sep in _COCHANGE_LEVELS}


def _record_cochange(touched):
    for level, unit_of, scope_of, sep in _COCHANGE_LEVELS:
        scope_by_unit = {}
        for fp in touched:
            scope_by_unit[unit_of(fp)] = scope_of(fp)
        units = list(scope_by_unit)
        for u in units:
            worst = 0.0
            for v in units:
                if v == u:
                    continue
                worst = max(worst, _escape_weight(
                    _scope_distance(scope_by_unit[u], scope_by_unit[v], sep)))
            cochange_escape[level][u] += worst
            cochange_seen[level][u] += 1
        for i, u in enumerate(units):
            for v in units[i + 1:]:
                if scope_by_unit[u] == scope_by_unit[v]:
                    continue
                cochange_pairs[level][(u, v) if u < v else (v, u)] += 1


def _cochange_out(level, unit):
    seen = cochange_seen[level].get(unit, 0)
    return (cochange_escape[level][unit] / seen) if seen else 0.0


def _crap_cols(entry, lines):
    """CRAP/coverage cells for one row; blank when the unit was never measured."""
    if not entry:
        return ["", "", "", "", "", "", ""]
    kloc = lines / 1000.0 if lines else 0
    coverage = (
        f"{100.0 * entry['cov_covered'] / entry['cov_total']:.1f}"
        if entry["cov_total"]
        else ""
    )
    acceptance = (
        f"{100.0 * entry['acc_covered'] / entry['acc_total']:.1f}"
        if entry.get("acc_total")
        else ""
    )
    return [
        coverage,
        acceptance,
        f"{entry['crap_max']:.1f}",
        entry["crap_max_method"],
        f"{entry['crap_load']:.1f}",
        f"{(entry['crap_load'] / kloc) if kloc else 0:.1f}",
        str(entry["crappy_methods"]),
    ]


def _crap_sum(entries):
    """Roll file CRAP rows up for a package or module.

    Coverage re-divides summed statement counters (not an average of %);
    crap_max is the worst child; crap_load / crappy_methods sum.
    """
    measured = [e for e in entries if e]
    if not measured:
        return None
    worst = max(measured, key=lambda e: e["crap_max"])
    return {
        "cov_covered": sum(e["cov_covered"] for e in measured),
        "cov_total": sum(e["cov_total"] for e in measured),
        "acc_covered": sum(e.get("acc_covered", 0) for e in measured),
        "acc_total": sum(e.get("acc_total", 0) for e in measured),
        "crap_max": worst["crap_max"],
        "crap_max_method": worst["crap_max_method"],
        "crap_load": sum(e["crap_load"] for e in measured),
        "crappy_methods": sum(e["crappy_methods"] for e in measured),
    }


sha = None
author = None
msg_lines = []
file_lines = []


def flush_commit():
    global total_commits, total_bug_commits
    if sha is None:
        return
    msg = "\n".join(msg_lines)
    subject = msg_lines[0] if msg_lines else ""
    refs = set(int(m) for m in GH_RE.findall(msg))
    for m in HASH_RE.findall(msg):
        refs.add(int(m))
    is_bug = bool(refs & bug_ids)
    if BUG_SUBJECT_RE and BUG_SUBJECT_RE.search(subject):
        is_bug = True
    total_commits += 1
    if is_bug:
        total_bug_commits += 1
    for fp in file_lines:
        if not fp:
            continue
        fp = posix_path(fp)
        commits_per_file[fp] += 1
        if author:
            committers_per_file[fp].add(author)
        if is_bug:
            bug_commits_per_file[fp] += 1
    counted = [fp for fp in (posix_path(x) for x in file_lines) if fp and _counts(fp)]
    for pkg in {_district(fp) for fp in counted}:
        commits_per_package[pkg].add(sha)
        if author:
            committers_per_package[pkg].add(author)
        if is_bug:
            bug_commits_per_package[pkg].add(sha)
    if counted and len(counted) <= COCHANGE_MAX_FILES:
        _record_cochange(counted)
    for mod in {_module(fp) for fp in counted}:
        commits_per_module[mod].add(sha)
        if author:
            committers_per_module[mod].add(author)
        if is_bug:
            bug_commits_per_module[mod].add(sha)


state = "expect_sent"
for raw in proc.stdout:
    line = raw.rstrip("\n")
    if line == SENT:
        flush_commit()
        sha = None
        author = None
        msg_lines = []
        file_lines = []
        state = "expect_sha"
        continue
    if state == "expect_sha":
        sha = line
        state = "expect_author"
        continue
    if state == "expect_author":
        author = line
        state = "in_msg"
        continue
    if state == "in_msg":
        if line == FSENT:
            state = "in_files"
            continue
        msg_lines.append(line)
        continue
    if state == "in_files":
        if line:
            file_lines.append(line)
        continue
flush_commit()
proc.wait()

print(f"walked {total_commits} commits, {total_bug_commits} flagged as bug-linked", file=sys.stderr)
print(f"touched {len(commits_per_file)} distinct file paths (across all history)", file=sys.stderr)

source_files = []
for root, dirs, files in os.walk(REPO_DIR):
    parts = repo_rel_parts(root, REPO_DIR)
    if any(p == ".git" for p in parts) or any(p in PRUNE for p in parts):
        dirs[:] = []
        continue
    dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".")]
    for fn in files:
        ap = os.path.join(root, fn)
        rel = posix_rel(ap, REPO_DIR)
        if counts_toward_diagram(rel):
            source_files.append(ap)

print(f"found {len(source_files)} current non-test JS/TS source files", file=sys.stderr)

complexity = {}
if os.path.exists(COMPLEXITY_FILE):
    with open(COMPLEXITY_FILE, encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                try:
                    complexity[posix_path(parts[0])] = int(parts[1])
                except ValueError:
                    continue
    print(f"loaded complexity for {len(complexity)} files", file=sys.stderr)
else:
    print(f"WARN: {COMPLEXITY_FILE} not found, complexity will be 0", file=sys.stderr)

fan_in_map, fan_out_map = {}, {}
if os.path.exists(FANIO_FILE):
    with open(FANIO_FILE, encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                key = posix_path(parts[0])
                try:
                    fan_in_map[key] = int(parts[1])
                    fan_out_map[key] = int(parts[2])
                except ValueError:
                    continue
    print(f"loaded fan-in/out for {len(fan_in_map)} files", file=sys.stderr)
else:
    print(f"WARN: {FANIO_FILE} not found, fan-in/out will be 0", file=sys.stderr)

# CRAP + coverage (compute_crap.py). Missing entry stays blank — not zero —
# so unmeasured files stay grey on the page (ADR 0011 / ADR 0005).
crap_map = {}
if os.path.exists(CRAP_FILE):
    with open(CRAP_FILE, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or line.startswith("file\t"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 8:
                crap_map[posix_path(parts[0])] = {
                    "cov_covered": int(parts[1]),
                    "cov_total": int(parts[2]),
                    "crap_max": float(parts[3]),
                    "crap_max_method": parts[4],
                    "crap_load": float(parts[5]),
                    "crappy_methods": int(parts[6]),
                    "acc_covered": int(parts[8]) if len(parts) >= 10 else 0,
                    "acc_total": int(parts[9]) if len(parts) >= 10 else 0,
                }
    print(f"loaded CRAP/coverage for {len(crap_map)} files", file=sys.stderr)
else:
    print(
        f"no {CRAP_FILE}: CRAP and coverage will be absent from this city",
        file=sys.stderr,
    )

FILE_HEADER = (
    "path\tbytes\tlines\tcommits\tbug_commits\tcommits_per_kloc\tbugs_per_kloc\t"
    "bugs_per_commit\tcognitive_complexity\tcomplexity_per_kloc\tfan_in\tfan_out\t"
    "committers\tcochange_out\tcoverage\tcoverage_acceptance\tcrap_max\t"
    "crap_max_method\tcrap_load\tcrap_per_kloc\tcrappy_methods\n"
)

rows = []
for ap in source_files:
    rel = posix_rel(ap, REPO_DIR)
    try:
        sz = os.path.getsize(ap)
        with open(ap, "rb") as f:
            lines = sum(1 for _ in f)
    except OSError:
        continue
    commits = commits_per_file.get(rel, 0)
    bug_commits = bug_commits_per_file.get(rel, 0)
    committers = len(committers_per_file.get(rel, ()))
    cog = complexity.get(rel, 0)
    fi = fan_in_map.get(rel, 0)
    fo = fan_out_map.get(rel, 0)
    kloc = lines / 1000.0 if lines else 0
    commits_per_kloc = (commits / kloc) if kloc else 0
    bugs_per_kloc = (bug_commits / kloc) if kloc else 0
    bugs_per_commit = (bug_commits / commits) if commits else 0
    cog_per_kloc = (cog / kloc) if kloc else 0.0
    rows.append((
        rel, sz, lines, commits, bug_commits, commits_per_kloc, bugs_per_kloc,
        bugs_per_commit, cog, cog_per_kloc, fi, fo, committers,
        _cochange_out("classes", rel), *_crap_cols(crap_map.get(rel), lines),
    ))

rows.sort(key=lambda r: (r[6], r[4], r[3]), reverse=True)

with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
    f.write(FILE_HEADER)
    for r in rows:
        f.write(
            f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}\t{r[5]:.2f}\t{r[6]:.2f}\t"
            f"{r[7]:.3f}\t{r[8]}\t{r[9]:.2f}\t{r[10]}\t{r[11]}\t{r[12]}\t"
            f"{r[13]:.3f}\t{r[14]}\t{r[15]}\t{r[16]}\t{r[17]}\t{r[18]}\t{r[19]}\t{r[20]}\n"
        )

print(f"wrote {len(rows)} rows to {OUT_FILE}", file=sys.stderr)

OUT_FILE_PKG = os.path.join(OUT_DIR, "codemap-packages.tsv")
pkg_agg = {}
pkg_crap = defaultdict(list)
for r in rows:
    pkg = _district(r[0])
    a = pkg_agg.setdefault(pkg, [0, 0, 0, 0, 0, 0])
    a[0] += 1
    a[1] += r[1]
    a[2] += r[2]
    a[3] += r[8]
    a[4] += r[10]
    a[5] += r[11]
    pkg_crap[pkg].append(crap_map.get(r[0]))

PKG_HEADER = (
    "package\tfiles\tbytes\tlines\tcommits\tbug_commits\tcommits_per_kloc\t"
    "bugs_per_kloc\tbugs_per_commit\tcognitive_complexity\tcomplexity_per_kloc\t"
    "fan_in\tfan_out\tcommitters\tcochange_out\tcoverage\tcoverage_acceptance\t"
    "crap_max\tcrap_max_method\tcrap_load\tcrap_per_kloc\tcrappy_methods\n"
)

pkg_rows = []
for pkg, (files, sz, lines, cog, fi, fo) in pkg_agg.items():
    commits = len(commits_per_package.get(pkg, ()))
    bug_commits = len(bug_commits_per_package.get(pkg, ()))
    committers = len(committers_per_package.get(pkg, ()))
    kloc = lines / 1000.0 if lines else 0
    commits_per_kloc = (commits / kloc) if kloc else 0
    bugs_per_kloc = (bug_commits / kloc) if kloc else 0
    bugs_per_commit = (bug_commits / commits) if commits else 0
    cog_per_kloc = (cog / kloc) if kloc else 0
    pkg_rows.append((
        pkg, files, sz, lines, commits, bug_commits, commits_per_kloc,
        bugs_per_kloc, bugs_per_commit, cog, cog_per_kloc, fi, fo, committers,
        _cochange_out("packages", pkg), *_crap_cols(_crap_sum(pkg_crap[pkg]), lines),
    ))

pkg_rows.sort(key=lambda r: (r[6], r[5], r[4]), reverse=True)

with open(OUT_FILE_PKG, "w", encoding="utf-8", newline="\n") as f:
    f.write(PKG_HEADER)
    for r in pkg_rows:
        f.write(
            f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}\t{r[5]}\t{r[6]:.2f}\t"
            f"{r[7]:.2f}\t{r[8]:.3f}\t{r[9]}\t{r[10]:.2f}\t{r[11]}\t{r[12]}\t"
            f"{r[13]}\t{r[14]:.3f}\t{r[15]}\t{r[16]}\t{r[17]}\t{r[18]}\t{r[19]}\t"
            f"{r[20]}\t{r[21]}\n"
        )

print(f"wrote {len(pkg_rows)} package rows to {OUT_FILE_PKG}", file=sys.stderr)

OUT_FILE_MOD = os.path.join(OUT_DIR, "codemap-modules.tsv")
mod_agg = {}
mod_crap = defaultdict(list)
for r in rows:
    mod = _module(r[0])
    a = mod_agg.setdefault(mod, [0, 0, 0, 0, 0, 0])
    a[0] += 1
    a[1] += r[1]
    a[2] += r[2]
    a[3] += r[8]
    a[4] += r[10]
    a[5] += r[11]
    mod_crap[mod].append(crap_map.get(r[0]))

MOD_HEADER = (
    "module\tfiles\tbytes\tlines\tcommits\tbug_commits\tcommits_per_kloc\t"
    "bugs_per_kloc\tbugs_per_commit\tcognitive_complexity\tcomplexity_per_kloc\t"
    "fan_in\tfan_out\tcommitters\tcochange_out\tcoverage\tcoverage_acceptance\t"
    "crap_max\tcrap_max_method\tcrap_load\tcrap_per_kloc\tcrappy_methods\n"
)

mod_rows = []
for mod, (files, sz, lines, cog, fi, fo) in mod_agg.items():
    commits = len(commits_per_module.get(mod, ()))
    bug_commits = len(bug_commits_per_module.get(mod, ()))
    committers = len(committers_per_module.get(mod, ()))
    kloc = lines / 1000.0 if lines else 0
    commits_per_kloc = (commits / kloc) if kloc else 0
    bugs_per_kloc = (bug_commits / kloc) if kloc else 0
    bugs_per_commit = (bug_commits / commits) if commits else 0
    cog_per_kloc = (cog / kloc) if kloc else 0
    mod_rows.append((
        mod, files, sz, lines, commits, bug_commits, commits_per_kloc,
        bugs_per_kloc, bugs_per_commit, cog, cog_per_kloc, fi, fo, committers,
        _cochange_out("modules", mod), *_crap_cols(_crap_sum(mod_crap[mod]), lines),
    ))

mod_rows.sort(key=lambda r: (r[3], r[4]), reverse=True)

with open(OUT_FILE_MOD, "w", encoding="utf-8", newline="\n") as f:
    f.write(MOD_HEADER)
    for r in mod_rows:
        f.write(
            f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}\t{r[5]}\t{r[6]:.2f}\t"
            f"{r[7]:.2f}\t{r[8]:.3f}\t{r[9]}\t{r[10]:.2f}\t{r[11]}\t{r[12]}\t"
            f"{r[13]}\t{r[14]:.3f}\t{r[15]}\t{r[16]}\t{r[17]}\t{r[18]}\t{r[19]}\t"
            f"{r[20]}\t{r[21]}\n"
        )

print(f"wrote {len(mod_rows)} module rows to {OUT_FILE_MOD}", file=sys.stderr)

OUT_FILE_COCH = os.path.join(OUT_DIR, "cochange-edges.tsv")
_live = {
    "classes": {r[0] for r in rows},
    "packages": {r[0] for r in pkg_rows},
    "modules": {r[0] for r in mod_rows},
}


def _emit_key(level, unit):
    return (unit or ".") if level == "modules" else unit


_coch_written = 0
with open(OUT_FILE_COCH, "w", encoding="utf-8", newline="\n") as f:
    f.write("level\tunit\tpeer\tshared\tseverity\n")
    for level, _unit_of, _scope_of, sep in _COCHANGE_LEVELS:
        scope_of_unit = (lambda u: _district(u)) if level == "classes" else (lambda u: u)
        adjacency = defaultdict(list)
        for (u, v), shared in cochange_pairs[level].items():
            if shared < COCHANGE_MIN_SHARED:
                continue
            if u not in _live[level] or v not in _live[level]:
                continue
            severity = _escape_weight(_scope_distance(scope_of_unit(u), scope_of_unit(v), sep))
            if severity <= 0:
                continue
            adjacency[u].append((v, shared, severity))
            adjacency[v].append((u, shared, severity))
        for u in sorted(adjacency):
            peers = sorted(adjacency[u], key=lambda t: (-(t[1] * t[2]), t[0]))
            for v, shared, severity in peers[:COCHANGE_TOP]:
                f.write(
                    f"{level}\t{_emit_key(level, u)}\t{_emit_key(level, v)}\t"
                    f"{shared}\t{severity:.4f}\n"
                )
                _coch_written += 1

print(f"wrote {_coch_written} co-change edges to {OUT_FILE_COCH}", file=sys.stderr)
