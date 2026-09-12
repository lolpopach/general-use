#!/usr/bin/env python3
"""Render an SVG to PNG.

Chromium (accurate, matches what a browser/Inkscape shows) with a cairosvg
fallback. Used both to check parts while drawing them and to export the
finished circuit.
"""

import argparse
import pathlib
import xml.etree.ElementTree as ET
import shutil
import subprocess
import sys
import tempfile

# headless_shell first on purpose: in the full chrome binary's new headless mode
# --window-size counts the window frame, so the viewport comes out short and the
# bottom of the drawing is silently cropped.
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
]

WRAPPER = """<!doctype html><meta charset="utf-8">
<style>
  html,body{{margin:0;padding:0;background:{bg};}}
  svg{{display:block;width:{w}px;height:{h}px;}}
</style>
{svg}
"""


def check_xml(svg_path):
    """Fail loudly on malformed SVG.

    Chromium parses an inlined SVG with the lenient HTML parser and will render
    something plausible from markup that every XML-based tool (Inkscape,
    librsvg, cairosvg) rejects outright. Checking here keeps the two engines
    honest with each other.
    """
    try:
        ET.fromstring(svg_path.read_text())
    except ET.ParseError as exc:
        raise SystemExit(f"{svg_path}: malformed XML: {exc}") from exc


def find_chrome():
    for path in CHROME_CANDIDATES:
        if pathlib.Path(path).exists():
            return path
    return shutil.which("chromium") or shutil.which("google-chrome")


def svg_size(svg_path):
    import re

    text = svg_path.read_text()
    box = re.search(r'viewBox\s*=\s*"([\d.\-\s]+)"', text)
    if not box:
        raise SystemExit(f"{svg_path}: no viewBox, cannot infer size")
    _, _, w, h = (float(v) for v in box.group(1).split())
    return w, h


def render_chromium(chrome, svg_path, out_path, scale, bg):
    w, h = svg_size(svg_path)
    out_w, out_h = round(w * scale), round(h * scale)
    with tempfile.TemporaryDirectory() as tmp:
        html = pathlib.Path(tmp) / "wrap.html"
        # inlined rather than <img src>: chromium blocks file:// subresources
        html.write_text(
            WRAPPER.format(bg=bg, w=out_w, h=out_h, svg=svg_path.read_text())
        )
        subprocess.run(
            [
                chrome,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--default-background-color=00000000",
                f"--window-size={out_w},{out_h}",
                f"--screenshot={out_path}",
                f"--user-data-dir={tmp}/profile",
                html.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
    return out_w, out_h


def render_cairo(svg_path, out_path, scale):
    import cairosvg

    cairosvg.svg2png(url=str(svg_path), write_to=str(out_path), scale=scale)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg", type=pathlib.Path)
    ap.add_argument("png", type=pathlib.Path)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--bg", default="transparent", help="CSS colour behind the SVG")
    ap.add_argument("--engine", choices=("chromium", "cairo"), default="chromium")
    args = ap.parse_args()

    check_xml(args.svg)
    args.png.parent.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    if args.engine == "chromium" and chrome:
        w, h = render_chromium(chrome, args.svg, args.png, args.scale, args.bg)
    else:
        if args.engine == "chromium":
            print("chromium not found, falling back to cairosvg", file=sys.stderr)
        render_cairo(args.svg, args.png, args.scale)
        w, h = svg_size(args.svg)
        w, h = round(w * args.scale), round(h * args.scale)
    print(f"{args.png}  {w}x{h}")


if __name__ == "__main__":
    main()
