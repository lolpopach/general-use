#!/usr/bin/env python3
"""Check the assembled circuit against the screenshot it was built from.

selftest.py proves the pipeline on a synthetic fixture; this proves the actual
output: nothing outside the edited areas moved, both old parts are really gone,
and every wire runs unbroken from the original screenshot onto a new pad.

Note on "the old part is gone": asserting that no pixel still looks like the old
part is the wrong test, because the replacement legitimately reuses those
colours - the solenoid's copper highlight sits inside the DC motor's gold. What
matters is that the region no longer shows the ORIGINAL screenshot.
"""

import json
import pathlib
import sys

from PIL import Image

HERE = pathlib.Path(__file__).parent

# where the outgoing parts sat in the screenshot, measured off base.png
OLD_MOTOR = (247, 32, 452, 218)
OLD_BREAKOUT = (1349, 885, 1499, 1103)

failures = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def near(a, b, tol):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def wire_mask(cfg, W, H):
    """Pixels the drawn wire stubs are allowed to touch."""
    mask = set()
    for wire in cfg["wires"]:
        r = wire.get("width", 9) / 2 + 3
        pts = [tuple(p) for p in wire["points"]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
            for i in range(steps + 1):
                t = i / steps
                cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                for dy in range(-int(r) - 1, int(r) + 2):
                    for dx in range(-int(r) - 1, int(r) + 2):
                        x, y = round(cx + dx), round(cy + dy)
                        if 0 <= x < W and 0 <= y < H:
                            mask.add((x, y))
    return mask


def main():
    cfg = json.loads((HERE / "placement.json").read_text())
    base = Image.open(HERE / cfg["base"]).convert("RGB")
    out_png = HERE / "out" / "circuit.png"
    if not out_png.exists():
        raise SystemExit("run assemble.py and render.py first")
    out = Image.open(out_png).convert("RGB")

    check(
        "output matches base size", out.size == base.size, f"{out.size} vs {base.size}"
    )
    if out.size != base.size:
        return 1
    bp, op = base.load(), out.load()
    W, H = base.size

    covers = [c for part in cfg["parts"] for c in part["cover"]]
    mask = wire_mask(cfg, W, H)

    def edited(x, y, pad=3):
        if (x, y) in mask:
            return True
        return any(
            c["x"] - pad <= x < c["x"] + c["w"] + pad
            and c["y"] - pad <= y < c["y"] + c["h"] + pad
            for c in covers
        )

    # 1. everything outside the edited areas must survive untouched
    changed = [
        (x, y)
        for y in range(0, H, 2)
        for x in range(0, W, 2)
        if not edited(x, y) and not near(op[x, y], bp[x, y], 6)
    ]
    check(
        "untouched areas preserved",
        not changed,
        f"{len(changed)} changed px, first {changed[:3]}",
    )

    # 2. the outgoing parts must no longer show the original screenshot.
    # Only pixels that were actually part art count: a bounding box also holds
    # the rounded corners and step-ins, which were graph paper to begin with and
    # are graph paper still, so counting them would dilute the result.
    def is_paper(c):
        return min(c) > 225 and max(c) - min(c) < 30

    for label, (x0, y0, x1, y1) in (
        ("DC motor", OLD_MOTOR),
        ("breakout", OLD_BREAKOUT),
    ):
        total = same = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                if is_paper(bp[x, y]):
                    continue
                total += 1
                same += near(op[x, y], bp[x, y], 12)
        frac = 1 - same / total
        check(f"{label} replaced", frac > 0.98, f"{frac:.1%} of its area changed")

    # 3. every wire must be drawn unbroken along its whole path
    for wire in cfg["wires"]:
        colour = tuple(int(wire["color"][i : i + 2], 16) for i in (1, 3, 5))
        pts = [tuple(p) for p in wire["points"]]
        samples = hits = 0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
            for i in range(steps + 1):
                t = i / steps
                x, y = round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t)
                samples += 1
                hits += near(op[x, y], colour, 70)
        check(
            f"wire {wire['name']} continuous",
            hits / samples > 0.97,
            f"{hits / samples:.1%} on colour",
        )

    # 4. the end that leaves the edited area must land on the untouched original
    for wire in cfg["wires"]:
        colour = tuple(int(wire["color"][i : i + 2], 16) for i in (1, 3, 5))
        ends = [tuple(round(v) for v in wire["points"][i]) for i in (0, -1)]
        ok = any(near(bp[x, y], colour, 70) for x, y in ends)
        check(
            f"wire {wire['name']} joins original",
            ok,
            f"base has {[bp[x, y] for x, y in ends]} at {ends}",
        )

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
