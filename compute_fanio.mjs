#!/usr/bin/env node
/**
 * Compute internal fan-in / fan-out and coupling edges for a JS/TS city (v3).
 *
 * Env (same as the Python steps):
 *   HEATMAP_REPO  — git checkout to analyse
 *   HEATMAP_OUT   — output directory (default: REPO/.codecity)
 *   HEATMAP_PRUNE — optional comma-separated path segments to prune
 *   HEATMAP_ROAD_EDGE_CAP — max edges kept per direction per file in
 *                           coupling-edges.tsv (default 80, matches renderer
 *                           ROAD_CAP). fan_in/fan_out stay full counts.
 *
 * Writes:
 *   fanio-per-file.tsv      file \t fan_in \t fan_out
 *   coupling-edges.tsv      source \t target \t weight \t line
 *
 * ADR 0010: dependency-cruiser; internal only; no import type; resolve-through
 * barrels; static import()/string require; first non-import line; mention weight.
 * On failure: empty coupling + stderr summary (exit 0).
 */
import { cruise } from "dependency-cruiser";
import extractTSConfig from "dependency-cruiser/config-utl/extract-ts-config";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

/** Match render_codecity.py ROAD_CAP — edges beyond this are not drawn anyway. */
export const ROAD_EDGE_CAP_DEFAULT = 80;

/**
 * Keep at most `cap` outbound edges per source and `cap` inbound per target
 * (highest weight first). fan_in/fan_out must be computed from the full graph
 * before calling this — trimmed edges are for drawing only.
 *
 * @param {Array<{source:string,target:string,weight:number,line:number}>} edges
 * @param {number} cap
 * @returns {{kept: typeof edges, dropped: number}}
 */
export function trimCouplingEdges(edges, cap = ROAD_EDGE_CAP_DEFAULT) {
  if (!Number.isFinite(cap) || cap <= 0) {
    return { kept: edges.slice(), dropped: 0 };
  }
  const bySource = new Map();
  for (const e of edges) {
    if (!bySource.has(e.source)) bySource.set(e.source, []);
    bySource.get(e.source).push(e);
  }
  const afterOut = [];
  for (const list of bySource.values()) {
    list.sort(
      (a, b) =>
        b.weight - a.weight ||
        (a.target < b.target ? -1 : a.target > b.target ? 1 : 0),
    );
    afterOut.push(...list.slice(0, cap));
  }
  const byTarget = new Map();
  for (const e of afterOut) {
    if (!byTarget.has(e.target)) byTarget.set(e.target, []);
    byTarget.get(e.target).push(e);
  }
  const kept = [];
  for (const list of byTarget.values()) {
    list.sort(
      (a, b) =>
        b.weight - a.weight ||
        (a.source < b.source ? -1 : a.source > b.source ? 1 : 0),
    );
    kept.push(...list.slice(0, cap));
  }
  kept.sort(
    (a, b) =>
      (a.source < b.source ? -1 : a.source > b.source ? 1 : 0) ||
      (a.target < b.target ? -1 : a.target > b.target ? 1 : 0),
  );
  return { kept, dropped: edges.length - kept.length };
}

function roadEdgeCapFromEnv() {
  const raw = process.env.HEATMAP_ROAD_EDGE_CAP;
  if (raw === undefined || raw === "") return ROAD_EDGE_CAP_DEFAULT;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : ROAD_EDGE_CAP_DEFAULT;
}


const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Loaded from citylib_include.json (written by citylib / generate.py). */
function loadIncludeRules() {
  const p = path.join(__dirname, "citylib_include.json");
  const raw = JSON.parse(fs.readFileSync(p, "utf8"));
  return {
    // Coupling omits .svelte (ADR 0010); JSON carries coupling_source_suffixes.
    SOURCE_SUFFIXES: raw.coupling_source_suffixes || raw.source_suffixes.filter((s) => s !== ".svelte"),
    PRUNE_DIRS: new Set(raw.prune_dirs),
    TEST_DIR_SEGMENTS: new Set(raw.test_dir_segments),
    TEST_INFIXES: new Set(raw.test_infixes),
  };
}

const {
  SOURCE_SUFFIXES,
  PRUNE_DIRS,
  TEST_DIR_SEGMENTS,
  TEST_INFIXES,
} = loadIncludeRules();

const INDEX_RE = /^index\.(tsx?|jsx?|mjs|cjs|mts|cts|vue)$/i;

const NPM_TYPES = new Set([
  "npm",
  "npm-dev",
  "npm-optional",
  "npm-peer",
  "npm-bundled",
  "npm-no-pkg",
]);

function posix(p) {
  return p.replace(/\\/g, "/").replace(/^\.\//, "");
}

function repoRel(absOrRel, repoRoot) {
  const abs = path.isAbsolute(absOrRel)
    ? absOrRel
    : path.resolve(repoRoot, absOrRel);
  return posix(path.relative(repoRoot, abs));
}

function stripSuffix(name) {
  const lower = name.toLowerCase();
  for (const suf of SOURCE_SUFFIXES) {
    if (lower.endsWith(suf)) return name.slice(0, -suf.length);
  }
  return name;
}

function isColocatedTest(name) {
  const parts = name.split(".");
  if (parts.length < 3) return false;
  return TEST_INFIXES.has(parts[parts.length - 2].toLowerCase());
}

function extensionOk(name) {
  const lower = name.toLowerCase();
  if (
    lower.endsWith(".d.ts") ||
    lower.endsWith(".d.mts") ||
    lower.endsWith(".d.cts")
  ) {
    return false;
  }
  if (lower.endsWith(".min.js") || lower.endsWith(".min.mjs")) return false;
  return SOURCE_SUFFIXES.some((s) => lower.endsWith(s));
}

function countsTowardDiagram(rel) {
  rel = posix(rel);
  if (!rel || rel === ".") return false;
  const parts = rel.split("/");
  const name = parts[parts.length - 1];
  if (!name || !extensionOk(name) || isColocatedTest(name)) return false;
  for (const seg of parts.slice(0, -1)) {
    if (
      PRUNE_DIRS.has(seg) ||
      TEST_DIR_SEGMENTS.has(seg) ||
      (seg.startsWith(".") && seg !== ".")
    ) {
      return false;
    }
  }
  return true;
}

function isInternalDep(dep) {
  if (!dep || dep.coreModule || dep.couldNotResolve) return false;
  const types = dep.dependencyTypes || [];
  if (types.some((t) => NPM_TYPES.has(t) || t === "core")) return false;
  if (dep.typeOnly) return false;
  if (types.includes("type-only")) return false;
  if (dep.dynamic && /\$\{/.test(dep.module || "")) return false;
  const resolved = posix(dep.resolved || "");
  if (!resolved || resolved.includes("node_modules/")) return false;
  return true;
}

function writeEmpty(outDir, reason) {
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "fanio-per-file.tsv"), "file\tfan_in\tfan_out\n");
  fs.writeFileSync(
    path.join(outDir, "coupling-edges.tsv"),
    "source\ttarget\tweight\tline\n",
  );
  console.error(`WARN: coupling empty — ${reason}`);
}

function stripCommentsAndStrings(src) {
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const ch = src[i];
    const nxt = i + 1 < n ? src[i + 1] : "";
    if (ch === "/" && nxt === "/") {
      const j = src.indexOf("\n", i);
      const end = j < 0 ? n : j;
      out += " ".repeat(end - i);
      i = end;
    } else if (ch === "/" && nxt === "*") {
      const j = src.indexOf("*/", i + 2);
      const end = j < 0 ? n : j + 2;
      for (let k = i; k < end; k++) {
        out += src[k] === "\n" ? "\n" : " ";
      }
      i = end;
    } else if (ch === "`") {
      let j = i + 1;
      while (j < n) {
        if (src[j] === "\\") {
          j += 2;
          continue;
        }
        if (src[j] === "`") {
          j += 1;
          break;
        }
        j += 1;
      }
      for (let k = i; k < j; k++) out += src[k] === "\n" ? "\n" : " ";
      i = j;
    } else if (ch === '"' || ch === "'") {
      let j = i + 1;
      while (j < n && src[j] !== ch) {
        j += src[j] === "\\" ? 2 : 1;
      }
      j = Math.min(j + 1, n);
      for (let k = i; k < j; k++) out += src[k] === "\n" ? "\n" : " ";
      i = j;
    } else {
      out += ch;
      i += 1;
    }
  }
  return out;
}

function isImportLikeLine(line) {
  const t = line.trim();
  if (!t) return false;
  if (/^import\b/.test(t)) return true;
  if (/^export\s+[\s\S]*\bfrom\b/.test(t)) return true;
  if (/^const\s+\w+\s*=\s*require\s*\(/.test(t)) return true;
  if (/^let\s+\w+\s*=\s*require\s*\(/.test(t)) return true;
  if (/^var\s+\w+\s*=\s*require\s*\(/.test(t)) return true;
  if (/^module\.exports\b/.test(t)) return true;
  if (/^exports\./.test(t)) return true;
  if (/\brequire\s*\(\s*['"`]/.test(t) && /^\s*(const|let|var)\b/.test(t)) {
    return true;
  }
  return false;
}

/**
 * Collect local binding names from ESM/CJS imports (ADR 0010 weight/line).
 * @returns {Array<{module:string, names:string[]}>}
 */
export function extractImportBindings(sourceText) {
  const out = [];
  const esm =
    /\bimport\s*(?:type\s+)?(?:([\w$]+)|(\*\s+as\s+[\w$]+)|(\{[^}]*\}))?\s*(?:,\s*(?:([\w$]+)|(\*\s+as\s+[\w$]+)|(\{[^}]*\})))?\s*from\s*['"]([^'"]+)['"]/g;
  const esmSide = /\bimport\s*['"]([^'"]+)['"]/g;
  const req = /\b(?:const|let|var)\s+(?:([\w$]+)|(\{[^}]*\}))\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)/g;

  function namesFromClause(defaultName, nsClause, namedClause) {
    const names = [];
    if (defaultName) names.push(defaultName);
    if (nsClause) {
      const m = /\*\s+as\s+([\w$]+)/.exec(nsClause);
      if (m) names.push(m[1]);
    }
    if (namedClause) {
      for (const part of namedClause.replace(/[{}]/g, "").split(",")) {
        const bit = part.trim();
        if (!bit || bit === "type") continue;
        // Foo as Bar  |  type Foo as Bar  |  Foo
        const as = /\bas\s+([\w$]+)\s*$/.exec(bit);
        if (as) {
          names.push(as[1]);
          continue;
        }
        const id = bit.replace(/^type\s+/, "").trim();
        if (/^[\w$]+$/.test(id)) names.push(id);
      }
    }
    return names;
  }

  let m;
  while ((m = esm.exec(sourceText))) {
    const names = namesFromClause(m[1] || m[4], m[2] || m[5], m[3] || m[6]);
    out.push({ module: m[7], names });
  }
  while ((m = esmSide.exec(sourceText))) {
    out.push({ module: m[1], names: [] });
  }
  while ((m = req.exec(sourceText))) {
    const names = namesFromClause(m[1], null, m[2]);
    out.push({ module: m[3], names });
  }
  return out;
}

function normModuleKey(s) {
  return s
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/\.(tsx?|jsx?|mjs|cjs|mts|cts|vue)$/i, "")
    .replace(/\/index$/i, "");
}

function moduleMatchesTarget(moduleSpec, targetRel) {
  const spec = normModuleKey(moduleSpec);
  const tgt = normModuleKey(targetRel);
  if (!spec || !tgt) return false;
  return (
    tgt === spec ||
    tgt.endsWith("/" + spec) ||
    spec.endsWith("/" + tgt) ||
    tgt.endsWith(spec)
  );
}

/** Binding names in `sourceText` that refer to `targetRel` (plus basename fallback). */
export function bindingNamesForTarget(sourceText, targetRel) {
  const names = new Set();
  const base = stripSuffix(targetRel.split("/").pop() || "");
  if (base) names.add(base);
  for (const imp of extractImportBindings(sourceText)) {
    if (!moduleMatchesTarget(imp.module, targetRel)) continue;
    for (const n of imp.names) names.add(n);
  }
  return [...names];
}

export function mentionStats(sourceText, targetRel, extraNames = []) {
  const names = new Set(bindingNamesForTarget(sourceText, targetRel));
  for (const n of extraNames) if (n) names.add(n);
  if (!names.size) return { weight: 1, line: 0 };
  const stripped = stripCommentsAndStrings(sourceText);
  const lines = stripped.split(/\r?\n/);
  const patterns = [...names].map(
    (n) => new RegExp(`\\b${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g"),
  );
  let weight = 0;
  let first = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (isImportLikeLine(line)) continue;
    let lineHits = 0;
    for (const re of patterns) {
      const matches = line.match(re);
      if (matches) lineHits += matches.length;
    }
    if (!lineHits) continue;
    weight += lineHits;
    if (!first) first = i + 1;
  }
  if (weight === 0) return { weight: 1, line: 0 };
  return { weight, line: first };
}

function findTsConfig(repoRoot) {
  for (const name of ["tsconfig.json", "jsconfig.json"]) {
    const p = path.join(repoRoot, name);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

/**
 * Barrel = index.* OR a module whose local outs are all re-exports (`export` type).
 * @param {string} rel
 * @param {Map<string, Map<string, {isExport:boolean}>>} localOut
 */
function isBarrel(rel, localOut) {
  if (INDEX_RE.test(rel.split("/").pop() || "")) return true;
  const kids = localOut.get(rel);
  if (!kids || kids.size === 0) return false;
  for (const meta of kids.values()) {
    if (!meta.isExport) return false;
  }
  return true;
}

function expandThroughBarrels(target, localOut, visiting = new Set()) {
  if (visiting.has(target)) return [];
  if (!isBarrel(target, localOut)) return [target];
  const kids = localOut.get(target);
  if (!kids || kids.size === 0) return [target];
  visiting.add(target);
  const out = new Set();
  for (const kid of kids.keys()) {
    for (const leaf of expandThroughBarrels(kid, localOut, visiting)) {
      out.add(leaf);
    }
  }
  visiting.delete(target);
  return out.size ? [...out] : [target];
}

async function main() {
  const repoRoot = path.resolve(
    process.env.HEATMAP_REPO || process.cwd(),
  );
  const outDir = path.resolve(
    process.env.HEATMAP_OUT || path.join(repoRoot, ".codecity"),
  );
  const extraPrune = new Set(
    (process.env.HEATMAP_PRUNE || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
  const prune = new Set([...PRUNE_DIRS, ...extraPrune]);

  fs.mkdirSync(outDir, { recursive: true });

  const excludeSegments = [...prune].map(
    (s) => `(^|/)${s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(/|$)`,
  );
  excludeSegments.push("(^|/)node_modules(/|$)");
  for (const t of TEST_DIR_SEGMENTS) {
    excludeSegments.push(`(^|/)${t}(/|$)`);
  }

  const cruiseOptions = {
    doNotFollow: {
      path: "(^|/)node_modules(/|$)",
      dependencyTypes: [...NPM_TYPES],
    },
    exclude: {
      path: excludeSegments.join("|"),
    },
    moduleSystems: ["es6", "cjs"],
    // Drop type-only / erased imports (ADR 0010).
    tsPreCompilationDeps: false,
    combinedDependencies: true,
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["import", "require", "node", "default"],
      extensions: [
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
        ".vue",
        ".json",
      ],
    },
  };

  let transpileOptions;
  const tsConfigPath = findTsConfig(repoRoot);
  if (tsConfigPath) {
    try {
      transpileOptions = { tsConfig: extractTSConfig(tsConfigPath) };
    } catch (err) {
      console.error(
        `WARN: could not load ${tsConfigPath}: ${err.message || err}`,
      );
    }
  }

  let modules;
  const prevCwd = process.cwd();
  try {
    // Cruise from inside the repo so exclude patterns match repo-relative
    // paths only (an absolute Windows path like …/tests/fixtures/… would
    // otherwise be killed by the `tests` prune segment).
    process.chdir(repoRoot);
    const result = await cruise(
      ["."],
      cruiseOptions,
      undefined,
      transpileOptions,
    );
    modules = result.output?.modules || [];
  } catch (err) {
    process.chdir(prevCwd);
    writeEmpty(outDir, `cruise failed: ${err.message || err}`);
    return 0;
  }
  process.chdir(prevCwd);

  // sourceRel -> Map<target, {isExport}> (as-written, before barrel expand)
  /** @type {Map<string, Map<string, {isExport:boolean}>>} */
  const localOut = new Map();

  for (const mod of modules) {
    const src = repoRel(mod.source, repoRoot);
    if (!countsTowardDiagram(src)) continue;
    if ([...src.split("/")].some((seg) => prune.has(seg))) continue;
    for (const dep of mod.dependencies || []) {
      if (!isInternalDep(dep)) continue;
      const dst = repoRel(dep.resolved, repoRoot);
      if (!countsTowardDiagram(dst)) continue;
      if ([...dst.split("/")].some((seg) => prune.has(seg))) continue;
      if (src === dst) continue;
      const types = dep.dependencyTypes || [];
      const isExport = types.includes("export");
      if (!localOut.has(src)) localOut.set(src, new Map());
      const prev = localOut.get(src).get(dst);
      // Prefer keeping a non-export edge if both exist (real use, not only re-export).
      localOut.get(src).set(dst, {
        isExport: prev ? prev.isExport && isExport : isExport,
      });
    }
  }

  // Resolve through barrels for metrics / roads.
  /** @type {Map<string, Map<string, {weight:number, line:number}>>} */
  const fanOut = new Map();
  const sourceCache = new Map();

  function readSource(rel) {
    if (sourceCache.has(rel)) return sourceCache.get(rel);
    const abs = path.join(repoRoot, rel);
    let text = "";
    try {
      text = fs.readFileSync(abs, "utf8");
    } catch {
      text = "";
    }
    sourceCache.set(rel, text);
    return text;
  }

  for (const [src, targets] of localOut) {
    /** @type {Map<string, string[]>} leaf -> extra binding names from barrel import */
    const expanded = new Map();
    const srcText = readSource(src);
    for (const t of targets.keys()) {
      const leaves = expandThroughBarrels(t, localOut).filter(
        (leaf) => leaf !== src && countsTowardDiagram(leaf),
      );
      // Bindings for the as-written import (barrel or direct).
      const fromWritten = bindingNamesForTarget(srcText, t);
      for (const leaf of leaves) {
        const prev = expanded.get(leaf) || [];
        expanded.set(leaf, [...new Set([...prev, ...fromWritten])]);
      }
    }
    if (!expanded.size) continue;
    const edgeMap = new Map();
    for (const [dst, extra] of expanded) {
      edgeMap.set(dst, mentionStats(srcText, dst, extra));
    }
    fanOut.set(src, edgeMap);
  }

  const fanIn = new Map();
  for (const [, edges] of fanOut) {
    for (const dst of edges.keys()) {
      fanIn.set(dst, (fanIn.get(dst) || 0) + 1);
    }
  }

  const allFiles = new Set([...fanOut.keys(), ...fanIn.keys()]);
  // Full distinct counts — never reduced by the road-draw cap below.
  const rows = [...allFiles]
    .filter((f) => countsTowardDiagram(f))
    .map((f) => [f, fanIn.get(f) || 0, fanOut.has(f) ? fanOut.get(f).size : 0])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));

  const fanioPath = path.join(outDir, "fanio-per-file.tsv");
  fs.writeFileSync(
    fanioPath,
    "file\tfan_in\tfan_out\n" +
      rows.map((r) => `${r[0]}\t${r[1]}\t${r[2]}\n`).join(""),
  );

  const fullEdges = [];
  for (const src of fanOut.keys()) {
    const edges = fanOut.get(src);
    for (const dst of edges.keys()) {
      const { weight, line } = edges.get(dst);
      fullEdges.push({ source: src, target: dst, weight, line });
    }
  }
  const cap = roadEdgeCapFromEnv();
  const { kept, dropped } = trimCouplingEdges(fullEdges, cap);

  const edgeLines = ["source\ttarget\tweight\tline\n"];
  for (const e of kept) {
    edgeLines.push(`${e.source}\t${e.target}\t${e.weight}\t${e.line}\n`);
  }
  const edgesPath = path.join(outDir, "coupling-edges.tsv");
  fs.writeFileSync(edgesPath, edgeLines.join(""));

  console.error(`wrote ${rows.length} rows to ${fanioPath}`);
  console.error(
    `wrote ${kept.length} edges to ${edgesPath}` +
      (dropped
        ? ` (trimmed ${dropped} hub edges; cap ${cap}/direction; fan_in/out unchanged)`
        : ` (cap ${cap}/direction)`),
  );

  const byOut = [...rows].sort((a, b) => b[2] - a[2]).slice(0, 5);
  const byIn = [...rows].sort((a, b) => b[1] - a[1]).slice(0, 5);
  console.error("\ntop fan_out:");
  for (const r of byOut) console.error(`  ${String(r[2]).padStart(4)}  ${r[0]}`);
  console.error("\ntop fan_in:");
  for (const r of byIn) console.error(`  ${String(r[1]).padStart(4)}  ${r[0]}`);

  return 0;
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main()
    .then((code) => process.exit(code ?? 0))
    .catch((err) => {
      const repoRoot = path.resolve(process.env.HEATMAP_REPO || process.cwd());
      const outDir = path.resolve(
        process.env.HEATMAP_OUT || path.join(repoRoot, ".codecity"),
      );
      writeEmpty(outDir, `unexpected: ${err.message || err}`);
      console.error(err);
      process.exit(0);
    });
}
