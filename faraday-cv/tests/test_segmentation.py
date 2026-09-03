"""Colour segmentation: the part everything else is built on."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from faradaycv.segmentation import (
    ColorRange,
    SegmentConfig,
    find_blobs,
    overlay_mask,
    sample_color_range,
    segment,
    select_blob,
)


def scene(bgr=(40, 40, 215), second=None):
    """A grey frame with a disk at (100, 60), optionally a second blob."""
    img = np.full((160, 240, 3), 120, np.uint8)
    cv2.circle(img, (100, 60), 12, bgr, -1)
    if second is not None:
        cv2.circle(img, second, 8, bgr, -1)
    return img


def test_hue_box_without_wrap_matches_only_its_band():
    hsv = np.zeros((1, 3, 3), np.uint8)
    hsv[0, 0] = (30, 200, 200)  # inside
    hsv[0, 1] = (60, 200, 200)  # outside
    hsv[0, 2] = (30, 10, 200)  # right hue, too little saturation
    mask = ColorRange(20, 40, s_lo=100, v_lo=100).mask(hsv)
    assert mask[0, 0] > 0
    assert mask[0, 1] == 0
    assert mask[0, 2] == 0


def test_hue_box_wraps_around_red():
    box = ColorRange(170, 10, s_lo=100, v_lo=100)
    assert box.wraps
    hsv = np.zeros((1, 3, 3), np.uint8)
    hsv[0, 0] = (175, 200, 200)  # just below 180
    hsv[0, 1] = (3, 200, 200)  # just above 0
    hsv[0, 2] = (90, 200, 200)  # cyan: nowhere near
    mask = box.mask(hsv)
    assert mask[0, 0] > 0 and mask[0, 1] > 0 and mask[0, 2] == 0


def test_clamping_keeps_the_box_legal():
    box = ColorRange(-5, 300, s_lo=200, s_hi=100, v_lo=-3, v_hi=999)
    assert (box.h_lo, box.h_hi) == (0, 179)
    assert box.s_lo <= box.s_hi and box.v_lo <= box.v_hi
    assert box.v_hi == 255


def test_parse_roundtrip():
    box = ColorRange.parse("170,10,120,255,80,255")
    assert box.to_dict() == ColorRange(170, 10, 120, 255, 80, 255).to_dict()
    with pytest.raises(ValueError):
        ColorRange.parse("1,2,3")


def test_click_on_the_magnet_yields_a_range_that_finds_it():
    img = scene()
    box = sample_color_range(img, 100, 60)
    mask = segment(img, box, SegmentConfig(min_area=20))
    blobs = find_blobs(mask, 20)
    assert len(blobs) == 1
    assert blobs[0].cx == pytest.approx(100, abs=1.0)
    assert blobs[0].cy == pytest.approx(60, abs=1.0)


def test_click_off_the_frame_is_rejected():
    with pytest.raises(ValueError):
        sample_color_range(scene(), 900, 900)


def test_min_area_drops_speckle():
    img = scene(second=(200, 130))
    box = sample_color_range(img, 100, 60)
    mask = segment(img, box, SegmentConfig(min_area=1))
    assert len(find_blobs(mask, min_area=1)) == 2
    assert len(find_blobs(mask, min_area=300)) == 1  # only the big disk survives


def test_roi_restricts_the_search():
    img = scene(second=(200, 130))
    box = sample_color_range(img, 100, 60)
    cfg = SegmentConfig(min_area=10, roi=(160, 100, 70, 60))
    blobs = find_blobs(segment(img, box, cfg), 10)
    assert len(blobs) == 1
    assert blobs[0].cx == pytest.approx(200, abs=1.5)


def test_select_blob_prefers_continuity_over_size():
    img = scene(second=(200, 130))  # the disk at (100,60) is the larger one
    box = sample_color_range(img, 100, 60)
    blobs = find_blobs(segment(img, box, SegmentConfig(min_area=10)), 10)
    assert select_blob(blobs).cx == pytest.approx(100, abs=1.5)  # largest by default
    near = select_blob(blobs, previous=(198, 128))
    assert near.cx == pytest.approx(200, abs=1.5)


def test_select_blob_rejects_impossible_jumps():
    img = scene()
    box = sample_color_range(img, 100, 60)
    blobs = find_blobs(segment(img, box, SegmentConfig(min_area=10)), 10)
    assert select_blob(blobs, previous=(10, 10), max_jump_px=5) is None
    assert select_blob([], previous=None) is None


def test_overlay_marks_the_centroid_without_touching_the_input():
    img = scene()
    box = sample_color_range(img, 100, 60)
    mask = segment(img, box, SegmentConfig(min_area=10))
    blob = select_blob(find_blobs(mask, 10))
    out = overlay_mask(img, mask, blob)
    assert out.shape == img.shape
    assert not np.array_equal(out, img)
    assert img[60, 100].tolist() == [40, 40, 215]  # original untouched
