"""Verify Ctrl-click on a jumpable coupling road opens the editor.

Repro for the Windows conflict: OrbitControls treats Ctrl+LEFT as rotate when
LEFT=PAN, which stole Ctrl-click-to-source. Flow:

1. Hold Alt and sweep until a building shows road counts in the tooltip (roads drawn)
2. Also hold Control; sweep until the canvas cursor becomes ``pointer`` (jumpable road)
3. Click with a 2px jitter; expect ``codecity-open-editor``
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SWIFT = [
    "--enable-unsafe-swiftshader",
    "--use-angle=swiftshader",
    "--no-sandbox",
]

ROAD_NOTE = re.compile(r"\d+\s+roads?|\d+\s+of\s+\d+\s+drawn", re.I)


def main(argv: list[str]) -> int:
    html = Path(argv[1]).resolve()
    label = argv[2] if len(argv) > 2 else html.parent.parent.name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=SWIFT)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(html.as_uri(), wait_until="load", timeout=120_000)
        page.wait_for_selector("canvas", timeout=120_000)
        page.wait_for_timeout(1500)

        intro = page.locator("button.intro-dismiss")
        if intro.count():
            intro.first.click()
            page.wait_for_timeout(400)

        page.evaluate(
            """() => {
              window.__codecityPreventEditorNav = true;
              window.__codecityOpens = [];
              window.addEventListener('codecity-open-editor', (e) => {
                window.__codecityOpens.push(e.detail);
              });
              window.addEventListener('click', (e) => {
                window.__lastSceneClick = {
                  ctrl: !!e.ctrlKey,
                  meta: !!e.metaKey,
                  alt: !!e.altKey,
                  target: e.target && (e.target.id || e.target.className || e.target.tagName),
                };
              }, true);
            }"""
        )

        baseline = page.evaluate(
            """() => {
              const classes = (COUPLING && COUPLING.classes) || {};
              return {
                roadsHint: !!document.getElementById('roadsHint'),
                buildingsWithOut: Object.keys(classes).length,
              };
            }"""
        )
        print(f"=== {label} baseline")
        print(json.dumps(baseline, indent=2))
        if not baseline.get("roadsHint") or baseline.get("buildingsWithOut", 0) < 1:
            browser.close()
            print("FAIL: no coupling data / roads hint")
            return 1

        canvas = page.locator("canvas").first
        box = canvas.bounding_box()
        if not box:
            browser.close()
            print("FAIL: no canvas box")
            return 1

        # Hold Alt so roads draw on hover; find a building with a road note.
        building_at = None
        page.keyboard.down("Alt")
        try:
            for i in range(1, 10):
                for j in range(1, 8):
                    x = box["x"] + (i / 10) * box["width"]
                    y = box["y"] + (j / 8) * box["height"]
                    page.mouse.move(x, y)
                    page.wait_for_timeout(40)
                    hover = page.locator("#hover.visible")
                    if not hover.count():
                        continue
                    text = hover.inner_text()
                    if ROAD_NOTE.search(text):
                        building_at = (x, y)
                        break
                if building_at:
                    break

            if not building_at:
                print("FAIL: no Alt-hover building with road note")
                browser.close()
                return 1

            print(f"roads visible near ({building_at[0]:.0f}, {building_at[1]:.0f})")
            page.mouse.move(building_at[0], building_at[1])
            page.wait_for_timeout(100)

            # Still holding Alt, add Control and find a jumpable roadway (hand cursor).
            road_at = None
            page.keyboard.down("Control")
            page.wait_for_timeout(50)
            candidates = []
            for i in range(-6, 7):
                for j in range(-6, 7):
                    candidates.append(
                        (building_at[0] + i * 18, building_at[1] + j * 18)
                    )
            for i in range(1, 18):
                for j in range(1, 12):
                    candidates.append(
                        (
                            box["x"] + (i / 18) * box["width"],
                            box["y"] + (j / 12) * box["height"],
                        )
                    )
            for x, y in candidates:
                if not (
                    box["x"] <= x <= box["x"] + box["width"]
                    and box["y"] <= y <= box["y"] + box["height"]
                ):
                    continue
                page.mouse.move(x, y)
                page.wait_for_timeout(20)
                cursor = page.evaluate(
                    "() => document.querySelector('canvas')?.style?.cursor || ''"
                )
                if cursor == "pointer":
                    road_at = (x, y)
                    break

            if not road_at:
                print("FAIL: no screen point where Ctrl+Alt hover shows pointer on a road")
                hist = page.evaluate(
                    """() => {
                      const c = document.querySelector('canvas');
                      return c ? c.style.cursor.slice(0, 40) : '';
                    }"""
                )
                print("last cursor prefix:", hist)
                browser.close()
                return 1

            print(f"jumpable road cursor at ({road_at[0]:.0f}, {road_at[1]:.0f})")

            page.mouse.move(road_at[0], road_at[1])
            page.wait_for_timeout(30)
            cursor_before = page.evaluate(
                "() => document.querySelector('canvas')?.style?.cursor || ''"
            )
            page.mouse.down()
            page.mouse.move(road_at[0] + 2, road_at[1] + 2)
            page.mouse.up()
            page.wait_for_timeout(200)

            result = page.evaluate(
                """() => ({
                  opens: window.__codecityOpens.slice(),
                  lastClick: window.__lastSceneClick || null,
                })"""
            )
            opens = result["opens"]
            print(
                json.dumps(
                    {
                        "cursorBeforeClick": cursor_before,
                        "opens": opens,
                        "lastClick": result["lastClick"],
                        "pageErrors": errors,
                    },
                    indent=2,
                )
            )
        finally:
            try:
                page.keyboard.up("Control")
            except Exception:
                pass
            try:
                page.keyboard.up("Alt")
            except Exception:
                pass

        browser.close()

        ok = True
        if cursor_before != "pointer":
            print("FAIL: expected pointer cursor over jumpable road while Ctrl held")
            ok = False
        if not opens:
            print("FAIL: codecity-open-editor did not fire (orbit likely stole the click)")
            ok = False
        if errors:
            print("FAIL: page errors", errors)
            ok = False
        if ok:
            print("PASS: Ctrl-click on road dispatched codecity-open-editor")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
