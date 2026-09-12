"""Drive the real page in a real browser: the strongest proof the client-side
tracker actually works, end to end, against the server's ``/api/analyze``.

Requires Playwright and a Chromium build with a video codec it can decode.
The reference Playwright Chromium build (the open-source one, with no
licensed H.264/HEVC) cannot play the project's canonical demo video, which
is H.264 for compatibility with real cameras and with OpenCV; this test
transcodes a throwaway VP9/WebM copy for that browser only.  See README.md
in this directory for what that substitution does and does not tell you
about tracking accuracy.

Skips cleanly wherever Playwright, a Chromium executable, or an ffmpeg with
VP9 support is missing -- this suite is not part of the required `pytest -q`
dev loop.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from faradaycv.decode import ffmpeg_binary  # noqa: E402
from faradaycv.webapp import create_app  # noqa: E402

CHROMIUM_CANDIDATES = [
    Path.home() / ".cache" / "ms-playwright",
    Path("/opt/pw-browsers"),
]


def _find_chromium() -> str | None:
    for root in CHROMIUM_CANDIDATES:
        if not root.exists():
            continue
        hits = sorted(root.glob("chromium*/chrome-linux/chrome"))
        if hits:
            return str(hits[-1])
    return None


CHROMIUM_PATH = _find_chromium()


def _to_vp9(src: Path, dst: Path) -> None:
    ffmpeg = ffmpeg_binary()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "12",
            "-b:v",
            "0",
            str(dst),
        ],
        check=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def browser_video(dataset, tmp_path_factory):
    """A copy of the demo video in a codec this test's Chromium can play."""
    if not CHROMIUM_PATH:
        pytest.skip("no Playwright Chromium build found")
    if ffmpeg_binary() is None:
        pytest.skip("no ffmpeg available to make a browser-playable copy")
    out = tmp_path_factory.mktemp("browser-video") / "pendulum.webm"
    try:
        _to_vp9(dataset.video, out)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg could not produce a VP9 copy: {exc}")
    return out


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """The app in public mode -- exactly the deployment this flow is for."""
    workdir = tmp_path_factory.mktemp("webapp")
    app = create_app(workdir=workdir, local_mode=False)
    port = 8712
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    import urllib.request

    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        pytest.fail("the server did not come up in time")
    return f"http://127.0.0.1:{port}"


def test_browser_tracking_reproduces_the_papers_result(
    live_server, browser_video, dataset, truth
):
    """Full page flow: pick colour, set coil/LED, run, read results back.

    Centroid accuracy in this specific harness (headless Chromium, software
    VP9 decode, a synthetic test video) is measurably looser than OpenCV
    decoding the same content natively -- see README.md in this directory.
    That is a property of this test environment, not of the segmentation
    algorithm itself (static/cv.js's unit tests and the OpenCV-parity checks
    in tests/test_video.py cover that).  What this test guards is the
    physics conclusion actually reaching the page: the LED sync, the voltage
    reading, and the paper's central point that the speed peak and the
    voltage peak do not coincide.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            console_errors = []
            page.on(
                "console",
                lambda m: console_errors.append(m.text) if m.type == "error" else None,
            )
            page.goto(live_server)

            page.set_input_files("#video-file", str(browser_video))
            page.wait_for_function(
                "document.querySelector('#video-info').children.length > 0",
                timeout=20000,
            )

            box = page.locator("#canvas").bounding_box()

            def click_at(px, py):
                page.mouse.click(
                    box["x"] + box["width"] * px / 640,
                    box["y"] + box["height"] * py / 480,
                )

            def drag_rect(x, y, w, h):
                page.mouse.move(
                    box["x"] + box["width"] * x / 640,
                    box["y"] + box["height"] * y / 480,
                )
                page.mouse.down()
                page.mouse.move(
                    box["x"] + box["width"] * (x + w) / 640,
                    box["y"] + box["height"] * (y + h) / 480,
                    steps=8,
                )
                page.mouse.up()

            click_at(*truth["magnet_px"][0])
            page.wait_for_timeout(300)
            assert "1 blob(s)" in page.inner_text("#seg-stats"), page.inner_text(
                "#seg-stats"
            )

            page.click("button[data-mode='coil']")
            click_at(*truth["coil_px"])

            page.click("button[data-mode='led']")
            drag_rect(*truth["led_roi"])

            page.fill("#mm-per-px", str(truth["mm_per_px"]))
            page.fill("#track-fps", str(truth["fps"]))

            assert page.is_disabled("#run")
            page.set_input_files("#voltage-file", str(dataset.voltage))
            assert not page.is_disabled("#run")

            page.click("#run")
            page.wait_for_function(
                "document.querySelector('#status').innerText.includes('Done') || "
                "document.querySelector('#status').innerText.includes('failed')",
                timeout=120000,
            )
            status = page.inner_text("#status")
            assert "Done" in status, f"run did not finish cleanly: {status}"

            rows = page.inner_text("#stats-table")
            # "Done" only means the server answered; the <img> tags it created
            # are still fetching.  Reading naturalWidth before they land makes
            # this test fail for a reason that has nothing to do with tracking.
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#figures img'))"
                ".every((i) => i.complete)",
                timeout=30000,
            )
            figures = page.evaluate(
                "Array.from(document.querySelectorAll('#figures img')).map(i => i.naturalWidth)"
            )
        finally:
            browser.close()

    assert not console_errors, console_errors
    assert figures and all(w > 0 for w in figures), "a figure failed to render"

    assert f"{truth['t0_video_s']:.3f}" in rows or "0.200" in rows
    # the voltage measurement, independent of tracking accuracy, must be exact
    assert f"{truth['max_abs_emf_mV']:.1f}" in rows or "20.6" in rows
    # the paper's point: the two peaks are measurably apart, not simultaneous
    assert "Separation between the two peaks" in rows


def test_measuring_a_length_sets_the_scale_only_once_a_real_value_is_given(
    live_server, browser_video
):
    """Dragging measures; it must not calibrate on its own.

    The field used to default to 100 mm, so a drag silently decided the scale
    from a number nobody had confirmed -- and every distance and speed in the
    results came out wrong by whatever that guess was off by, with nothing
    saying so. A drag now reports pixels and waits.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            console_errors = []
            page.on(
                "console",
                lambda m: console_errors.append(m.text) if m.type == "error" else None,
            )
            page.goto(live_server)
            page.set_input_files("#video-file", str(browser_video))
            page.wait_for_function(
                "document.querySelector('#video-info').children.length > 0",
                timeout=20000,
            )

            assert page.is_hidden("#scale-panel"), "nothing measured yet"
            before = page.input_value("#mm-per-px")

            box = page.locator("#canvas").bounding_box()
            page.click("button[data-mode='scale']")
            # drag a horizontal line across a quarter of the 640 px-wide frame
            page.mouse.move(
                box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.5
            )
            page.mouse.down()
            page.mouse.move(
                box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5, steps=8
            )
            page.mouse.up()

            assert page.is_visible("#scale-panel"), "the measurement should be shown"
            measured_px = float(page.inner_text("#scale-px").split()[0])
            assert 140 < measured_px < 180, f"expected ~160 px, got {measured_px}"

            # the drag alone must change nothing
            assert page.input_value("#mm-per-px") == before
            assert "type the real length" in page.inner_text("#scale-result")

            # now say what it really is
            page.fill("#scale-mm", "80")
            page.dispatch_event("#scale-mm", "input")
            scale = float(page.input_value("#mm-per-px"))

            # A second drag is a measurement, not a re-calibration: the length
            # typed for the first line must not be reapplied to this one.
            page.mouse.move(
                box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3
            )
            page.mouse.down()
            page.mouse.move(
                box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.6, steps=8
            )
            page.mouse.up()
            assert page.input_value("#scale-mm") == "", "the old length carried over"
            assert float(page.input_value("#mm-per-px")) == pytest.approx(scale), (
                "a second drag silently changed the scale"
            )
            assert "at the current scale" in page.inner_text("#scale-result")
        finally:
            browser.close()

    assert scale == pytest.approx(80 / measured_px, rel=1e-3), (
        f"{measured_px} px called 80 mm should give {80 / measured_px} mm/px, got {scale}"
    )
    assert not console_errors, console_errors


def test_the_analysis_range_actually_trims_the_run(live_server, browser_video):
    """Setting start/end must restrict the frames a real run walks.

    The unit tests cover how a range is resolved; this covers the part only a
    browser can answer -- that the resolved range reaches trackAll and the
    timestamps it records stay inside it.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            console_errors = []
            page.on(
                "console",
                lambda m: console_errors.append(m.text) if m.type == "error" else None,
            )
            page.goto(live_server)
            page.set_input_files("#video-file", str(browser_video))
            page.wait_for_function(
                "document.querySelector('#video-info').children.length > 0",
                timeout=20000,
            )

            duration = page.evaluate("document.querySelector('#frame-slider').max")
            duration = float(duration)
            assert duration > 1.0, f"demo clip too short to trim: {duration}"

            page.fill("#trim-start", "0.30")
            page.fill("#trim-end", "0.70")
            page.dispatch_event("#trim-end", "change")
            assert "0.30 s → 0.70 s" in page.inner_text("#range-info")

            # walk the video with the page's own tracker class, as Run would
            stamps = page.evaluate(
                """async () => {
                    const file = document.querySelector('#video-file').files[0];
                    const tracker = new window.VideoTracker(file);
                    await tracker.load();
                    const track = await tracker.trackAll({
                        color: { h_lo: 0, h_hi: 179, s_lo: 0, s_hi: 255,
                                 v_lo: 0, v_hi: 255 },
                        segment: { blur: 0, open_ksize: 0, close_ksize: 0,
                                   min_area: 1, roi: null },
                        ledRoi: null,
                        fps: 30,
                        startTime: 0.3,
                        endTime: 0.7,
                    });
                    tracker.dispose();
                    return track.t;
                }"""
            )
        finally:
            browser.close()

    assert stamps, "the trimmed run recorded no frames at all"
    assert min(stamps) >= 0.3 - 1e-3, f"walked before the start: {min(stamps)}"
    assert max(stamps) <= 0.7 + 0.05, f"walked past the end: {max(stamps)}"
    # and it really is a slice, not the whole clip relabelled
    assert max(stamps) < duration - 0.1, "the trim did not shorten the run"
    assert not console_errors, console_errors


def test_the_led_is_read_from_the_top_of_the_clip_when_trimmed(
    live_server, browser_video, truth
):
    """A trim starting after the LED flash must not cost us the sync.

    The flash sits at the head of a recording, which is exactly what a user
    trims away, so the LED trace is taken from the start of the clip on its
    own timestamps while the magnet is tracked only inside the range.
    """
    start = (truth["led_frame"] + 8) / truth["fps"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(live_server)
            page.set_input_files("#video-file", str(browser_video))
            page.wait_for_function(
                "document.querySelector('#video-info').children.length > 0",
                timeout=20000,
            )
            track = page.evaluate(
                """async ([ledRoi, start]) => {
                    const file = document.querySelector('#video-file').files[0];
                    const tracker = new window.VideoTracker(file);
                    await tracker.load();
                    const out = await tracker.trackAll({
                        color: { h_lo: 170, h_hi: 10, s_lo: 120, s_hi: 255,
                                 v_lo: 80, v_hi: 255 },
                        segment: { blur: 5, open_ksize: 3, close_ksize: 7,
                                   min_area: 40, roi: null },
                        ledRoi,
                        fps: 30,
                        startTime: start,
                        endTime: null,
                    });
                    tracker.dispose();
                    return { t: out.t, led: out.led, led_t: out.led_t };
                }""",
                [truth["led_roi"], start],
            )
        finally:
            browser.close()

    assert len(track["led"]) == len(track["led_t"]), "the LED trace lost its clock"
    # the magnet starts late, but the LED still covers the dark frames before it
    assert min(track["t"]) >= start - 1e-3
    assert min(track["led_t"]) < start, "the LED was trimmed along with the magnet"
    assert min(track["led_t"]) < 0.05, "the LED trace did not start at the clip's top"
    # and the trace really does carry the dark-then-bright step the sync needs
    assert max(track["led"]) - min(track["led"]) > 15, "no LED step to sync on"


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is needed to run the cv.js unit tests"
)
def test_the_cv_js_unit_tests_pass():
    """The pure-JS colour segmentation, checked without a browser at all."""
    here = Path(__file__).parent
    for suite in ("cv.test.mjs", "tracker.test.mjs"):
        result = subprocess.run(
            ["node", str(here / suite)], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr
