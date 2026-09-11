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


def test_emf_over_v_holds_the_denominator_at_a_floor_near_the_turning_points():
    """E/v runs away as v -> 0, so v is floored rather than the sample dropped.

    The floor keeps the curve continuous and bounded; it is only the ratio that
    needs it. The speed itself is left alone, because a pendulum really does
    stop at its turning points and the speed plot should say so.
    """
    motion = build_motion(_fake_track(), Calibration(mm_per_px=1000.0, smooth_window=0))
    t = np.linspace(0, 0.9, 200)
    log = VoltageLog(t=t, v=np.full_like(t, 0.01))
    synced = synchronize(motion, log, v_min=None, v_min_fraction=0.5)

    slow = synced.speed < synced.v_min
    assert slow.any(), "the fixture should dip below the floor somewhere"
    assert np.isfinite(synced.emf_over_v).all(), "no holes left in the curve"
    assert np.array_equal(synced.clamped, slow)

    # below the floor the ratio saturates at E/v_min ...
    assert np.allclose(synced.emf_over_v[slow], 0.01 / synced.v_min)
    # ... and above it the value is exact
    fast = ~slow
    assert np.allclose(synced.emf_over_v[fast], 0.01 / synced.speed[fast])
    # the floor bounds the whole trace, which is the point of having one
    assert np.abs(synced.emf_over_v).max() == pytest.approx(0.01 / synced.v_min)

    # and the speed itself is untouched -- it still reaches its true minimum
    assert synced.speed.min() < synced.v_min


def test_asking_for_no_floor_keeps_the_exact_ratio_and_divides_nothing_by_zero():
    motion = build_motion(_fake_track(), Calibration(mm_per_px=1000.0, smooth_window=0))
    t = np.linspace(0, 0.9, 200)
    log = VoltageLog(t=t, v=np.full_like(t, 0.01))
    synced = synchronize(motion, log, v_min=0.0)

    assert not synced.clamped.any()
    moving = synced.speed > 0
    assert np.allclose(synced.emf_over_v[moving], 0.01 / synced.speed[moving])
    assert np.isnan(synced.emf_over_v[~moving]).all()


def _fake_track():
    """A one-second track moving at a varying, known speed."""
    from faradaycv.video import Track

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
        info=None,  # a track from somewhere that never reported the geometry
    )


def _wobbly_clock(n=240, jitter=0.30, seed=3):
    """Frame times of a variable-frame-rate phone clip: the nominal interval,
    wobbling by ``jitter``, with one pair of near-duplicate frames."""
    rng = np.random.default_rng(seed)
    step = 1 / 30.0
    t = np.cumsum(np.r_[0.0, rng.normal(step, jitter * step, n - 1)])
    t[n // 2] = t[n // 2 - 1] + 0.001  # a decoder handing back a repeat
    return np.maximum.accumulate(t) + np.arange(n) * 1e-7


def _swinging_track(t):
    """x = 0.5 sin(2 pi t) metres, sampled at the times given."""
    from faradaycv.video import Track, VideoInfo

    return Track(
        frame=np.arange(t.size),
        t=t,
        x=0.5 * np.sin(2 * np.pi * t) * 1000,  # mm, so mm_per_px=1 gives metres
        y=np.zeros_like(t),
        area=np.full(t.size, 100.0),
        found=np.ones(t.size, bool),
        info=VideoInfo("swing", 30.0, t.size, 640, 480),
    )


def test_speed_survives_a_video_whose_frame_times_wobble():
    """A phone clip's frames are not evenly spaced, and a two-frame difference
    divided by that frame's own dt turns the wobble into speed that was never
    there -- a 1 ms gap between two frames sends it to infinity.

    What is measured here is the *extra* error the wobble causes: a short
    fitting window costs a few percent on a sinusoid whatever the clock does,
    and the uneven clock must not add meaningfully to that.
    """
    calib = Calibration(mm_per_px=1.0, smooth_window=7)
    inner = slice(6, -6)  # the fit is one-sided at the very ends

    def error(t):
        truth = np.pi * np.abs(np.cos(2 * np.pi * t))
        speed = build_motion(_swinging_track(t), calib).speed
        return float(np.max(np.abs(speed[inner] - truth[inner]))), speed

    even, _ = error(np.arange(240) / 30.0)
    wobbly, speed = error(_wobbly_clock())

    assert wobbly < even + 0.05, (
        f"the uneven clock added {wobbly - even:.3f} m/s of error "
        f"(even clock {even:.3f}, wobbly {wobbly:.3f})"
    )
    # and no spike: a 1 ms gap must not blow the quotient up
    assert speed.max() < 1.3 * np.pi, f"peak speed {speed.max():.2f} m/s is a spike"
    assert any(
        "frame times are uneven" in note
        for note in build_motion(_swinging_track(_wobbly_clock()), calib).notes
    )


def test_an_even_clock_is_not_reported_as_uneven():
    from faradaycv.video import Track, VideoInfo

    t = np.arange(200) / 30.0
    track = Track(
        frame=np.arange(t.size),
        t=t,
        x=np.sin(2 * np.pi * t) * 1000,
        y=np.zeros_like(t),
        area=np.full(t.size, 100.0),
        found=np.ones(t.size, bool),
        info=VideoInfo("even", 30.0, t.size, 640, 480),
    )
    motion = build_motion(track, Calibration(mm_per_px=1.0, smooth_window=7))
    assert not any("uneven" in note for note in motion.notes)


def test_pixel_jitter_does_not_reach_the_speed_as_a_ripple():
    """Centroids land on a fraction of a pixel; differencing them frame to
    frame turns that into a visible sawtooth on the speed curve."""
    from faradaycv.video import Track, VideoInfo

    rng = np.random.default_rng(4)
    t = np.arange(300) / 30.0
    clean = 0.5 * np.sin(2 * np.pi * t) * 1000
    common = dict(
        frame=np.arange(t.size),
        y=np.zeros_like(t),
        area=np.full(t.size, 100.0),
        found=np.ones(t.size, bool),
        info=VideoInfo("jittery", 30.0, t.size, 640, 480),
    )
    calib = Calibration(mm_per_px=1.0, smooth_window=7)
    smoothness = []
    for noise in (0.0, 2.0):
        track = Track(t=t, x=clean + rng.normal(0, noise, t.size), **common)
        speed = build_motion(track, calib).speed
        smoothness.append(float(np.mean(np.abs(np.diff(speed, 2)))))
    quiet, noisy = smoothness
    assert noisy < quiet + 0.02, f"2 px of jitter added {noisy - quiet:.3f} of wiggle"


@pytest.mark.parametrize(
    "mm_per_px, flagged",
    [
        (0.4717, False),  # 1920 px of a 91 cm scene -- the real calibration
        (4.32, True),  # the same drag with a length ~9x too large: 8.3 m frame
        (0.005, True),  # microscope territory: a 1 cm frame
        (1.5, False),  # a 2.9 m frame is wide but not absurd
    ],
)
def test_a_scale_that_implies_an_impossible_frame_is_called_out(mm_per_px, flagged):
    """A mistyped length is the one calibration error with no visible symptom:
    every distance and speed is wrong by the same factor, so the curves keep
    their shape and the figure looks healthy.  The frame width is the number
    that gives it away."""
    from faradaycv.video import Track, VideoInfo

    t = np.arange(60) / 30.0
    track = Track(
        frame=np.arange(t.size),
        t=t,
        x=900 + 300 * np.sin(2 * np.pi * t),
        y=np.full(t.size, 640.0),
        area=np.full(t.size, 1800.0),
        found=np.ones(t.size, bool),
        info=VideoInfo("clip", 30.0, t.size, 1920, 1080),
    )
    notes = build_motion(track, Calibration(mm_per_px=mm_per_px)).notes
    said = [n for n in notes if "frame is" in n]
    assert bool(said) == flagged, notes
    if flagged:
        assert "off by the same factor" in said[0]


def test_the_scale_check_stays_quiet_when_the_frame_size_is_unknown():
    """A track measured somewhere that never reported the video geometry must
    not be accused of a bad scale."""
    motion = build_motion(_fake_track(), Calibration(mm_per_px=4.32))
    assert not any("frame is" in note for note in motion.notes)
