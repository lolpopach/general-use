"""The track model: what a measured swing looks like, in pixels and seconds.

Deliberately free of OpenCV, because the server that analyses a track need
not be able to decode video at all -- in the hosted setup the browser does
the decoding and segmentation, and only these numbers cross the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class VideoInfo:
    path: str
    fps: float
    frame_count: int
    width: int
    height: int
    note: str | None = None  # set when the file had to be converted first

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "width": self.width,
            "height": self.height,
            "duration_s": self.frame_count / self.fps if self.fps else 0.0,
            "note": self.note,
        }


@dataclass
class Track:
    """Raw per-frame tracking output, in pixels and video time."""

    frame: np.ndarray
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    area: np.ndarray
    found: np.ndarray
    led: np.ndarray | None = None
    info: VideoInfo | None = None
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return int(self.frame.size)

    @property
    def detection_rate(self) -> float:
        return float(self.found.mean()) if len(self) else 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "Track":
        """Rebuild a track measured elsewhere -- in the browser, typically.

        ``t`` carries each frame's real presentation time in seconds, so a
        variable frame rate stays correct; ``x``/``y`` are pixel centroids with
        null where the magnet was not found.
        """
        t = np.asarray(_floats(data.get("t")), dtype=float)
        if t.size < 2:
            raise ValueError("the track needs at least 2 frames")
        if not np.all(np.diff(t) > 0):
            raise ValueError("track timestamps must increase")
        x = np.asarray(_floats(data.get("x")), dtype=float)
        y = np.asarray(_floats(data.get("y")), dtype=float)
        if x.size != t.size or y.size != t.size:
            raise ValueError("t, x and y must be the same length")
        area = np.asarray(_floats(data.get("area", [])), dtype=float)
        if area.size != t.size:
            area = np.where(np.isfinite(x), 1.0, 0.0)
        found = np.isfinite(x) & np.isfinite(y)
        led = data.get("led")
        info = None
        if data.get("width") and data.get("height"):
            span = float(t[-1] - t[0])
            fps = (t.size - 1) / span if span > 0 else 30.0
            info = VideoInfo(
                path=str(data.get("name", "browser")),
                fps=float(data.get("fps") or fps),
                frame_count=int(t.size),
                width=int(data["width"]),
                height=int(data["height"]),
            )
        track = cls(
            frame=np.asarray(data.get("frame", np.arange(t.size)), dtype=int),
            t=t,
            x=x,
            y=y,
            area=area,
            found=found,
            led=np.asarray(_floats(led), dtype=float) if led else None,
            info=info,
        )
        if track.detection_rate < 0.9:
            track.notes.append(
                f"magnet detected in only {track.detection_rate:.0%} of frames -- "
                "widen the colour range or lower the minimum blob size"
            )
        return track


def _floats(values) -> list[float]:
    """None/null -> NaN, so a missing detection survives the JSON round trip."""
    if values is None:
        return []
    return [float("nan") if v is None else float(v) for v in values]


def led_onset_frame(
    led: np.ndarray,
    threshold: float | None = None,
    min_rise: float = 15.0,
) -> tuple[int | None, float]:
    """First frame in which the marker LED reads as lit.

    With no explicit threshold the trace is split half-way between its dark and
    bright levels, and the split is rejected if those levels differ by less
    than ``min_rise`` grey levels -- which is what a trace with no LED in it
    looks like.  Dark and bright come from the extremes of a 3-frame median of
    the trace, not from percentiles: the LED is typically lit for all but the
    first few frames, so any percentile wide enough to be robust would sit on
    the lit side of the step.
    """
    values = np.asarray(led, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, float("nan")
    if threshold is None:
        smoothed = _median3(finite)
        lo, hi = float(np.min(smoothed)), float(np.max(smoothed))
        if hi - lo < min_rise:
            return None, float("nan")
        threshold = lo + 0.5 * (hi - lo)
    idx = np.flatnonzero(values > threshold)
    if idx.size == 0:
        return None, float(threshold)
    return int(idx[0]), float(threshold)


def _median3(values: np.ndarray) -> np.ndarray:
    """3-point median filter, so one bad frame cannot set the LED levels."""
    if values.size < 3:
        return values
    stacked = np.vstack([values[:-2], values[1:-1], values[2:]])
    inner = np.median(stacked, axis=0)
    return np.concatenate([values[:1], inner, values[-1:]])
