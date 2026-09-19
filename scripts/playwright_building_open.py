"""Verify Ctrl-double-click on a building opens the editor.

Repro for the Windows conflict: OrbitControls treats Ctrl+LEFT as rotate when
LEFT=PAN, which stole Ctrl-double-click-to-source (same class of bug as
``playwright_road_jump.py``). Flow:

1. Dismiss the intro
2. Project a building to screen (fallback: sweep until #hover is visible)
3. Hold Control; cursor should be ``pointer``, not the orbit glyph
4. Double-click with a 2px jitter; expect ``codecity-open-editor``
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SWIFT = [
    "--enable-unsafe-swiftshader",
    "--use-angle=swiftshader",
    "--no-sandbox",
]


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
            }"""
        )

        canvas = page.locator("canvas").first
        box = canvas.bounding_box()
        if not box:
            browser.close()
            print("FAIL: no canvas box")
            return 1

        projected = page.evaluate(
            """() => {
              const api = window.codecity;
              if (!api || !api.buildings || !api.buildings.length) return null;
              const camera = api.camera;
              const b = api.buildings[0];
              const pos = b.mesh.position;
              const v = pos.clone().project(camera);
              return {
                ndcX: v.x,
                ndcY: v.y,
                path: b.file && b.file.path,
                x: (v.x * 0.5 + 0.5) * window.innerWidth,
                y: (-v.y * 0.5 + 0.5) * window.innerHeight,
              };
            }"""
        )

        building_at = None
        expected_path = None
        if (
            projected
            and projected.get("path")
            and -0.95 < projected["ndcX"] < 0.95
            and -0.95 < projected["ndcY"] < 0.95
        ):
            building_at = (projected["x"], projected["y"])
            expected_path = projected["path"]
        else:
            for i in range(1, 12):
                for j in range(1, 10):
                    x = box["x"] + (i / 12) * box["width"]
                    y = box["y"] + (j / 10) * box["height"]
                    page.mouse.move(x, y)
                    page.wait_for_timeout(30)
                    hover = page.locator("#hover.visible")
                    if hover.count():
                        building_at = (x, y)
                        break
                if building_at:
                    break

        if not building_at:
            browser.close()
            print("FAIL: no on-screen building to double-click")
            return 1

        print(f"=== {label} building at ({building_at[0]:.0f}, {building_at[1]:.0f})")
        if expected_path:
            print(f"projected path: {expected_path}")

        page.mouse.move(building_at[0], building_at[1])
        page.wait_for_timeout(80)
        page.keyboard.down("Control")
        page.wait_for_timeout(50)
        cursor_before = page.evaluate(
            "() => document.querySelector('canvas')?.style?.cursor || ''"
        )
        rotate_locked = page.evaluate(
            """([x, y]) => {
              const down = new PointerEvent('pointerdown', {
                bubbles: true, cancelable: true, composed: true,
                clientX: x, clientY: y, ctrlKey: true, button: 0,
                pointerType: 'mouse',
              });
              window.dispatchEvent(down);
              const locked = window.codecity.controls.enableRotate === false;
              window.dispatchEvent(new PointerEvent('pointerup', {
                bubbles: true, cancelable: true, composed: true,
                clientX: x, clientY: y, ctrlKey: true, button: 0,
                pointerType: 'mouse',
              }));
              return locked;
            }""",
            [building_at[0], building_at[1]],
        )

        page.mouse.move(building_at[0], building_at[1])
        page.wait_for_timeout(30)
        page.mouse.dblclick(building_at[0] + 2, building_at[1] + 2)
        page.wait_for_timeout(200)

        result = page.evaluate(
            """() => ({
              opens: window.__codecityOpens.slice(),
              rotateEnabled: window.codecity.controls.enableRotate,
            })"""
        )
        try:
            page.keyboard.up("Control")
        except Exception:
            pass

        opens = result["opens"]
        print(
            json.dumps(
                {
                    "cursorBeforeClick": cursor_before[:80],
                    "rotateLockedOnCtrlDown": rotate_locked,
                    "opens": opens,
                    "pageErrors": errors,
                },
                indent=2,
            )
        )
        browser.close()

        ok = True
        if cursor_before != "pointer":
            print("FAIL: expected pointer cursor over a building while Ctrl held")
            ok = False
        if not rotate_locked:
            print("FAIL: enableRotate stayed true on Ctrl pointerdown over a building")
            ok = False
        if not opens:
            print("FAIL: codecity-open-editor did not fire")
            ok = False
        else:
            href = opens[0].get("href") or ""
            if "vscode://file/" not in href:
                print("FAIL: href missing vscode://file/ prefix", href)
                ok = False
            if "\\" in href:
                print("FAIL: href still has backslashes", href)
                ok = False
            if expected_path and opens[0].get("path") != expected_path:
                print(
                    "FAIL: opened path",
                    opens[0].get("path"),
                    "!= projected",
                    expected_path,
                )
                ok = False
        if errors:
            print("FAIL: page errors", errors)
            ok = False
        if ok:
            print("PASS: Ctrl-double-click on building dispatched codecity-open-editor")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
