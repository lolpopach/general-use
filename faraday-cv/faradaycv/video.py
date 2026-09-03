"""Decoding video with OpenCV: the local half of the tracker.

The video is decoded exactly once.  Every frame yields two things: the
centroid of the colour blob (the magnet) and the mean brightness inside the
LED region of interest (the sync marker the Arduino lights up at t = 0).

The browser does the same job in ``static/tracker.js`` when faraday-cv is
used as a hosted service; both produce the :class:`~faradaycv.track.Track`
defined next door.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .decode import VideoOpenError, readable_video, try_open
from .track import Track, VideoInfo, led_onset_frame
from .segmentation import (
    Blob,
    ColorRange,
    SegmentConfig,
    clean_mask,
    find_blobs,
    select_blob,
    to_hsv,
)


def open_video(path: str | Path) -> tuple[cv2.VideoCapture, VideoInfo]:
    """Open a video, converting it first if OpenCV cannot decode it as it is."""
    source, note = readable_video(path)
    cap, _backend = try_open(source)
    if cap is None:  # readable_video already proved it opens; be defensive
        raise VideoOpenError(f"cannot open video: {path}")
    path = str(source)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if not np.isfinite(fps) or fps <= 1e-3:
        fps = 30.0
    info = VideoInfo(
        path=path,
        fps=fps,
        frame_count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        note=note,
    )
    return cap, info


def probe(path: str | Path) -> VideoInfo:
    cap, info = open_video(path)
    cap.release()
    return info


def read_frame(path: str | Path, index: int = 0) -> np.ndarray:
    """Grab a single frame (for the colour picker / preview)."""
    cap, _info = open_video(path)
    try:
        if index > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"cannot read frame {index}")
        return frame
    finally:
        cap.release()


def track_video(
    path: str | Path,
    color: ColorRange,
    cfg: SegmentConfig | None = None,
    *,
    led_roi: tuple[int, int, int, int] | None = None,
    fps_override: float | None = None,
    max_jump_px: float | None = None,
    start_frame: int = 0,
    end_frame: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Track:
    """Decode the video once, returning the magnet track and the LED trace."""
    cfg = cfg or SegmentConfig()
    cap, info = open_video(path)
    if fps_override:
        info.fps = float(fps_override)

    frames: list[int] = []
    ts: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    areas: list[float] = []
    found: list[bool] = []
    led: list[float] = []

    previous: tuple[float, float] | None = None
    idx = start_frame
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_frame))
    total = info.frame_count or 0

    try:
        while True:
            if end_frame is not None and idx > end_frame:
                break
            ok, frame = cap.read()
            if not ok:
                break

            hsv = to_hsv(frame, cfg.blur)
            mask = clean_mask(color.mask(hsv), cfg)
            blob: Blob | None = select_blob(
                find_blobs(mask, cfg.min_area), previous, max_jump_px
            )

            frames.append(idx)
            ts.append(idx / info.fps)
            if blob is None:
                xs.append(np.nan)
                ys.append(np.nan)
                areas.append(0.0)
                found.append(False)
            else:
                xs.append(blob.cx)
                ys.append(blob.cy)
                areas.append(float(blob.area))
                found.append(True)
                previous = (blob.cx, blob.cy)

            led.append(_led_level(hsv, led_roi) if led_roi else np.nan)

            if progress and total and idx % 25 == 0:
                progress(idx - start_frame, total - start_frame)
            idx += 1
    finally:
        cap.release()

    if not frames:
        raise ValueError(f"no frames decoded from {path}")

    track = Track(
        frame=np.asarray(frames, dtype=int),
        t=np.asarray(ts, dtype=float),
        x=np.asarray(xs, dtype=float),
        y=np.asarray(ys, dtype=float),
        area=np.asarray(areas, dtype=float),
        found=np.asarray(found, dtype=bool),
        led=np.asarray(led, dtype=float) if led_roi else None,
        info=info,
    )
    if track.detection_rate < 0.9:
        track.notes.append(
            f"magnet detected in only {track.detection_rate:.0%} of frames -- "
            "widen the colour range or lower min_area"
        )
    return track


def _led_level(hsv: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    x, y, w, h = (int(v) for v in roi)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(hsv.shape[1], x + w), min(hsv.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return float("nan")
    return float(hsv[y0:y1, x0:x1, 2].mean())  # V channel = brightness


__all__ = [
    "Track",
    "VideoInfo",
    "led_onset_frame",
    "open_video",
    "probe",
    "read_frame",
    "track_video",
]
