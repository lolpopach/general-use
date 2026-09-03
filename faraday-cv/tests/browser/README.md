# Browser tests

Two layers:

- `cv.test.mjs` — pure unit tests of `static/cv.js` (HSV conversion, masking,
  morphology, connected components, blob selection, colour picking). No
  browser needed: `node tests/browser/cv.test.mjs`.
- `test_e2e.py` — drives the actual page in a real (headless) Chromium via
  Playwright: load a video, click the magnet, set the coil/LED/scale, run,
  and check the results that come back from `/api/analyze`. Requires
  `pip install playwright && playwright install chromium`; skips cleanly
  without it, so it is not part of the plain `pytest -q` dev loop.

## Why the e2e test uses a VP9 copy of the demo video

The project's canonical demo video (`faradaycv.synthetic`) is H.264, because
that is what a real phone or webcam produces and what OpenCV needs for the
CLI/local pipeline. The **open-source Chromium build that Playwright
downloads has no licensed H.264/HEVC decoder** — `video.canPlayType('video/mp4;
codecs="avc1.640028"')` returns `''` in that build. Real Chrome, Edge, and
Safari all ship proprietary codec support and do not have this limitation;
this is purely a test-harness constraint, not a statement about what end
users can play. `test_e2e.py` transcodes a throwaway VP9/WebM copy of the
demo video so the test's Chromium can open it at all, and does not touch the
canonical `.mp4`.

## What that substitution costs: a measured accuracy caveat

Comparing the browser-tracked centroids against the synthetic dataset's
ground truth (`ground_truth.json`), on the VP9 copy, in this headless
Chromium:

| decoder                                 | mean centroid error | max centroid error |
| --------------------------------------- | ------------------- | ------------------ |
| OpenCV/ffmpeg reading the same VP9 file | 0.40 px             | 0.83 px            |
| this browser reading the same VP9 file  | ~2.7 px             | ~11 px             |

The error is not random noise: it is close to zero near the pendulum's
turning points (where the magnet barely moves between frames) and largest
near the bottom of the swing (where it moves fastest) — the signature of the
canvas frame being captured a little before or after the browser has fully
settled on the new frame after a seek, magnified by how far the magnet moved
in that gap.

Two fixes were tried and both made it _worse_ in this specific environment:

- Confirming the seek with `requestVideoFrameCallback` before reading the
  canvas (the standard fix for exactly this kind of race) — this caused
  ~1/3 of frames to be silently skipped, most likely a callback/seek race
  particular to headless, software-decoded VP9 playback.
- A double `requestAnimationFrame` wait after `'seeked'` — no measurable
  effect at all, suggesting `'seeked'` was already fully settled here and
  the discrepancy has a different cause (most plausibly decoder-level: a
  loop/deblocking filter Chromium's decode path applies that ffmpeg's CLI
  decode of the same file does not, even under a "lossless" VP9 encode).

`static/tracker.js` ships the plain, best-measured `'seeked'`-based
implementation, with this investigation recorded in a comment there.

**What this does and does not mean:**

- The segmentation algorithm itself is verified correct: `cv.test.mjs`'s
  unit tests, and `tests/test_video.py`'s OpenCV-vs-ground-truth checks
  (<1.5 px max error) exercise the identical logic in Python. The gap above
  is specific to _this browser's decode of this test video_, not to the
  colour-segmentation math.
- `test_e2e.py` therefore does not assert tight pixel accuracy. It checks
  the things that must be exactly right regardless of tracking noise (LED
  sync, the voltage measurement, the figures rendering) and the paper's
  qualitative result (the speed peak and the voltage peak are measurably
  apart) survives.
- If you can run this suite with a real Chrome/Edge build (pass a different
  `executablePath`, or install `playwright install chrome`) against the
  canonical H.264 demo video, that is a stronger and more representative
  check than what runs here by default — the table above is a property of
  this sandbox's browser, not a guarantee about deployed accuracy.
