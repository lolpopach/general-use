"""The no-code path: upload, click, upload the log separately, run."""

from __future__ import annotations

import io
import json
import time

import pytest

from faradaycv.webapp import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(workdir=tmp_path / "work")
    app.config.update(TESTING=True)
    return app.test_client()


def upload(client, path, endpoint="/api/video", **form):
    data = {"file": (io.BytesIO(path.read_bytes()), path.name), **form}
    return client.post(endpoint, data=data, content_type="multipart/form-data")


def test_the_page_loads(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"faraday-cv" in page.data
    assert client.get("/static/app.js").status_code == 200


def test_video_upload_reports_the_geometry(client, dataset, truth):
    out = upload(client, dataset.video).get_json()
    assert out["video"]["frame_count"] == truth["n_frames"]
    assert out["video"]["fps"] == pytest.approx(truth["fps"], rel=0.01)
    assert out["state"] == "idle"


def test_a_non_video_upload_is_refused(client, dataset):
    res = upload(client, dataset.voltage)  # a .csv where a video belongs
    assert res.status_code == 400
    assert "unsupported video type" in res.get_json()["error"]


def test_unknown_sessions_are_404(client):
    assert client.get("/api/session/nope").status_code == 404


def test_click_picks_a_colour_and_the_preview_finds_the_magnet(client, dataset, truth):
    sid = upload(client, dataset.video).get_json()["session"]
    x, y = truth["magnet_px"][0]

    picked = client.post(
        f"/api/session/{sid}/pick",
        json={"index": 0, "x": int(x), "y": int(y)},
    ).get_json()["color"]
    assert picked["h_lo"] > picked["h_hi"]  # a red magnet wraps the hue circle

    stats = client.post(
        f"/api/session/{sid}/preview",
        json={"index": 0, "color": picked, "segment": {"min_area": 60}, "stats": True},
    ).get_json()
    assert stats["blobs"] == 1
    assert stats["centroid"][0] == pytest.approx(x, abs=1.5)
    assert stats["centroid"][1] == pytest.approx(y, abs=1.5)

    image = client.post(
        f"/api/session/{sid}/preview",
        json={"index": 0, "color": picked, "segment": {"min_area": 60}},
    )
    assert image.headers["Content-Type"] == "image/jpeg"
    assert len(image.data) > 2000

    frame = client.get(f"/api/session/{sid}/frame?index=10")
    assert frame.headers["Content-Type"] == "image/jpeg"


def test_the_full_run_produces_figures_and_tables(client, dataset, truth):
    sid = upload(client, dataset.video).get_json()["session"]
    voltage = upload(
        client,
        dataset.voltage,
        endpoint=f"/api/session/{sid}/voltage",
        voltage_unit="auto",
    ).get_json()
    assert voltage["voltage"]["sample_rate_hz"] == pytest.approx(116, rel=0.02)

    started = client.post(
        f"/api/session/{sid}/run",
        json={
            "color": {
                "h_lo": 170,
                "h_hi": 10,
                "s_lo": 120,
                "s_hi": 255,
                "v_lo": 80,
                "v_hi": 255,
            },
            "segment": {"min_area": 60},
            "calibration": {
                "mm_per_px": truth["mm_per_px"],
                "coil_px": truth["coil_px"],
                "smooth_window": 7,
            },
            "led_roi": truth["led_roi"],
            "baseline_seconds": 0.2,
            "title": "web run",
        },
    )
    assert started.status_code == 200

    state = _wait(client, sid)
    assert state["state"] == "done", state["message"]
    result = state["result"]
    assert result["led_frame"] == truth["led_frame"]
    assert result["detection_rate"] == 1.0
    assert result["stats"]["max_abs_voltage_mV"] == pytest.approx(
        truth["max_abs_emf_mV"], rel=0.03
    )

    figure = client.get(f"/api/session/{sid}/file/fig2_motion_and_voltage.png")
    assert figure.status_code == 200 and len(figure.data) > 10_000
    table = client.get(f"/api/session/{sid}/file/synced.csv")
    assert table.status_code == 200 and table.data.count(b"\n") > 100
    summary = json.loads(client.get(f"/api/session/{sid}/file/summary.json").data)
    assert summary["t0_video_s"] == pytest.approx(truth["t0_video_s"])

    assert client.get(f"/api/session/{sid}/file/../../etc/passwd").status_code in (
        400,
        404,
    )


def test_a_scale_line_sets_the_calibration(client, dataset):
    sid = upload(client, dataset.video).get_json()["session"]
    upload(client, dataset.voltage, endpoint=f"/api/session/{sid}/voltage")
    client.post(
        f"/api/session/{sid}/run",
        json={
            "color": {
                "h_lo": 170,
                "h_hi": 10,
                "s_lo": 120,
                "s_hi": 255,
                "v_lo": 80,
                "v_hi": 255,
            },
            "segment": {"min_area": 60},
            "calibration": {
                "scale_line": {"x0": 0, "y0": 0, "x1": 100, "y1": 0, "length_mm": 250}
            },
        },
    )
    state = _wait(client, sid)
    assert state["state"] == "done", state["message"]
    summary = json.loads(client.get(f"/api/session/{sid}/file/summary.json").data)
    assert summary["config"]["calibration"]["mm_per_px"] == pytest.approx(2.5)


def test_a_bad_voltage_file_is_reported_not_swallowed(client, dataset, tmp_path):
    sid = upload(client, dataset.video).get_json()["session"]
    junk = tmp_path / "junk.csv"
    junk.write_text("# nothing but a comment\n")
    res = upload(client, junk, endpoint=f"/api/session/{sid}/voltage")
    assert res.status_code == 400
    assert "cannot read that voltage log" in res.get_json()["error"]


def test_a_run_that_cannot_synchronise_reports_the_error(client, dataset, truth):
    sid = upload(client, dataset.video).get_json()["session"]
    upload(client, dataset.voltage, endpoint=f"/api/session/{sid}/voltage")
    client.post(
        f"/api/session/{sid}/run",
        json={
            "color": {
                "h_lo": 170,
                "h_hi": 10,
                "s_lo": 120,
                "s_hi": 255,
                "v_lo": 80,
                "v_hi": 255,
            },
            "segment": {"min_area": 60},
            "t0_video": 500.0,  # nonsense offset: the records cannot overlap
        },
    )
    state = _wait(client, sid)
    assert state["state"] == "error"
    assert "do not overlap" in state["message"]


def _wait(client, sid, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/session/{sid}").get_json()
        if state["state"] != "running":
            return state
        time.sleep(0.1)
    raise AssertionError("the analysis did not finish in time")


def test_a_cut_short_upload_is_named_as_such(client, dataset):
    """A part-arrived file must not be reported as an unsupported codec."""
    data = {
        "file": (io.BytesIO(dataset.video.read_bytes()), "swing.mp4"),
        "size": str(dataset.video.stat().st_size + 5_000_000),  # browser saw more
    }
    res = client.post("/api/video", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    error = res.get_json()["error"]
    assert "cut short" in error
    assert "by path" in error  # offers the way around a huge upload


def test_a_matching_size_passes_the_integrity_check(client, dataset, truth):
    data = {
        "file": (io.BytesIO(dataset.video.read_bytes()), "swing.mp4"),
        "size": str(dataset.video.stat().st_size),
    }
    out = client.post(
        "/api/video", data=data, content_type="multipart/form-data"
    ).get_json()
    assert out["video"]["frame_count"] == truth["n_frames"]


def test_a_local_file_can_be_opened_by_path_without_uploading(client, dataset, truth):
    out = client.post("/api/video/path", json={"path": str(dataset.video)}).get_json()
    assert out["video"]["frame_count"] == truth["n_frames"]
    sid = out["session"]
    # the session works exactly like an uploaded one
    stats = client.post(
        f"/api/session/{sid}/preview",
        json={
            "index": 0,
            "color": {
                "h_lo": 170,
                "h_hi": 10,
                "s_lo": 120,
                "s_hi": 255,
                "v_lo": 80,
                "v_hi": 255,
            },
            "segment": {"min_area": 60},
            "stats": True,
        },
    ).get_json()
    assert stats["blobs"] == 1


def test_opening_by_path_rejects_what_it_should(client, dataset, tmp_path):
    for payload, expected in [
        ({"path": ""}, "no path"),
        ({"path": "swing.mp4"}, "full path"),
        ({"path": str(tmp_path / "ghost.mp4")}, "no such file"),
        ({"path": str(dataset.voltage)}, "unsupported video type"),
    ]:
        res = client.post("/api/video/path", json=payload)
        assert res.status_code == 400, payload
        assert expected in res.get_json()["error"]


def test_a_quoted_path_pasted_from_finder_still_works(client, dataset):
    """Dragging a file into a terminal or field often brings quotes with it."""
    out = client.post("/api/video/path", json={"path": f"'{dataset.video}'"}).get_json()
    assert "session" in out
