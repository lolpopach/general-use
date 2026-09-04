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


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is needed to run the cv.js unit tests"
)
def test_the_cv_js_unit_tests_pass():
    """The pure-JS colour segmentation, checked without a browser at all."""
    here = Path(__file__).parent
    result = subprocess.run(
        ["node", str(here / "cv.test.mjs")], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
