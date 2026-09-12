# circuit

Swapping two part graphics in an Arduino circuit screenshot without redrawing
the wiring.

The original export stays as the bottom layer of an SVG, so every wire keeps
its original pixels. On top of it go cover rectangles that hide the outgoing
part art, then the replacement parts as real vector groups. The result is one
self-contained `.svg` you can open in Inkscape, select the solenoid, and drag.

## Use

```bash
cp /path/to/your/export.png circuit/base.png   # the screenshot being edited
python3 circuit/assemble.py                    # -> circuit/out/circuit.svg
python3 circuit/render.py circuit/out/circuit.svg circuit/out/circuit.png
```

Then open `circuit/out/circuit.png`, see what is misplaced, edit the numbers in
`placement.json`, and run it again. Nothing in `placement.json` requires
touching code:

| key                | meaning                                                    |
| ------------------ | ---------------------------------------------------------- |
| `base`             | the screenshot to edit, relative to `circuit/`             |
| `background_tile`  | a clean patch of grid, tiled into the covers               |
| `parts[].x` / `.y` | where the part's top-left corner lands, in base.png pixels |
| `parts[].scale`    | part size; 1.0 draws it at the size in its own `viewBox`   |
| `parts[].rotate`   | degrees, about the part's centre                           |
| `parts[].cover`    | rectangles of old art to hide                              |

`--link` references `base.png` by path instead of embedding it, for a much
smaller file that has to travel with the PNG.

## Parts

`parts/solenoid.svg` and `parts/ads1115.svg` are standalone and open on their
own. Useful handles:

- solenoid: `#solenoid-wire-plus` / `#solenoid-wire-minus` are the orange and
  purple terminal stubs — extend or reroute them to reach the rest of the
  circuit.
- ADS1115: every pad is addressable as `#ads-pad-VDD`, `#ads-pad-SCL`,
  `#ads-pad-A0` and so on. Attach wires at the pad centre.

When a part is inlined by `assemble.py` its ids get namespaced, so
`#ads-pad-SCL` becomes `#ads1115-ads-pad-SCL` in the assembled file.

## Checking it

```bash
python3 circuit/selftest.py         # the pipeline, on a synthetic screenshot
python3 circuit/verify_assembly.py  # the actual output, against base.png
```

`selftest.py` runs the whole assemble → render path against a synthetic
screenshot (grid plus two coloured blobs standing in for the outgoing parts) and
asserts the covers landed, the grid tiles through them, the new parts drew, and
untouched areas came through unchanged. It needs no `base.png`.

`verify_assembly.py` checks the real output: nothing outside the edited areas
moved, both old parts are gone, and every wire runs unbroken from the original
screenshot onto a new pad.

Both avoid one tempting but wrong assertion: "no pixel still looks like the old
part". The replacements legitimately reuse those colours — the solenoid's copper
highlight falls inside the DC motor's gold — so the test is whether the region
still shows the ORIGINAL screenshot, not whether a colour is absent. For the
same reason the comparison skips pixels that were graph paper to begin with;
a bounding box holds rounded corners that never were part art.

Traps these exist to catch:

- **`--` inside an XML comment is illegal.** Chromium parses inlined SVG with
  the lenient HTML parser and renders something plausible anyway; cairosvg and
  Inkscape reject the file. `render.py` now parses as XML first.
- **Chromium's full binary crops the bottom of the page.** In new headless mode
  `--window-size` counts the window frame, so the viewport comes out short.
  `render.py` prefers `headless_shell`, which does not.
- **The graph-paper grid period is 21.64px, not an integer.** The background
  tile is 303px because that is 14 periods to within 0.04px; a tile picked for
  roundness instead drifts visibly across a wide cover.
