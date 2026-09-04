// Node-runnable unit tests for static/cv.js -- no browser needed.
//
//     node tests/browser/cv.test.mjs
//
// cv.js targets `window.faradayCV`, so a bare `window = {}` is enough of a
// DOM to load it under Node; nothing here touches an actual canvas.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const cvPath = path.join(here, "..", "..", "static", "cv.js");

global.window = {};
new Function(fs.readFileSync(cvPath, "utf8"))();
const cv = global.window.faradayCV;

let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    failures++;
    console.error("FAIL:", msg);
  } else {
    console.log("ok:", msg);
  }
}

// -- rgbToHsv matches OpenCV's convention closely enough for thresholding --
{
  const [h, s, v] = cv.rgbToHsv(215, 40, 40); // the magnet's red marker
  assert(h <= 5 || h >= 175, `red hue should sit near 0/179, got ${h}`);
  assert(s > 200, `red saturation should be high, got ${s}`);
  assert(v === 215, `value should equal the max channel, got ${v}`);
}
{
  const [h, s, v] = cv.rgbToHsv(0, 0, 0);
  assert(s === 0 && v === 0, `black should read s=0,v=0, got s=${s} v=${v}`);
}

// -- hue wraparound: a box that straddles red must catch both sides --
{
  const data = new Uint8ClampedArray([
    255,
    0,
    4,
    255, // near-red (low hue, just above 0)
    0,
    255,
    90,
    255, // cyan -- must NOT match
    255,
    4,
    0,
    255, // near-red the other way (just below 180)
  ]);
  const { mask } = cv.buildMask(
    { width: 3, height: 1, data },
    { h_lo: 170, h_hi: 10, s_lo: 100, s_hi: 255, v_lo: 100, v_hi: 255 },
    {},
  );
  assert(
    mask[0] === 255 && mask[2] === 255,
    "both sides of the wrap must match",
  );
  assert(mask[1] === 0, "cyan must not match a red wraparound box");
}

// -- connected components + min-area filtering --
{
  const w = 10,
    h = 10;
  const mask = new Uint8Array(w * h);
  for (let y = 1; y < 5; y++) for (let x = 1; x < 5; x++) mask[y * w + x] = 255;
  mask[8 * w + 8] = 255; // a lone speck elsewhere

  const all = cv.findBlobs(mask, w, h, 1);
  assert(
    all.length === 2,
    `expected 2 blobs before filtering, got ${all.length}`,
  );

  const filtered = cv.findBlobs(mask, w, h, 5);
  assert(
    filtered.length === 1,
    `min-area should drop the speck, got ${filtered.length}`,
  );
  assert(
    filtered[0].area === 16,
    `blob area should be 16, got ${filtered[0].area}`,
  );
  assert(
    Math.abs(filtered[0].cx - 2.5) < 1e-9 &&
      Math.abs(filtered[0].cy - 2.5) < 1e-9,
    `centroid should be (2.5, 2.5), got (${filtered[0].cx}, ${filtered[0].cy})`,
  );
}

// -- selectBlob: continuity beats size, and an impossible jump is rejected --
{
  const blobs = [
    { cx: 100, cy: 60, area: 400 },
    { cx: 200, cy: 130, area: 150 },
  ];
  assert(
    cv.selectBlob(blobs, null).cx === 100,
    "no previous position -> largest wins",
  );
  assert(
    cv.selectBlob(blobs, [198, 128]).cx === 200,
    "previous position near the small blob -> continuity wins",
  );
  assert(
    cv.selectBlob(blobs, [10, 10], 5) === null,
    "a jump farther than max_jump_px must be rejected",
  );
}

// -- morphology: a lone pixel dies under a 3x3 open; a solid block survives --
{
  const w = 9,
    h = 9;
  const lone = new Uint8Array(w * h);
  lone[4 * w + 4] = 255;
  const opened = cv.cleanMask(lone, w, h, { open_ksize: 3, close_ksize: 0 });
  assert(
    opened.every((v) => v === 0),
    "a lone pixel must be erased by a 3x3 open",
  );

  const block = new Uint8Array(w * h);
  for (let y = 2; y < 7; y++)
    for (let x = 2; x < 7; x++) block[y * w + x] = 255;
  const openedBlock = cv.cleanMask(block, w, h, {
    open_ksize: 3,
    close_ksize: 0,
  });
  assert(
    openedBlock[4 * w + 4] === 255,
    "the center of a solid block must survive opening",
  );
}

// -- clicking the magnet must re-detect the very pixel it was sampled from --
{
  const w = 20,
    h = 20;
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    data[i * 4] = 220;
    data[i * 4 + 1] = 30;
    data[i * 4 + 2] = 30;
    data[i * 4 + 3] = 255;
  }
  const color = cv.sampleColorRange({ width: w, height: h, data }, 10, 10, {
    radius: 5,
  });
  const { mask } = cv.buildMask({ width: w, height: h, data }, color, {});
  assert(
    mask[10 * w + 10] === 255,
    "the sampled colour must re-detect its own source pixel",
  );
}

// -- segment.blur must actually run: an isolated same-hue noise pixel on a
// contrasting background should vanish once blurred, while a real solid
// blob (all neighbours the same colour) is unaffected -- this is what tells
// a genuine magnet apart from JPEG/skin/wood-grain speckle in real footage.
{
  const w = 20,
    h = 20;
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) data[i * 4 + 3] = 255; // opaque, else black
  const paintRed = (x, y) => {
    const i = (y * w + x) * 4;
    data[i] = 220;
    data[i + 1] = 20;
    data[i + 2] = 20;
  };
  for (let y = 2; y < 8; y++) for (let x = 2; x < 8; x++) paintRed(x, y); // solid block
  paintRed(16, 16); // isolated speck, surrounded by black background

  const color = {
    h_lo: 0,
    h_hi: 8,
    s_lo: 100,
    s_hi: 255,
    v_lo: 100,
    v_hi: 255,
  };

  const unblurred = cv.buildMask({ width: w, height: h, data }, color, {
    blur: 0,
  });
  assert(
    unblurred.mask[5 * w + 5] === 255,
    "unblurred: block interior should match",
  );
  assert(
    unblurred.mask[16 * w + 16] === 255,
    "unblurred: the noise speck also matches",
  );

  const blurred = cv.buildMask({ width: w, height: h, data }, color, {
    blur: 5,
  });
  assert(
    blurred.mask[5 * w + 5] === 255,
    "blurred: block interior must still match",
  );
  assert(
    blurred.mask[16 * w + 16] === 0,
    "blurred: an isolated speck should be smoothed below threshold",
  );
}

// -- boxBlurChannel: a single bright value surrounded by zeros gets diluted --
{
  const w = 9,
    h = 9;
  const src = new Uint8Array(w * h);
  src[4 * w + 4] = 255;
  const out = cv.boxBlurChannel(src, w, h, 5);
  assert(
    out[4 * w + 4] < 30,
    `centre should be diluted toward 0, got ${out[4 * w + 4]}`,
  );
  assert(out[0] === 0, "far corners untouched by a small kernel should stay 0");
}

// -- ledLevel: a bright rectangle in a dark frame reads high --
{
  const w = 20,
    h = 20;
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    data[i * 4] = 20;
    data[i * 4 + 1] = 20;
    data[i * 4 + 2] = 20;
    data[i * 4 + 3] = 255;
  }
  for (let y = 0; y < 5; y++) {
    for (let x = 0; x < 5; x++) {
      const i = (y * w + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = 250;
    }
  }
  const level = cv.ledLevel({ width: w, height: h, data }, [0, 0, 5, 5]);
  assert(level > 200, `a bright LED roi should read a high V, got ${level}`);

  const dark = cv.ledLevel({ width: w, height: h, data }, [10, 10, 5, 5]);
  assert(dark < 30, `background outside the LED must read low, got ${dark}`);
}

console.log(
  failures ? `\n${failures} FAILED` : "\nALL JS CV UNIT TESTS PASSED",
);
process.exit(failures ? 1 : 0);
