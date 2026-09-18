"""Assert a generated codecity.html has coupling roads data."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(argv: list[str]) -> int:
    html = Path(argv[1]).resolve()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
                "--no-sandbox",
            ],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(html.as_uri(), wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_selector("canvas", timeout=120_000)
        btn = page.query_selector("button.intro-dismiss")
        if btn:
            btn.click()
        page.wait_for_timeout(500)
        info = page.evaluate(
            """() => {
              const classes = (typeof COUPLING !== 'undefined' && COUPLING && COUPLING.classes)
                ? COUPLING.classes : {};
              const keys = Object.keys(classes);
              let top = null, n = 0;
              for (const k of keys) {
                const c = Object.keys(classes[k] || {}).length;
                if (c > n) { n = c; top = k; }
              }
              return {
                buildingCount: keys.length,
                topBuilding: top,
                topOut: n,
                roadsHint: !!document.getElementById('roadsHint'),
                height: document.getElementById('heightMetric')?.value || null,
              };
            }"""
        )
        browser.close()
    print(info)
    if not info.get("roadsHint") or info.get("buildingCount", 0) < 1:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
