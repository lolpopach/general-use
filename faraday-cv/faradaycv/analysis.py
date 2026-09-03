"""From pixels to physics: calibration, smoothing, synchronisation, E/v.

Two clocks meet here.  The video clock starts at the first frame in which the
marker LED is lit; the Arduino clock starts at the moment the sketch switched
that LED on.  Once both records are shifted onto that shared origin, the
magnet's position and speed can be interpolated onto the (faster) voltage
timestamps, and Eq. (3) of the paper -- E/v proportional to -N dPhi/dx --
becomes a column in a table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

from .track import Track
from .voltage import VoltageLog


@dataclass
class Calibration:
    """Geometry of the frame, filled in by clicking in the UI."""

    mm_per_px: float = 1.0
    coil_px: tuple[float, float] | None = None
    origin_px: tuple[float, float] | None = None
    smooth_window: int = 7  # frames, odd; 0 disables
    smooth_poly: int = 2

    def to_dict(self) -> dict:
        return {
            "mm_per_px": self.mm_per_px,
            "coil_px": list(self.coil_px) if self.coil_px else None,
            "origin_px": list(self.origin_px) if self.origin_px else None,
            "smooth_window": self.smooth_window,
            "smooth_poly": self.smooth_poly,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        def pair(key):
            value = data.get(key)
            return (float(value[0]), float(value[1])) if value else None

        return cls(
            mm_per_px=float(data.get("mm_per_px", 1.0)),
            coil_px=pair("coil_px"),
            origin_px=pair("origin_px"),
            smooth_window=int(data.get("smooth_window", 7)),
            smooth_poly=int(data.get("smooth_poly", 2)),
        )

    @staticmethod
    def scale_from_line(
        p0: tuple[float, float], p1: tuple[float, float], length_mm: float
    ) -> float:
        """mm per pixel from a drawn line of known length."""
        px = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        if px <= 0:
            raise ValueError("calibration line has zero length")
        return float(length_mm) / px


@dataclass
class Motion:
    """The magnet's motion in SI units on the video clock."""

    t: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    speed: np.ndarray  # m/s
    vx: np.ndarray
    vy: np.ndarray
    distance: np.ndarray | None = None  # m, magnet to coil centre
    found: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return int(self.t.size)


def fill_gaps(values: np.ndarray) -> np.ndarray:
    """Linear interpolation across frames where the magnet was not found."""
    out = np.asarray(values, dtype=float).copy()
    good = np.isfinite(out)
    if good.all() or not good.any():
        return out
    idx = np.arange(out.size)
    out[~good] = np.interp(idx[~good], idx[good], out[good])
    return out


def smooth(values: np.ndarray, window: int, poly: int = 2) -> np.ndarray:
    """Savitzky-Golay smoothing, clamped to what the sample count allows."""
    values = np.asarray(values, dtype=float)
    n = values.size
    if window is None or window < 3 or n < 5:
        return values
    win = int(window)
    if win % 2 == 0:
        win += 1
    win = min(win, n if n % 2 == 1 else n - 1)
    if win < 3:
        return values
    order = min(poly, win - 1)
    return savgol_filter(values, win, order)


def build_motion(track: Track, calib: Calibration) -> Motion:
    """Pixels -> metres, gaps filled, positions smoothed, velocity by gradient.

    Differentiating raw centroids amplifies the +-0.5 px quantisation of the
    segmentation, so positions are smoothed *before* the derivative is taken.
    """
    scale = calib.mm_per_px * 1e-3  # metres per pixel
    x_px = smooth(fill_gaps(track.x), calib.smooth_window, calib.smooth_poly)
    y_px = smooth(fill_gaps(track.y), calib.smooth_window, calib.smooth_poly)

    ox, oy = calib.origin_px if calib.origin_px else (0.0, 0.0)
    x_m = (x_px - ox) * scale
    y_m = -(y_px - oy) * scale  # image y grows downward; physics y grows up

    t = np.asarray(track.t, dtype=float)
    if t.size >= 2:
        vx = np.gradient(x_m, t)
        vy = np.gradient(y_m, t)
    else:
        vx = np.zeros_like(x_m)
        vy = np.zeros_like(y_m)
    speed = np.hypot(vx, vy)

    distance = None
    if calib.coil_px is not None:
        cx = (calib.coil_px[0] - ox) * scale
        cy = -(calib.coil_px[1] - oy) * scale
        distance = np.hypot(x_m - cx, y_m - cy)

    motion = Motion(
        t=t,
        x_m=x_m,
        y_m=y_m,
        speed=speed,
        vx=vx,
        vy=vy,
        distance=distance,
        found=np.asarray(track.found, dtype=bool),
        notes=list(track.notes),
    )
    if calib.mm_per_px == 1.0:
        motion.notes.append(
            "no length calibration given -- distances are in pixels, not metres"
        )
    return motion


def shift_motion(motion: Motion, t0: float) -> Motion:
    """Re-zero the video clock at ``t0`` seconds (the LED-onset frame)."""
    return Motion(
        t=motion.t - t0,
        x_m=motion.x_m,
        y_m=motion.y_m,
        speed=motion.speed,
        vx=motion.vx,
        vy=motion.vy,
        distance=motion.distance,
        found=motion.found,
        notes=list(motion.notes),
    )


@dataclass
class Synced:
    """Both records on one time axis (the voltage timestamps)."""

    t: np.ndarray
    voltage: np.ndarray  # V
    speed: np.ndarray  # m/s
    distance: np.ndarray | None  # m
    emf_over_v: np.ndarray  # V / (m/s)
    v_min: float
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return int(self.t.size)


def synchronize(
    motion: Motion,
    log: VoltageLog,
    *,
    t0_video: float = 0.0,
    t0_voltage: float = 0.0,
    v_min: float | None = None,
    v_min_fraction: float = 0.08,
) -> Synced:
    """Align the two records and derive E/v on the shared axis.

    ``t0_video`` is the time of the LED-onset frame in the video's own clock;
    ``t0_voltage`` the corresponding instant in the Arduino log (normally 0,
    since the sketch lights the LED as logging begins).
    """
    m = shift_motion(motion, t0_video)
    v = log.zeroed(t0_voltage)

    lo = max(float(m.t[0]), float(v.t[0]))
    hi = min(float(m.t[-1]), float(v.t[-1]))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        raise ValueError(
            "video and voltage records do not overlap in time "
            f"(video {m.t[0]:.2f}..{m.t[-1]:.2f} s, voltage {v.t[0]:.2f}..{v.t[-1]:.2f} s) "
            "-- check the LED synchronisation"
        )

    sel = (v.t >= lo) & (v.t <= hi)
    t = v.t[sel]
    voltage = v.v[sel]
    speed = np.interp(t, m.t, m.speed)
    distance = np.interp(t, m.t, m.distance) if m.distance is not None else None

    if v_min is None:
        peak = float(np.nanmax(speed)) if speed.size else 0.0
        v_min = v_min_fraction * peak
    ratio = np.full_like(voltage, np.nan)
    fast = speed > v_min
    ratio[fast] = voltage[fast] / speed[fast]

    notes = list(m.notes)
    overlap = hi - lo
    if overlap < 0.5:
        notes.append(f"the two records overlap for only {overlap:.2f} s")
    return Synced(
        t=t,
        voltage=voltage,
        speed=speed,
        distance=distance,
        emf_over_v=ratio,
        v_min=float(v_min),
        notes=notes,
    )


def summarize(synced: Synced, speed_tolerance: float = 0.01) -> dict:
    """The paper's headline numbers: the two peaks and the gap between them.

    A record covering several swings has several near-identical speed maxima,
    and plain ``argmax`` picks between them on noise alone -- which would make
    the peak separation change from run to run.  So the top-speed instant used
    for the comparison is the one *nearest the emf peak* among all samples
    within ``speed_tolerance`` of the maximum speed.
    """
    if len(synced) == 0:
        return {}
    i_volt = int(np.nanargmax(np.abs(synced.voltage)))
    peak_speed = float(np.nanmax(synced.speed))
    near_peak = np.flatnonzero(synced.speed >= (1.0 - speed_tolerance) * peak_speed)
    i_speed = int(near_peak[np.argmin(np.abs(near_peak - i_volt))])
    out = {
        "t_max_speed_s": float(synced.t[i_speed]),
        "max_speed_m_s": float(synced.speed[i_speed]),
        "t_max_abs_voltage_s": float(synced.t[i_volt]),
        "max_abs_voltage_mV": float(abs(synced.voltage[i_volt]) * 1e3),
        "speed_at_max_voltage_m_s": float(synced.speed[i_volt]),
        "voltage_at_max_speed_mV": float(synced.voltage[i_speed] * 1e3),
        "peak_separation_s": float(synced.t[i_volt] - synced.t[i_speed]),
        "samples": len(synced),
        "duration_s": float(synced.t[-1] - synced.t[0]),
    }
    if synced.distance is not None:
        out["distance_at_max_voltage_mm"] = float(synced.distance[i_volt] * 1e3)
        out["distance_at_max_speed_mm"] = float(synced.distance[i_speed] * 1e3)
        out["min_distance_mm"] = float(np.nanmin(synced.distance) * 1e3)
    peak = out["max_abs_voltage_mV"]
    if peak > 0:
        out["voltage_at_max_speed_fraction"] = float(
            abs(out["voltage_at_max_speed_mV"]) / peak
        )
    return out
