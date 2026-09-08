// Node-runnable unit tests for static/tracker.js's range resolution.
//
//     node tests/browser/tracker.test.mjs
//
// tracker.js only touches `document` inside the VideoTracker constructor, so
// a bare `window = {}` is enough to load it and exercise the pure helper that
// decides which stretch of a clip a run will actually walk.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
global.window = {};
new Function(
  fs.readFileSync(path.join(here, "..", "..", "static", "tracker.js"), "utf8"),
)();
const { resolveRange } = global.window.faradayTracker;

let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    failures++;
    console.error("FAIL:", msg);
  } else {
    console.log("ok:", msg);
  }
}

function eq(got, want, msg) {
  assert(
    Math.abs(got.start - want.start) < 1e-9 &&
      Math.abs(got.end - want.end) < 1e-9,
    `${msg} -- wanted ${want.start}..${want.end}, got ${got.start}..${got.end}`,
  );
}

// -- nothing set: the whole clip --
eq(resolveRange(30, null, null), { start: 0, end: 30 }, "no range set");
eq(
  resolveRange(30, undefined, undefined),
  { start: 0, end: 30 },
  "undefined ends",
);
eq(resolveRange(30, NaN, NaN), { start: 0, end: 30 }, "unparseable boxes");

// -- one end only: the other stays at the clip's own edge --
eq(resolveRange(30, 5, null), { start: 5, end: 30 }, "start only");
eq(resolveRange(30, null, 20), { start: 0, end: 20 }, "end only");

// -- both ends --
eq(resolveRange(30, 5, 20), { start: 5, end: 20 }, "both ends");

// -- clamped to the clip, so a stale range cannot walk off the end --
eq(resolveRange(30, -4, 99), { start: 0, end: 30 }, "clamped to the clip");
eq(resolveRange(30, 10, 99), { start: 10, end: 30 }, "end past the clip");

// -- a range that is not a range falls back to the whole clip rather than
// tracking zero frames: the user is mid-edit, not asking for nothing --
eq(resolveRange(30, 20, 5), { start: 0, end: 30 }, "backwards range");
eq(resolveRange(30, 12, 12), { start: 0, end: 30 }, "zero-length range");

// -- a clip whose duration the browser has not settled yet --
eq(resolveRange(NaN, 1, 2), { start: 0, end: 0 }, "unknown duration");
eq(resolveRange(Infinity, null, null), { start: 0, end: 0 }, "endless stream");

console.log(
  failures ? `\n${failures} FAILED` : "\nALL TRACKER UNIT TESTS PASSED",
);
process.exit(failures ? 1 : 0);
