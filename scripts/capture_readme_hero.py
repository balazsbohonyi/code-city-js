"""Capture docs/vscode-city.jpg for the public README hero.

Requirements from product copy:
- bottom-right shortcuts card collapsed
- CHANGES dropdown = "show everything" (changeMode=off)
- Overview-style metrics (complexity height)
- hide credit corner for a clean plate
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
DEFAULT_HTML = Path(r"D:\develop\playground\vscode\.codecity\codecity.html")
DEFAULT_OUT = HERE / "docs" / "vscode-city.jpg"


def main(argv: list[str]) -> int:
    html = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_HTML
    out = Path(argv[2]).resolve() if len(argv) > 2 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
                "--no-sandbox",
            ],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(html.as_uri(), wait_until="load", timeout=180_000)
        page.wait_for_selector("canvas", timeout=180_000)
        page.wait_for_timeout(2500)

        intro = page.locator("button.intro-dismiss")
        if intro.count():
            intro.first.click()
            page.wait_for_timeout(400)

        # Collapse bottom-right shortcuts card if visible.
        page.evaluate(
            """() => {
              const sc = document.getElementById('shortcuts');
              const btn = document.getElementById('shortcutsCollapse');
              if (sc && !sc.hidden && btn) btn.click();
            }"""
        )
        page.wait_for_timeout(200)

        # CHANGES = show everything; Overview metrics; Files view.
        page.evaluate(
            """() => {
              const set = (id, value) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.value = value;
                el.dispatchEvent(new Event('change', { bubbles: true }));
              };
              set('changeMode', 'off');
              set('viewMode', 'classes');
              set('areaMetric', 'bytes');
              set('heightMetric', 'cognitive_complexity');
              set('colorMetric', 'commits');
              const heightKloc = document.getElementById('heightKloc');
              if (heightKloc) {
                heightKloc.checked = false;
                heightKloc.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const colorKloc = document.getElementById('colorKloc');
              if (colorKloc) {
                colorKloc.checked = true;
                colorKloc.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const colorLog = document.getElementById('colorLog');
              if (colorLog) {
                colorLog.checked = true;
                colorLog.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const preset = document.querySelector('#presets .presetDot');
              if (preset) preset.click();
              // Presets may reset CHANGES — force "show everything" after Overview.
              set('changeMode', 'off');
              // Clean plate: hide credit corner for hero.
              for (const sel of ['.corner']) {
                const el = document.querySelector(sel);
                if (el) el.style.display = 'none';
              }
            }"""
        )
        page.wait_for_timeout(2000)

        # Confirm state before shot.
        state = page.evaluate(
            """() => ({
              changeMode: document.getElementById('changeMode')?.value,
              shortcutsHidden: !!document.getElementById('shortcuts')?.hidden,
              height: document.getElementById('heightMetric')?.value,
            })"""
        )
        print("hero state:", state)
        page.screenshot(path=str(out), type="jpeg", quality=82)
        print(f"wrote {out}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
