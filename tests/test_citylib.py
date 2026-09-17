"""Inclusion, district and naming rules — no git, no renderer."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citylib import (
    building_name,
    counts_toward_diagram,
    discover_module_dirs,
    district_of,
    filter_suggestions,
    posix_path,
    repo_rel_parts,
)


def test_posix_slash():
    assert posix_path("src\\lib\\foo.ts") == "src/lib/foo.ts"


def test_repo_rel_parts_ignore_ancestor_names():
    # Absolute ancestors must not look like prune segments.
    assert repo_rel_parts(r"D:\develop\playground\vite", r"D:\develop\playground\vite") == ()
    assert repo_rel_parts(
        r"D:\develop\playground\vite\packages\vite\src",
        r"D:\develop\playground\vite",
    ) == ("packages", "vite", "src")


def test_extra_prune_does_not_wipe_checkout_under_same_name():
    """HEATMAP_PRUNE=playground must skip repo/playground/, not …/playground/repo."""
    with tempfile.TemporaryDirectory() as tmp:
        host = Path(tmp) / "playground" / "vite"
        (host / "packages" / "vite" / "src").mkdir(parents=True)
        (host / "playground" / "demo").mkdir(parents=True)
        (host / "docs").mkdir(parents=True)
        (host / "package.json").write_text("{}", encoding="utf-8")
        (host / "packages" / "vite" / "package.json").write_text("{}", encoding="utf-8")
        (host / "playground" / "demo" / "package.json").write_text("{}", encoding="utf-8")
        (host / "docs" / "package.json").write_text("{}", encoding="utf-8")
        (host / "packages" / "vite" / "src" / "index.ts").write_text("export {}", encoding="utf-8")
        (host / "playground" / "demo" / "main.ts").write_text("export {}", encoding="utf-8")

        discover_module_dirs.cache_clear()
        modules = discover_module_dirs(str(host), frozenset({"playground", "docs"}))
        assert "" in modules  # repo root package.json
        assert "packages/vite" in modules
        assert "playground/demo" not in modules
        assert "docs" not in modules
        discover_module_dirs.cache_clear()


def test_includes_source_files():
    assert counts_toward_diagram("src/lib/planner.ts")
    assert counts_toward_diagram("src/components/charts/BarChart.tsx")
    assert counts_toward_diagram("lib/express.js")
    assert counts_toward_diagram("packages/ui/src/Button.vue")


def test_excludes_tests_and_pruned():
    assert not counts_toward_diagram("src/lib/planner.test.ts")
    assert not counts_toward_diagram("src/components/Button.spec.tsx")
    assert not counts_toward_diagram("src/Button.stories.tsx")
    assert not counts_toward_diagram("tests/utils/test-helpers.ts")
    assert not counts_toward_diagram("test/app.router.js")
    assert not counts_toward_diagram("src/vite-env.d.ts")
    assert not counts_toward_diagram("dist/assets/index.js")
    assert not counts_toward_diagram("node_modules/react/index.js")
    assert not counts_toward_diagram("src/app.min.js")
    assert not counts_toward_diagram("playwright/foo.ts")
    assert not counts_toward_diagram("src/css.d.ts")


def test_keeps_non_test_infix():
    # "test" is a token, not a substring of the filename.
    assert counts_toward_diagram("src/lib/testimonial.ts")


def test_district_is_full_folder_not_parent_name():
    assert district_of("src/components/charts/BarChart.tsx") == "src.components.charts"
    assert district_of("packages/ui/src/components/Button.tsx") == "packages.ui.src.components"
    assert district_of("lib/express.js") == "lib"
    assert district_of("index.js") == "root"


def test_building_name_strips_longest_suffix():
    assert building_name("src/Foo.tsx") == "Foo"
    assert building_name("src/Foo.ts") == "Foo"
    assert building_name("lib/express.js") == "express"
    assert building_name("App.vue") == "App"


def test_filter_suggestions_are_js_not_java_service():
    rows = (
        [{"name": "BarChart", "district": "src.components.charts"}] * 4
        + [{"name": "usePlannerStore", "district": "src.hooks"}] * 3
        + [{"name": "PlannerWorkspace", "district": "src.components"}] * 3
        + [{"name": "CsvImportDialog", "district": "src.components"}] * 3
        + [{"name": "badge", "district": "src.components.ui"}] * 4
    )
    globs = [s["glob"] for s in filter_suggestions(rows, folder_min=4, name_min=3)]
    assert "..charts.*" in globs
    assert "..ui.*" in globs
    assert "..use*" in globs
    assert "..Planner*" in globs
    assert "*Dialog" in globs
    assert "*Service" not in globs


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    raise SystemExit(failed)
