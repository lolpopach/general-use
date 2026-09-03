"""HSV colour segmentation: the core of the magnet tracker.

Everything downstream (position, velocity, the E/v plot) depends on one
question being answered well per frame: *which pixels are the magnet?*  We
answer it with a hue/saturation/value box, because that is what a student can
pick by clicking on the magnet and nudging three sliders.

OpenCV hue is 0..179, saturation/value 0..255.  A hue box may wrap around the
red end of the circle, which is exactly where most lab magnets are marked, so
wrap-around is handled explicitly rather than left to the user.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

H_MAX = 179
SV_MAX = 255


def _clamp(value: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(value))))


@dataclass(frozen=True)
class ColorRange:
    """An HSV box.  ``h_lo > h_hi`` means the box wraps past red."""

    h_lo: int
    h_hi: int
    s_lo: int = 80
    s_hi: int = SV_MAX
    v_lo: int = 60
    v_hi: int = SV_MAX

    def __post_init__(self) -> None:
        object.__setattr__(self, "h_lo", _clamp(self.h_lo, 0, H_MAX))
        object.__setattr__(self, "h_hi", _clamp(self.h_hi, 0, H_MAX))
        for name in ("s_lo", "s_hi", "v_lo", "v_hi"):
            object.__setattr__(self, name, _clamp(getattr(self, name), 0, SV_MAX))
        if self.s_lo > self.s_hi:
            object.__setattr__(self, "s_lo", self.s_hi)
        if self.v_lo > self.v_hi:
            object.__setattr__(self, "v_lo", self.v_hi)

    @property
    def wraps(self) -> bool:
        return self.h_lo > self.h_hi

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ColorRange":
        fields = ("h_lo", "h_hi", "s_lo", "s_hi", "v_lo", "v_hi")
        return cls(**{k: int(data[k]) for k in fields if k in data})

    @classmethod
    def parse(cls, text: str) -> "ColorRange":
        """Parse ``h_lo,h_hi,s_lo,s_hi,v_lo,v_hi`` (as used on the CLI)."""
        parts = [p.strip() for p in text.replace(":", ",").split(",") if p.strip()]
        if len(parts) != 6:
            raise ValueError(
                "expected 6 comma-separated numbers: h_lo,h_hi,s_lo,s_hi,v_lo,v_hi"
            )
        return cls(*[int(float(p)) for p in parts])

    def mask(self, hsv: np.ndarray) -> np.ndarray:
        """Binary mask (0/255) of the pixels inside this box.

        Needs OpenCV, imported here rather than at module level so that the
        rest of this module -- ``ColorRange``, ``SegmentConfig``, parsing --
        stays usable on a server with no OpenCV installed (the browser does
        the actual segmentation there; the server never calls this method).
        """
        import cv2

        lo_sv = (self.s_lo, self.v_lo)
        hi_sv = (self.s_hi, self.v_hi)
        if not self.wraps:
            return cv2.inRange(
                hsv,
                np.array((self.h_lo, *lo_sv), np.uint8),
                np.array((self.h_hi, *hi_sv), np.uint8),
            )
        lower = cv2.inRange(
            hsv,
            np.array((0, *lo_sv), np.uint8),
            np.array((self.h_hi, *hi_sv), np.uint8),
        )
        upper = cv2.inRange(
            hsv,
            np.array((self.h_lo, *lo_sv), np.uint8),
            np.array((H_MAX, *hi_sv), np.uint8),
        )
        return cv2.bitwise_or(lower, upper)


@dataclass(frozen=True)
class Blob:
    cx: float
    cy: float
    area: int
    bbox: tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True)
class SegmentConfig:
    """Knobs the UI exposes next to the colour sliders."""

    blur: int = 5
    open_ksize: int = 3
    close_ksize: int = 7
    min_area: int = 40
    roi: tuple[int, int, int, int] | None = None  # x, y, w, h

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SegmentConfig":
        roi = data.get("roi")
        return cls(
            blur=int(data.get("blur", 5)),
            open_ksize=int(data.get("open_ksize", 3)),
            close_ksize=int(data.get("close_ksize", 7)),
            min_area=int(data.get("min_area", 40)),
            roi=tuple(int(v) for v in roi) if roi else None,
        )


def to_hsv(frame_bgr: np.ndarray, blur: int = 5) -> np.ndarray:
    """Blur (odd kernel, 0 disables) then convert to HSV."""
    import cv2

    work = frame_bgr
    if blur and blur >= 3:
        k = blur if blur % 2 == 1 else blur + 1
        work = cv2.GaussianBlur(work, (k, k), 0)
    return cv2.cvtColor(work, cv2.COLOR_BGR2HSV)


def _apply_roi(mask: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    if roi is None:
        return mask
    import cv2

    x, y, w, h = (int(v) for v in roi)
    keep = np.zeros_like(mask)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(mask.shape[1], x + w), min(mask.shape[0], y + h)
    if x1 > x0 and y1 > y0:
        keep[y0:y1, x0:x1] = 255
    return cv2.bitwise_and(mask, keep)


def segment(
    frame_bgr: np.ndarray,
    color: ColorRange,
    cfg: SegmentConfig | None = None,
) -> np.ndarray:
    """Colour-segment one frame and clean the mask up morphologically."""
    cfg = cfg or SegmentConfig()
    hsv = to_hsv(frame_bgr, cfg.blur)
    mask = color.mask(hsv)
    return clean_mask(mask, cfg)


def clean_mask(mask: np.ndarray, cfg: SegmentConfig) -> np.ndarray:
    """Opening removes speckle, closing fills the specular highlight."""
    import cv2

    if cfg.open_ksize >= 2:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (cfg.open_ksize, cfg.open_ksize)
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    if cfg.close_ksize >= 2:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (cfg.close_ksize, cfg.close_ksize)
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return _apply_roi(mask, cfg.roi)


def find_blobs(mask: np.ndarray, min_area: int = 40) -> list[Blob]:
    """Connected components above ``min_area``, largest first."""
    import cv2

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8
    )
    blobs: list[Blob] = []
    for i in range(1, count):  # 0 is the background
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        blobs.append(
            Blob(
                cx=float(centroids[i][0]),
                cy=float(centroids[i][1]),
                area=area,
                bbox=(
                    int(stats[i, cv2.CC_STAT_LEFT]),
                    int(stats[i, cv2.CC_STAT_TOP]),
                    int(stats[i, cv2.CC_STAT_WIDTH]),
                    int(stats[i, cv2.CC_STAT_HEIGHT]),
                ),
            )
        )
    blobs.sort(key=lambda b: b.area, reverse=True)
    return blobs


def select_blob(
    blobs: Iterable[Blob],
    previous: tuple[float, float] | None = None,
    max_jump_px: float | None = None,
) -> Blob | None:
    """Pick the magnet: nearest to where it was last frame, else the largest.

    Continuity matters more than size once the track is running -- a reflection
    on the coil can briefly outgrow the magnet, but it will not be where the
    magnet was 33 ms ago.
    """
    blobs = list(blobs)
    if not blobs:
        return None
    if previous is None:
        return blobs[0]
    px, py = previous
    scored = sorted(blobs, key=lambda b: (b.cx - px) ** 2 + (b.cy - py) ** 2)
    best = scored[0]
    if max_jump_px is not None:
        dist = float(np.hypot(best.cx - px, best.cy - py))
        if dist > max_jump_px:
            return None
    return best


def _circular_hue_median(hues: np.ndarray) -> float:
    """Median hue on a circle: average unit vectors at 2x the OpenCV angle."""
    ang = hues.astype(np.float64) * (2.0 * np.pi / (H_MAX + 1))
    mean = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
    if mean < 0:
        mean += 2.0 * np.pi
    return float(mean * (H_MAX + 1) / (2.0 * np.pi))


def sample_color_range(
    frame_bgr: np.ndarray,
    x: int,
    y: int,
    radius: int = 6,
    h_tol: int = 10,
    s_tol: int = 70,
    v_tol: int = 80,
    blur: int = 5,
) -> ColorRange:
    """Suggest a colour box from a click on the magnet.

    Hue gets a tight tolerance around the circular median (that is what
    identifies the magnet); saturation and value get loose ones (they swing
    with the lab lighting and with the shadow on the far side of the swing).
    """
    hsv = to_hsv(frame_bgr, blur)  # imports cv2 itself
    h, w = hsv.shape[:2]
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"click ({x}, {y}) is outside the {w}x{h} frame")
    patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
    hue = _circular_hue_median(patch[:, 0])
    sat = float(np.median(patch[:, 1]))
    val = float(np.median(patch[:, 2]))
    h_lo = int(round(hue - h_tol)) % (H_MAX + 1)
    h_hi = int(round(hue + h_tol)) % (H_MAX + 1)
    return ColorRange(
        h_lo=h_lo,
        h_hi=h_hi,
        s_lo=_clamp(sat - s_tol, 30, SV_MAX),
        s_hi=SV_MAX,
        v_lo=_clamp(val - v_tol, 30, SV_MAX),
        v_hi=SV_MAX,
    )


def overlay_mask(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    blob: Blob | None = None,
    color: tuple[int, int, int] = (0, 255, 0),
    alpha: float = 0.45,
) -> np.ndarray:
    """Tint the segmented pixels and mark the tracked centroid (for preview)."""
    import cv2

    out = frame_bgr.copy()
    tint = np.zeros_like(out)
    tint[:] = color
    sel = mask > 0
    out[sel] = cv2.addWeighted(out, 1 - alpha, tint, alpha, 0)[sel]
    contours, _ = cv2.findContours(
        (mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(out, contours, -1, (255, 255, 255), 1)
    if blob is not None:
        c = (int(round(blob.cx)), int(round(blob.cy)))
        cv2.drawMarker(out, c, (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
    return out
