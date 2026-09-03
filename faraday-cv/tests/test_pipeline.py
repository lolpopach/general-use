"""End to end: video + Arduino log in, the paper's figures and numbers out."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from faradaycv.analysis import Calibration
from faradaycv.pipeline import AnalysisConfig, export_results, run_analysis
from faradaycv.segmentation import ColorRange, SegmentConfig

MAGNET = ColorRange(170, 10, 120, 255, 80, 255)  # the red marker on the magnet


@pytest.fixture(scope="module")
def result(dataset, truth):
    cfg = AnalysisConfig(
        video=str(dataset.video),
        voltage=str(dataset.voltage),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        calibration=Calibration(
            mm_per_px=truth["mm_per_px"], coil_px=tuple(truth["coil_px"])
        ),
        led_roi=tuple(truth["led_roi"]),
        title="synthetic pendulum",
    )
    return run_analysis(cfg)


def test_the_led_marker_sets_the_video_zero(result, truth):
    assert result.led_frame == truth["led_frame"]
    assert result.t0_video == pytest.approx(truth["t0_video_s"], abs=1e-6)
    assert result.track.detection_rate == 1.0
    assert not any("LED never crossed" in note for note in result.notes)


def test_the_measured_emf_peak_matches_the_generated_one(result, truth):
    stats = result.stats
    assert stats["t_max_abs_voltage_s"] == pytest.approx(
        truth["t_max_abs_emf_s"], abs=0.02
    )
    assert stats["max_abs_voltage_mV"] == pytest.approx(
        truth["max_abs_emf_mV"], rel=0.03
    )


def test_the_measured_speed_matches_the_generated_motion(result, truth):
    assert result.stats["max_speed_m_s"] == pytest.approx(
        truth["max_speed_m_s"], rel=0.03
    )


def test_the_papers_result_is_reproduced(result):
    """Max speed and max |emf| do not coincide -- the point of the experiment."""
    stats = result.stats
    assert abs(stats["peak_separation_s"]) > 0.1
    # at the emf peak the magnet is moving well below its top speed ...
    assert stats["speed_at_max_voltage_m_s"] < 0.8 * stats["max_speed_m_s"]
    # ... and at top speed the induced voltage is a small fraction of its peak
    assert stats["voltage_at_max_speed_fraction"] < 0.25
    # the emf peak happens near the coil, top speed far from it
    assert stats["distance_at_max_voltage_mm"] < 0.5 * stats["distance_at_max_speed_mm"]


def test_emf_over_v_follows_the_flux_gradient(result):
    """E/v should be large near the coil and unremarkable far from it."""
    synced = result.synced
    near = synced.distance < 0.06
    far = synced.distance > 0.20
    ratio = np.abs(synced.emf_over_v)
    assert np.nanmax(ratio[near]) > 10 * np.nanmax(ratio[far])


def test_export_writes_every_figure_and_table(result, tmp_path):
    written = export_results(result, tmp_path / "out")
    for key in (
        "track_csv",
        "motion_csv",
        "synced_csv",
        "fig_motion_voltage",
        "fig_emf_over_v",
        "fig_diagnostics",
        "summary",
    ):
        path = Path(written[key])
        assert path.exists(), key
        assert path.stat().st_size > 1000, f"{key} looks empty"

    header = Path(written["synced_csv"]).read_text().splitlines()[0]
    assert header.split(",") == [
        "t_s",
        "voltage_V",
        "speed_m_s",
        "distance_m",
        "emf_over_v_Vs_per_m",
    ]
    rows = Path(written["synced_csv"]).read_text().splitlines()[1:]
    assert len(rows) == len(result.synced)

    summary = json.loads(Path(written["summary"]).read_text())
    assert summary["led_frame"] == result.led_frame
    assert summary["stats"]["max_abs_voltage_mV"] == pytest.approx(
        result.stats["max_abs_voltage_mV"]
    )
    assert summary["config"]["calibration"]["coil_px"] is not None


def test_a_manual_t0_overrides_the_led(dataset, truth):
    cfg = AnalysisConfig(
        video=str(dataset.video),
        voltage=str(dataset.voltage),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        calibration=Calibration(mm_per_px=truth["mm_per_px"]),
        led_roi=tuple(truth["led_roi"]),
        t0_video=0.5,
    )
    out = run_analysis(cfg)
    assert out.led_frame == truth["led_frame"]  # still reported ...
    assert out.t0_video == 0.5  # ... but not used


def test_without_an_led_the_run_still_completes_and_says_so(dataset, truth):
    cfg = AnalysisConfig(
        video=str(dataset.video),
        voltage=str(dataset.voltage),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        calibration=Calibration(mm_per_px=truth["mm_per_px"]),
    )
    out = run_analysis(cfg)
    assert out.led_frame is None
    assert out.t0_video == 0.0
    assert any("no LED marker" in note for note in out.notes)
    assert out.stats  # the analysis still runs, just unsynchronised


def test_video_only_runs_need_no_voltage_file(dataset, truth):
    cfg = AnalysisConfig(
        video=str(dataset.video),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        calibration=Calibration(mm_per_px=truth["mm_per_px"]),
    )
    out = run_analysis(cfg)
    assert out.synced is None and out.stats == {}
    written = export_results(out, Path(cfg.video).parent / "video-only")
    assert "synced_csv" not in written
    assert Path(written["motion_csv"]).exists()


def test_glitches_and_unit_guesses_in_the_log_are_reported(dataset, truth, tmp_path):
    """The real-world log quirks must reach the user, not be silently fixed."""
    log = tmp_path / "glitchy.csv"
    rows = ["9999.0,42.0"] + [
        f"{i * 0.01:.2f},{(i % 20 - 10) * 0.03125:.5f}" for i in range(400)
    ]
    log.write_text("\n".join(rows) + "\n")

    cfg = AnalysisConfig(
        video=str(dataset.video),
        voltage=str(log),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        calibration=Calibration(mm_per_px=truth["mm_per_px"]),
        led_roi=tuple(truth["led_roi"]),
    )
    out = run_analysis(cfg)
    assert any("out-of-order timestamps" in note for note in out.notes)
    assert any("read as mV" in note for note in out.notes)


def test_an_led_that_was_already_lit_is_diagnosed_specifically(tmp_path, truth):
    """A student who starts the camera late sees no LED step at all."""
    from faradaycv.synthetic import SyntheticSpec, make_dataset

    ds = make_dataset(tmp_path / "lit", SyntheticSpec(duration_s=1.5, led_frame=0))
    cfg = AnalysisConfig(
        video=str(ds.video),
        color=MAGNET,
        segment=SegmentConfig(min_area=60),
        led_roi=tuple(ds.ground_truth["led_roi"]),
    )
    out = run_analysis(cfg)
    assert out.led_frame is None
    assert any("already" in note for note in out.notes)
