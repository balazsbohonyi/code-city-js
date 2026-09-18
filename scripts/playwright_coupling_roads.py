"""Exercise ⌥ / Alt coupling roads on a generated codecity.html (Playwright).

Asserts public behaviour: roadsHint present, COUPLING data loaded, and after
Alt+hover the tooltip shows “(N roads)” / “(N of M drawn)” on fan-in/out lines
(wireNote). Does not rely on private `let` bindings (streetGroup, etc.).
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
    shot = Path(argv[3]).resolve() if len(argv) > 3 else None

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

        baseline = page.evaluate(
            """() => {
              const classes = (COUPLING && COUPLING.classes) || {};
              let top = null, n = 0;
              for (const k of Object.keys(classes)) {
                const c = Object.keys(classes[k] || {}).length;
                if (c > n) { n = c; top = k; }
              }
              const inter = document.getElementById('interPkgOnly');
              return {
                roadsHint: !!document.getElementById('roadsHint'),
                buildingsWithOut: Object.keys(classes).length,
                topBuilding: top,
                topOut: n,
                interPkgControl: !!inter,
                height: document.getElementById('heightMetric')?.value || null,
              };
            }"""
        )
        print(f"=== {label} baseline")
        print(json.dumps(baseline, indent=2))

        if not baseline.get("roadsHint") or baseline.get("buildingsWithOut", 0) < 1:
            browser.close()
            print("FAIL: no coupling data / roads hint")
            return 1

        # Hold Alt and sweep the plate. wireNote appends "(N roads)" on fan-in/out
        # when streets are drawn for the hovered building.
        found = page.evaluate(
            """async () => {
              const canvas = document.querySelector('canvas');
              const w = canvas.clientWidth, h = canvas.clientHeight;
              const points = [];
              for (let i = 1; i <= 8; i++) {
                for (let j = 1; j <= 6; j++) {
                  points.push([w * i / 9, h * j / 7]);
                }
              }
              window.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Alt', code: 'AltLeft', altKey: true, bubbles: true,
              }));

              let best = null;
              let hits = 0;
              for (const [x, y] of points) {
                window.dispatchEvent(new PointerEvent('pointermove', {
                  clientX: x, clientY: y, altKey: true, bubbles: true,
                }));
                await new Promise(r => requestAnimationFrame(r));
                const hover = document.getElementById('hover');
                if (!hover || !hover.classList.contains('visible')) continue;
                hits++;
                const html = hover.innerHTML || '';
                const text = hover.innerText || '';
                const hasRoadNote = /\\d+\\s+roads?|\\d+\\s+of\\s+\\d+\\s+drawn/i.test(html + text);
                const row = {
                  x, y,
                  hasRoadNote,
                  text: text.slice(0, 400),
                  mentionsFanOut: /outgoing coupling/i.test(html + text),
                  mentionsFanIn: /incoming coupling/i.test(html + text),
                };
                if (hasRoadNote) return { ok: true, hits, ...row };
                if (!best) best = row;
              }
              if (!best) return { ok: false, reason: 'no building hover under Alt', hits };
              return { ok: true, hits, ...best, reason: 'hovered but no road note yet' };
            }"""
        )
        print(f"=== {label} Alt hover")
        print(json.dumps(found, indent=2))

        if shot:
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot), type="png")
            print(f"screenshot -> {shot}")

        page.evaluate(
            """() => {
              window.dispatchEvent(new KeyboardEvent('keyup', {
                key: 'Alt', code: 'AltLeft', altKey: false, bubbles: true,
              }));
            }"""
        )
        page.wait_for_timeout(200)

        if errors:
            print("page errors:", errors[:5])

        browser.close()

        if not found.get("ok"):
            print("FAIL:", found.get("reason"))
            return 1
        if not found.get("hasRoadNote"):
            # Building may have fan_in/out 0 (no wires). Retry criterion: still
            # require roadsHint + COUPLING; soft-fail only if topOut suggests wires.
            if baseline.get("topOut", 0) > 0:
                print("FAIL: Alt hover did not show road count note on fan-in/out")
                print("altText:", found.get("altText"))
                return 1
            print("WARN: no road note (hovered building may have zero wires)")
        print("PASS: coupling UI present; Alt hover shows road wiring notes")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
