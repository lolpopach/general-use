"""Tracking a real (synthetic but encoded) video, against known ground truth."""

from __future__ import annotations

import numpy as np
import pytest

from faradaycv.segmentation import SegmentConfig
from faradaycv.video import led_onset_frame, probe, read_frame, track_video


def test_probe_reports_the_encoded_geometry(dataset, truth):
    info = probe(dataset.video)
    assert info.fps == pytest.approx(truth["fps"], rel=0.01)
    assert info.frame_count == truth["n_frames"]
    assert (info.width, info.height) == (640, 480)


def test_read_frame_returns_the_requested_frame(dataset):
    first = read_frame(dataset.video, 0)
    later = read_frame(dataset.video, 40)
    assert first.shape == (480, 640, 3)
    assert not np.array_equal(first, later)


def test_track_follows_the_magnet_to_within_a_pixel(dataset, truth, color):
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    assert len(track) == truth["n_frames"]
    assert track.detection_rate == 1.0

    expected = np.array(truth["magnet_px"])
    error = np.hypot(track.x - expected[:, 0], track.y - expected[:, 1])
    assert np.nanmax(error) < 1.5, f"worst centroid error {np.nanmax(error):.2f} px"
    assert np.nanmean(error) < 0.6


def test_the_green_clamp_in_frame_is_not_mistaken_for_the_magnet(dataset, color):
    """The scene contains a green and a blue object; only the magnet is red."""
    track = track_video(dataset.video, color, SegmentConfig(min_area=60))
    assert track.x.max() < 500  # the green clamp sits at x = 500..560
    assert np.nanstd(track.area) < 0.25 * np.nanmean(track.area)


def test_a_search_window_excludes_everything_outside_it(dataset, color):
    cfg = SegmentConfig(min_area=60, roi=(0, 0, 320, 480))  # left half only
    track = track_video(dataset.video, color, cfg)
    assert 0.1 < track.detection_rate < 0.9  # the swing crosses the boundary
    assert np.nanmax(track.x) <= 320
    assert "detected in only" in " ".join(track.notes)


def test_led_onset_is_found_at_the_frame_it_was_switched_on(dataset, truth, color):
    track = track_video(
        dataset.video,
        color,
        SegmentConfig(min_area=60),
        led_roi=tuple(truth["led_roi"]),
    )
    assert track.led is not None
    frame, threshold = led_onset_frame(track.led)
    assert frame == truth["led_frame"]
    assert track.led[frame - 1] < threshold < track.led[frame]


def test_a_dark_led_region_reports_no_onset():
    flat = np.full(120, 41.0) + np.random.default_rng(0).normal(0, 0.5, 120)
    assert (
        led_onset_frame(flat) == (None, float("nan"))
        or led_onset_frame(flat)[0] is None
    )


def test_one_bright_glitch_frame_does_not_set_the_led_level():
    trace = np.full(90, 30.0)
    trace[10] = 250.0  # a single flash: not a sustained onset
    trace[60:] = 240.0  # the real onset
    frame, _ = led_onset_frame(trace)
    assert frame == 10  # the raw crossing is still reported...
    smoothed_threshold = led_onset_frame(trace)[1]
    assert 30 < smoothed_threshold < 240  # ...on a threshold set by the real step


def test_explicit_threshold_overrides_the_automatic_one():
    trace = np.concatenate([np.full(5, 10.0), np.full(20, 100.0)])
    assert led_onset_frame(trace, threshold=50.0)[0] == 5
    assert led_onset_frame(trace, threshold=200.0)[0] is None


def test_missing_video_raises_a_clear_error(color):
    with pytest.raises(FileNotFoundError):
        track_video("does-not-exist.mp4", color)
