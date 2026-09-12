#!/usr/bin/env python3
"""Build an editable SVG: the original circuit screenshot with parts swapped out.

The screenshot stays as the bottom layer, so every wire keeps its original
pixels. On top of it go:

  1. cover rectangles that hide the old part art, filled with a tile cropped
     from a clean patch of the screenshot so the graph-paper grid keeps going
  2. the replacement parts, inlined as real vector groups

Inlining rather than <image href="parts/solenoid.svg"> is deliberate: the
result is one self-contained file whose parts can still be selected, moved and
recoloured in Inkscape or any text editor.

Layout lives in placement.json so tweaking a position never means touching code.
"""

import argparse
import base64
import io
import json
import pathlib
import re

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  <title>{title}</title>
{defs}
  <!-- layer 1: the original screenshot, untouched -->
  <image id="base" x="0" y="0" width="{w}" height="{h}"
         xlink:href="{base_href}"/>

  <!-- layer 2: cover the outgoing part art -->
  <g id="covers">
{covers}
  </g>

  <!-- layer 3: replacement parts -->
{parts}

  <!-- layer 4: wire stubs joining the new parts to the original wiring -->
  <g id="wires" fill="none" stroke-linecap="round" stroke-linejoin="round">
{wires}
  </g>
</svg>
"""


def data_uri(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def inline_part(path, prefix, transform, label, hide=()):
    """Return the part's markup as a <g>, with every id namespaced by prefix."""
    text = path.read_text()

    box = re.search(r'viewBox\s*=\s*"([\d.\-\s]+)"', text)
    if not box:
        raise SystemExit(f"{path}: no viewBox")
    vb = [float(v) for v in box.group(1).split()]

    body = text[text.index(">", text.index("<svg")) + 1 : text.rindex("</svg>")]

    for ident in sorted(
        set(re.findall(r'\bid="([^"]+)"', body)), key=len, reverse=True
    ):
        new = f"{prefix}-{ident}"
        body = body.replace(f'id="{ident}"', f'id="{new}"')
        body = body.replace(f"url(#{ident})", f"url(#{new})")
        body = body.replace(f'href="#{ident}"', f'href="#{new}"')

    for ident in hide:
        target = f'id="{prefix}-{ident}"'
        if target not in body:
            raise SystemExit(f"{path}: cannot hide unknown id {ident!r}")
        body = body.replace(target, target + ' style="display:none"')

    body = "\n".join("    " + line for line in body.strip().splitlines())
    return vb, (
        f'  <g id="{prefix}" data-part="{label}" transform="{transform}">\n'
        f"{body}\n  </g>"
    )


def build(cfg_path, out_path, link_base):
    from PIL import Image

    cfg = json.loads(cfg_path.read_text())
    root = cfg_path.parent

    base_path = root / cfg["base"]
    if not base_path.exists():
        raise SystemExit(
            f"base image not found: {base_path}\n"
            f"Drop the circuit screenshot there (or edit 'base' in {cfg_path.name})."
        )
    base_img = Image.open(base_path).convert("RGBA")
    w, h = base_img.size

    if link_base:
        base_href = cfg["base"]
    else:
        buf = io.BytesIO()
        base_img.save(buf, format="PNG")
        base_href = data_uri(buf.getvalue())

    # background tile, so cover rectangles keep the grid running
    defs = ""
    tile = cfg.get("background_tile")
    if tile:
        tx, ty, tw, th = (tile[k] for k in ("x", "y", "w", "h"))
        crop = base_img.crop((tx, ty, tx + tw, ty + th))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        # phase-align the tiling to where the crop came from, or the grid shifts
        defs = (
            "  <defs>\n"
            f'    <pattern id="bg-tile" patternUnits="userSpaceOnUse"\n'
            f'             x="{tx % tw}" y="{ty % th}" width="{tw}" height="{th}">\n'
            f'      <image xlink:href="{data_uri(buf.getvalue())}"\n'
            f'             x="0" y="0" width="{tw}" height="{th}"/>\n'
            "    </pattern>\n"
            "  </defs>\n"
        )
        cover_fill = "url(#bg-tile)"
    else:
        cover_fill = cfg.get("cover_fill", "#ffffff")

    covers = []
    parts = []
    for spec in cfg["parts"]:
        prefix = spec["id"]
        for i, r in enumerate(spec.get("cover", [])):
            covers.append(
                f'    <rect id="{prefix}-cover-{i}" x="{r["x"]}" y="{r["y"]}" '
                f'width="{r["w"]}" height="{r["h"]}" fill="{cover_fill}"/>'
            )

        scale = spec.get("scale", 1.0)
        hide = tuple(spec.get("hide", ()))
        transform = f"translate({spec['x']},{spec['y']}) scale({scale})"
        # read the viewBox first: mirroring and rotation both need the part's size
        vb, _ = inline_part(root / spec["part"], prefix, transform, spec["part"], hide)
        if spec.get("mirror"):
            transform += f" translate({vb[2]},0) scale(-1,1)"
        if spec.get("rotate"):
            transform += f" rotate({spec['rotate']},{vb[2] / 2},{vb[3] / 2})"
        _, markup = inline_part(
            root / spec["part"], prefix, transform, spec["part"], hide
        )
        parts.append(markup)

    wires = []
    for i, wire in enumerate(cfg.get("wires", [])):
        pts = " ".join(f"{x},{y}" for x, y in wire["points"])
        wires.append(
            f'    <polyline id="wire-{wire.get("name", i)}" points="{pts}" '
            f'stroke="{wire["color"]}" stroke-width="{wire.get("width", 9)}"/>'
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        TEMPLATE.format(
            w=w,
            h=h,
            title=cfg.get("title", "Circuit"),
            defs=defs,
            base_href=base_href,
            covers="\n".join(covers) if covers else "",
            parts="\n".join(parts),
            wires="\n".join(wires),
        )
    )
    print(
        f"{out_path}  {w}x{h}  ({len(cfg['parts'])} parts, "
        f"{len(covers)} covers, {len(wires)} wires)"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "config",
        nargs="?",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "placement.json",
    )
    ap.add_argument(
        "-o",
        "--out",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "out" / "circuit.svg",
    )
    ap.add_argument(
        "--link",
        action="store_true",
        help="reference the base PNG by path instead of embedding it",
    )
    args = ap.parse_args()
    build(args.config, args.out, args.link)


if __name__ == "__main__":
    main()
