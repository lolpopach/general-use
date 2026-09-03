"""Calibration, smoothing, synchronisation and E/v."""

from __future__ import annotations

import numpy as np
import pytest

from faradaycv.analysis import (
    Calibration,
    build_motion,
    fill_gaps,
    shift_motion,
    smooth,
    summarize,
    synchronize,
)
from faradaycv.segmentation import SegmentConfig
from faradaycv.synthetic import speed_m_s
from faradaycv.video import track_video
from faradaycv.voltage import VoltageLog, load_voltage_csv


def test_fill_gaps_interpolates_only_the_holes():
    values = np.array([0.0, np.nan, 2.0, np.nan, np.nan, 5.0])
    out = fill_gaps(values)
    assert list(out) == pytest.approx([0, 1, 2, 3, 4, 5])
    assert list(fill_gaps(np.array([np.nan, np.nan]))) != [0, 0]  # nothing to do


def test_smooth_shortens_the_window_when_there_is_little_data():
    values = np.array([1.0, 5.0, 1.0, 5.0, 1.0])
    assert smooth(values, window=101).shape == values.shape
    assert smooth(values, window=0) is values
    assert np.std(smooth(values, window=5)) < np.std(values)


def test_scale_from_a_drawn_line():
    assert Calibration.scale_from_line((0, 0), (100, 0), 250.0) == pytest.approx(2.5)
    assert Calibration.scale_from_line((0, 0), (30, 40), 100.0) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        Calibration.scale_from_line((5, 5), (5, 5), 10.0)


def test_speed_from_the_video_matches_the_true_pendulum_speed(dataset, truth, color):
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    calib = Calibration(mm_per_px=truth["mm_per_px"], coil_px=tuple(truth["coil_px"]))
    motion = build_motion(track, calib)

    expected = speed_m_s(dataset.spec, track.t)
    inner = slice(4, -4)  # the gradient at the very ends is one-sided
    error = np.abs(motion.speed[inner] - expected[inner])
    assert np.max(error) < 0.05, f"worst speed error {np.max(error):.4f} m/s"
    assert np.max(motion.speed) == pytest.approx(truth["max_speed_m_s"], rel=0.03)


def test_distance_to_the_coil_is_measured_in_metres(dataset, truth, color):
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    motion = build_motion(
        track,
        Calibration(mm_per_px=truth["mm_per_px"], coil_px=tuple(truth["coil_px"])),
    )
    assert motion.distance is not None
    # The coil sits 30 mm outside the arc, near the turning point.
    assert np.min(motion.distance) == pytest.approx(0.030, abs=0.004)
    assert np.max(motion.distance) < 0.4


def test_without_calibration_the_units_are_flagged(dataset, color):
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    motion = build_motion(track, Calibration())
    assert any("not metres" in note for note in motion.notes)
    assert motion.distance is None


def test_shift_moves_the_clock_without_touching_the_data():
    motion = build_motion(_fake_track(), Calibration(mm_per_px=1.0, smooth_window=0))
    shifted = shift_motion(motion, 0.2)
    assert shifted.t[0] == pytest.approx(motion.t[0] - 0.2)
    assert list(shifted.speed) == pytest.approx(list(motion.speed))


def test_synchronize_puts_the_records_on_the_voltage_timestamps(dataset, truth, color):
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    motion = build_motion(
        track,
        Calibration(mm_per_px=truth["mm_per_px"], coil_px=tuple(truth["coil_px"])),
    )
    log = load_voltage_csv(dataset.voltage).baseline_corrected(0.2)
    synced = synchronize(motion, log, t0_video=truth["t0_video_s"])

    assert len(synced) > 300
    assert synced.t[0] >= 0
    assert np.median(np.diff(synced.t)) == pytest.approx(1 / 116.0, rel=0.02)
    # the emf peak lands where the generator says it does
    stats = summarize(synced)
    assert stats["t_max_abs_voltage_s"] == pytest.approx(
        truth["t_max_abs_emf_s"], abs=0.02
    )


def test_synchronize_refuses_records_that_do_not_overlap():
    motion = build_motion(_fake_track(), Calibration())
    log = VoltageLog(t=np.linspace(50, 60, 100), v=np.zeros(100))
    with pytest.raises(ValueError, match="do not overlap"):
        synchronize(motion, log)


def test_emf_over_v_is_hidden_where_the_magnet_is_nearly_stopped():
    motion = build_motion(_fake_track(), Calibration(mm_per_px=1000.0, smooth_window=0))
    t = np.linspace(0, 0.9, 200)
    log = VoltageLog(t=t, v=np.full_like(t, 0.01))
    synced = synchronize(motion, log, v_min=None, v_min_fraction=0.5)

    slow = synced.speed <= synced.v_min
    assert slow.any() and np.isnan(synced.emf_over_v[slow]).all()
    fast = synced.speed > synced.v_min
    assert np.allclose(synced.emf_over_v[fast], 0.01 / synced.speed[fast])


def _fake_track():
    """A one-second track moving at a varying, known speed."""
    from faradaycv.video import Track, VideoInfo

    t = np.arange(31) / 30.0
    x = np.sin(2 * np.pi * t)  # pixels
    y = np.zeros_like(x)
    return Track(
        frame=np.arange(31),
        t=t,
        x=x,
        y=y,
        area=np.full(31, 100.0),
        found=np.ones(31, bool),
        info=VideoInfo("fake", 30.0, 31, 640, 480),
    )
