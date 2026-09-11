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
# scipy is imported inside the one function that needs it, not here: it costs
# the better part of a second to load, and on a free-tier host that is time
# every cold start spends before the page can even be served.  Nothing on the
# path from "browser asks for the page" to "page is served" needs it.

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
    win = _odd_window(window, n)
    if win < 3:
        return values
    order = min(poly, win - 1)
    from scipy.signal import savgol_filter

    return savgol_filter(values, win, order)


def derivative(values: np.ndarray, t: np.ndarray, window: int, poly: int = 2):
    """d(values)/dt, fitted rather than differenced.

    ``np.gradient`` divides a two-frame difference by that frame's own dt, so
    it amplifies two things the video cannot help: the pixel quantisation of
    the centroid, and any wobble in the frame timestamps.  Phone video wobbles
    -- the browser reports real presentation times, and a variable frame rate
    means neighbouring frames are genuinely 28 ms and 38 ms apart, which on a
    difference reads as a 30 % change in speed that never happened.  Worse, a
    decoder that hands back two frames a millisecond apart makes the quotient
    explode.

    A Savitzky-Golay derivative fits a short polynomial across the window and
    differentiates that, which has the same bandwidth without the
    amplification.  It needs a uniform grid, so on an uneven clock the
    positions are resampled to the median frame interval, differentiated
    there, and the velocity interpolated back onto the real timestamps.
    """
    values = np.asarray(values, dtype=float)
    t = np.asarray(t, dtype=float)
    if t.size < 5 or window is None or window < 3:
        return np.gradient(values, t) if t.size >= 2 else np.zeros_like(values)

    dt = np.diff(t)
    step = float(np.median(dt))
    if step <= 0:
        return np.gradient(values, t)

    from scipy.signal import savgol_filter

    win = _odd_window(window, t.size)
    if win < 3:
        return np.gradient(values, t)
    order = min(poly, win - 1)

    if np.all(np.abs(dt - step) <= 0.02 * step):  # already an even clock
        return savgol_filter(values, win, order, deriv=1, delta=step)

    grid = np.arange(float(t[0]), float(t[-1]) + 0.5 * step, step)
    if grid.size < win:
        return np.gradient(values, t)
    on_grid = np.interp(grid, t, values)
    return np.interp(t, grid, savgol_filter(on_grid, win, order, deriv=1, delta=step))


def _odd_window(window: int, n: int) -> int:
    """The Savitzky-Golay window, clamped to what the sample count allows."""
    win = int(window)
    if win % 2 == 0:
        win += 1
    win = min(win, n if n % 2 == 1 else n - 1)
    return win


def build_motion(track: Track, calib: Calibration) -> Motion:
    """Pixels -> metres, gaps filled, positions smoothed, velocity fitted.

    Differentiating raw centroids amplifies the +-0.5 px quantisation of the
    segmentation, so positions are smoothed before they are reported, and the
    velocity comes from :func:`derivative` rather than a finite difference.
    """
    scale = calib.mm_per_px * 1e-3  # metres per pixel
    x_filled = fill_gaps(track.x)
    y_filled = fill_gaps(track.y)
    x_px = smooth(x_filled, calib.smooth_window, calib.smooth_poly)
    y_px = smooth(y_filled, calib.smooth_window, calib.smooth_poly)

    ox, oy = calib.origin_px if calib.origin_px else (0.0, 0.0)
    x_m = (x_px - ox) * scale
    y_m = -(y_px - oy) * scale  # image y grows downward; physics y grows up

    t = np.asarray(track.t, dtype=float)
    # The fit below does its own smoothing, so it runs on the filled positions
    # rather than the already-smoothed ones -- smoothing twice would flatten
    # the very peaks the figures are about.
    vx = derivative(x_filled * scale, t, calib.smooth_window, calib.smooth_poly)
    vy = derivative(-y_filled * scale, t, calib.smooth_window, calib.smooth_poly)
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
    else:
        motion.notes.extend(_scale_sanity(track, calib.mm_per_px))
    spread = _clock_spread(t)
    if spread > 0.25:
        motion.notes.append(
            f"the video's frame times are uneven -- the gaps between frames vary by "
            f"{spread:.0%} about the median. The speed was fitted on an even clock so "
            "that does not wreck it, but a steadier recording would measure it better"
        )
    return motion


#: A benchtop pendulum filmed on a desk: anything outside this is a typo, not
#: an experiment.  Generous on purpose -- it is a smell test, not a rule.
_PLAUSIBLE_FRAME_M = (0.03, 3.0)


def _scale_sanity(track: Track, mm_per_px: float) -> list[str]:
    """Complain if the scale implies a frame no tabletop experiment could fill.

    A mistyped length is the one calibration error that produces no visible
    symptom: every distance and speed comes out wrong by the same factor, the
    curves keep their shape, and the figure looks perfectly healthy.  The
    frame width, though, is something the student can check by eye.
    """
    if track.info is None or not track.info.width:
        return []
    frame_m = track.info.width * mm_per_px * 1e-3
    lo, hi = _PLAUSIBLE_FRAME_M
    if lo <= frame_m <= hi:
        return []
    return [
        f"the length scale ({mm_per_px:.4g} mm/px) says the video frame is "
        f"{frame_m:.3g} m wide. Check the measured line and the length typed for "
        "it -- every distance and speed is off by the same factor if it is wrong"
    ]


def _clock_spread(t: np.ndarray) -> float:
    """Worst frame-interval deviation from the median, as a fraction of it."""
    if t.size < 3:
        return 0.0
    dt = np.diff(t)
    step = float(np.median(dt))
    return float(np.max(np.abs(dt - step)) / step) if step > 0 else 0.0


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
    #: True where the speed was below ``v_min`` and the floor stood in for it,
    #: so ``emf_over_v`` there is E/v_min, not E/v.  The speed panel keeps the
    #: real speed; only this derived ratio needs the floor to stay finite.
    clamped: np.ndarray | None = None
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

    # E/v is exact wherever the magnet is moving; it only misbehaves as v -> 0
    # at the turning points, where the ratio runs away.  Rather than drop those
    # samples and leave the curve full of holes, hold the *denominator* at a
    # floor so the trace stays continuous and bounded.  The floor is recorded
    # in `clamped` because the values under it are E/v_min, not E/v.
    clamped = speed < v_min if v_min > 0 else np.zeros(speed.shape, bool)
    if v_min > 0:
        ratio = voltage / np.maximum(speed, v_min)
    else:
        # no floor asked for: the only thing that cannot be divided is zero
        ratio = np.full_like(voltage, np.nan)
        moving = speed > 0
        ratio[moving] = voltage[moving] / speed[moving]

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
        clamped=clamped,
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
