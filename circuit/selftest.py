#!/usr/bin/env python3
"""End-to-end check of the assemble -> render pipeline.

Runs against a synthetic screenshot (graph-paper grid + two coloured blobs
standing in for the parts being replaced) so the pipeline is provable without
the real circuit export. Exits non-zero on any failure.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).parent
GRID = (205, 214, 223)
PAPER = (255, 255, 255)
OLD_MOTOR = (120, 120, 128)
OLD_BOARD = (40, 90, 190)

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def make_base(path, w=900, h=600):
    im = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(im)
    for x in range(0, w, 20):
        d.line([(x, 0), (x, h)], fill=GRID)
    for y in range(0, h, 20):
        d.line([(0, y), (w, y)], fill=GRID)
    d.rectangle([100, 80, 240, 320], fill=OLD_MOTOR)  # outgoing "motor"
    d.rectangle([560, 300, 810, 500], fill=OLD_BOARD)  # outgoing "breakout"
    im.save(path)
    return im.size


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        (work / "parts").mkdir()
        for p in (HERE / "parts").glob("*.svg"):
            (work / "parts" / p.name).write_text(p.read_text())

        w, h = make_base(work / "base.png")

        cfg = {
            "title": "selftest",
            "base": "base.png",
            "background_tile": {"x": 400, "y": 40, "w": 40, "h": 40},
            "parts": [
                {
                    "id": "solenoid",
                    "part": "parts/solenoid.svg",
                    "x": 100,
                    "y": 80,
                    "scale": 0.9,
                    "cover": [{"x": 96, "y": 76, "w": 150, "h": 250}],
                },
                {
                    "id": "ads",
                    "part": "parts/ads1115.svg",
                    "x": 560,
                    "y": 300,
                    "scale": 0.8,
                    "cover": [{"x": 556, "y": 296, "w": 260, "h": 210}],
                },
            ],
        }
        (work / "placement.json").write_text(json.dumps(cfg, indent=2))

        print("assemble:")
        r = subprocess.run(
            [
                sys.executable,
                str(HERE / "assemble.py"),
                str(work / "placement.json"),
                "-o",
                str(work / "circuit.svg"),
            ],
            capture_output=True,
            text=True,
        )
        check("assemble.py exits 0", r.returncode == 0, r.stderr.strip()[:200])
        if r.returncode != 0:
            return 1
        svg = work / "circuit.svg"

        print("output svg:")
        try:
            ET.fromstring(svg.read_text())
            check("output is well-formed XML", True)
        except ET.ParseError as e:
            check("output is well-formed XML", False, str(e))

        text = svg.read_text()
        import re

        ids = re.findall(r'\bid="([^"]+)"', text)
        dupes = {i for i in ids if ids.count(i) > 1}
        check("no duplicate ids", not dupes, f"dupes={sorted(dupes)}" if dupes else "")
        check(
            "both parts inlined",
            'data-part="parts/solenoid.svg"' in text
            and 'data-part="parts/ads1115.svg"' in text,
        )
        check("base embedded as data uri", "data:image/png;base64," in text)

        print("render:")
        png = work / "circuit.png"
        r = subprocess.run(
            [sys.executable, str(HERE / "render.py"), str(svg), str(png)],
            capture_output=True,
            text=True,
        )
        check("render.py exits 0 (chromium)", r.returncode == 0, r.stderr.strip()[:200])

        # cairosvg is strict about XML and ignores HTML-parser leniency, so a
        # clean pass here is the signal that Inkscape et al. will open the file
        r2 = subprocess.run(
            [
                sys.executable,
                str(HERE / "render.py"),
                str(svg),
                str(work / "circuit_cairo.png"),
                "--engine",
                "cairo",
            ],
            capture_output=True,
            text=True,
        )
        check("renders under cairosvg too", r2.returncode == 0, r2.stderr.strip()[:200])
        if not png.exists():
            return 1

        im = Image.open(png).convert("RGB")
        check("rendered size matches base", im.size == (w, h), f"{im.size} vs {(w, h)}")
        px = im.load()

        def count(box, pred):
            x0, y0, x1, y1 = box
            return sum(
                1 for x in range(x0, x1) for y in range(y0, y1) if pred(px[x, y])
            )

        def near(c, target, tol=18):
            return all(abs(a - b) <= tol for a, b in zip(c, target))

        # The old art must be gone from the covered regions. Asserting "no pixel
        # looks like the old part" would be wrong - the solenoid's own grey
        # flange sits inside the old motor's colour range. What actually matters
        # is that the covered region no longer shows the ORIGINAL screenshot.
        base_im = Image.open(work / "base.png").convert("RGB")
        bpx = base_im.load()

        def changed_fraction(box):
            x0, y0, x1, y1 = box
            total = (x1 - x0) * (y1 - y0)
            same = sum(
                1
                for x in range(x0, x1)
                for y in range(y0, y1)
                if near(px[x, y], bpx[x, y], 12)
            )
            return 1 - same / total

        for label, box in [
            ("old motor art replaced", (100, 80, 240, 320)),
            ("old breakout art replaced", (560, 300, 810, 500)),
        ]:
            frac = changed_fraction(box)
            check(label, frac > 0.98, f"{frac:.1%} of the region changed")

        # the grid must continue through the covered area, not become a white patch
        strip = count((200, 290, 246, 326), lambda c: near(c, GRID, 12))
        check(
            "grid tiles through cover", strip > 0, f"{strip} grid px in exposed cover"
        )

        # and the new parts must actually be drawn
        copper = count(
            (100, 80, 260, 320),
            lambda c: c[0] > 150 and c[1] > 90 and c[2] < 110 and c[0] > c[2] + 60,
        )
        check("solenoid copper present", copper > 2000, f"{copper} px")
        pcb = count((560, 300, 810, 470), lambda c: max(c) < 60)
        check("ads1115 pcb present", pcb > 2000, f"{pcb} px")

        # untouched area of the screenshot must come through unchanged
        diff = sum(
            1
            for x in range(300, 500)
            for y in range(350, 550)
            if not near(px[x, y], bpx[x, y], 6)
        )
        check("untouched region preserved", diff == 0, f"{diff} changed px")

        (HERE / "out").mkdir(exist_ok=True)
        (HERE / "out" / "selftest.png").write_bytes(png.read_bytes())
        print(f"\nwrote {HERE / 'out' / 'selftest.png'}")

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
