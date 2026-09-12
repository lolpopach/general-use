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
- ADS1115: every header pin is addressable as `#ads-pin-V`, `#ads-pin-SCL`,
  `#ads-pin-A0` and so on. Attach wires to the bottom tip of the tail.

When a part is inlined by `assemble.py` its ids get namespaced, so
`#ads-pin-SCL` becomes `#ads1115-ads-pin-SCL` in the assembled file.

## Checking it

```bash
python3 circuit/selftest.py
```

Runs the whole assemble → render path against a synthetic screenshot (grid plus
two coloured blobs standing in for the outgoing parts) and asserts the covers
landed, the grid tiles through them, the new parts drew, and untouched areas of
the screenshot came through unchanged. It needs no `base.png`.

Two traps it exists to catch:

- **`--` inside an XML comment is illegal.** Chromium parses inlined SVG with
  the lenient HTML parser and renders something plausible anyway; cairosvg and
  Inkscape reject the file. `render.py` now parses as XML first.
- **Chromium's full binary crops the bottom of the page.** In new headless mode
  `--window-size` counts the window frame, so the viewport comes out short.
  `render.py` prefers `headless_shell`, which does not.
