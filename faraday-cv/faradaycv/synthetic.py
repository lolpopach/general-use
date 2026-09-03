"""A synthetic pendulum dataset: video + Arduino-style voltage log.

It exists for two reasons.  First, the tests need ground truth -- a track whose
true centroid, true speed and true emf are known to the pixel and the
millivolt.  Second, a teacher can try the whole workflow before setting the
apparatus up, because the generated pair reproduces the paper's central
result: with the coil placed near the turning point, the maximum speed and the
maximum |emf| happen at different times.

Physics: a simple pendulum, and a dipole flux through a coil of radius ``a``,

    Phi(r) = (mu0 * m / 2) * a^2 / (r^2 + a^2)^(3/2),   emf = -N dPhi/dt

with r the magnet-to-coil distance.  That is enough structure for dPhi/dx to
vary sharply with position, which is the whole point of the experiment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

MU0 = 4e-7 * np.pi
G = 9.81


@dataclass
class SyntheticSpec:
    """Everything the generator needs; the defaults mirror the paper's setup."""

    length_m: float = 0.60  # pendulum length
    theta0_rad: float = 0.28  # amplitude
    duration_s: float = 3.0
    fps: float = 30.0
    sample_rate_hz: float = 116.0
    width: int = 640
    height: int = 480
    px_per_m: float = 480.0
    pivot_px: tuple[int, int] = (320, 40)
    magnet_radius_px: int = 11
    magnet_bgr: tuple[int, int, int] = (40, 40, 215)  # red magnet marker
    coil_radius_m: float = 0.045
    coil_at_theta_frac: float = 0.92  # coil sits near the turning point
    coil_offset_m: float = 0.030  # ... this far outside the arc
    turns: int = 7000
    dipole_moment: float = 0.05  # A m^2, sets the emf scale
    led_frame: int = 6  # first frame in which the marker LED is lit
    led_box_px: tuple[int, int, int, int] = (16, 16, 34, 34)  # x, y, w, h
    voltage_offset_mV: float = 1.7  # ADC offset the analysis must remove
    noise_mV: float = 0.05
    pixel_noise: float = 3.0
    distractor: bool = True  # a green clamp in frame, to punish lazy thresholds
    seed: int = 7

    @property
    def period_s(self) -> float:
        return 2.0 * np.pi * np.sqrt(self.length_m / G)


@dataclass
class SyntheticDataset:
    video: Path
    voltage: Path
    truth: Path
    spec: SyntheticSpec
    ground_truth: dict = field(default_factory=dict)


def _theta(spec: SyntheticSpec, t: np.ndarray | float):
    omega = 2.0 * np.pi / spec.period_s
    return spec.theta0_rad * np.cos(omega * np.asarray(t, dtype=float))


def _position_m(spec: SyntheticSpec, t):
    """Magnet position in metres, origin at the pivot, y downward."""
    th = _theta(spec, t)
    return spec.length_m * np.sin(th), spec.length_m * np.cos(th)


def _to_px(spec: SyntheticSpec, x_m, y_m):
    return (
        spec.pivot_px[0] + np.asarray(x_m) * spec.px_per_m,
        spec.pivot_px[1] + np.asarray(y_m) * spec.px_per_m,
    )


def coil_position_m(spec: SyntheticSpec) -> tuple[float, float]:
    """Coil centre: near the turning point, just outside the swing arc."""
    th = spec.theta0_rad * spec.coil_at_theta_frac
    r = spec.length_m + spec.coil_offset_m
    return r * np.sin(th), r * np.cos(th)


def _flux(spec: SyntheticSpec, r: np.ndarray) -> np.ndarray:
    a = spec.coil_radius_m
    return (MU0 * spec.dipole_moment / 2.0) * a**2 / (r**2 + a**2) ** 1.5


def emf_volts(spec: SyntheticSpec, t: np.ndarray) -> np.ndarray:
    """Induced emf, -N dPhi/dt, by central difference on the exact motion."""
    dt = 1e-4
    cx, cy = coil_position_m(spec)

    def flux_at(tt):
        x, y = _position_m(spec, tt)
        r = np.hypot(x - cx, y - cy)
        return _flux(spec, r)

    dphi = (flux_at(t + dt) - flux_at(t - dt)) / (2 * dt)
    return -spec.turns * dphi


def speed_m_s(spec: SyntheticSpec, t: np.ndarray) -> np.ndarray:
    dt = 1e-4
    x1, y1 = _position_m(spec, np.asarray(t) + dt)
    x0, y0 = _position_m(spec, np.asarray(t) - dt)
    return np.hypot(x1 - x0, y1 - y0) / (2 * dt)


def _render_frame(spec: SyntheticSpec, rng, x_px: float, y_px: float, led_on: bool):
    frame = np.full((spec.height, spec.width, 3), 118.0, np.float32)
    frame = np.clip(
        frame + rng.normal(0, spec.pixel_noise, frame.shape), 0, 255
    ).astype(np.uint8)
    # bench and pendulum string, so the frame is not just a blob on grey
    cv2.line(
        frame, (0, spec.height - 40), (spec.width, spec.height - 40), (95, 95, 95), 3
    )
    cv2.line(
        frame,
        spec.pivot_px,
        (int(round(x_px)), int(round(y_px))),
        (150, 150, 150),
        2,
    )
    if spec.distractor:
        cv2.rectangle(frame, (500, 300), (560, 360), (60, 170, 60), -1)  # green clamp
        cv2.circle(frame, (120, 300), 16, (200, 120, 60), -1)  # blue-ish knob

    cx_m, cy_m = coil_position_m(spec)
    coil_px = _to_px(spec, cx_m, cy_m)
    cv2.circle(
        frame,
        (int(round(float(coil_px[0]))), int(round(float(coil_px[1])))),
        int(spec.coil_radius_m * spec.px_per_m),
        (90, 90, 90),
        2,
    )

    cv2.circle(
        frame,
        (int(round(x_px)), int(round(y_px))),
        spec.magnet_radius_px,
        spec.magnet_bgr,
        -1,
    )

    x, y, w, h = spec.led_box_px
    cv2.rectangle(
        frame, (x, y), (x + w, y + h), (235, 245, 255) if led_on else (28, 30, 40), -1
    )
    return frame


def _open_writer(path: Path, spec: SyntheticSpec):
    """mp4v where the build supports it, MJPG/AVI otherwise.

    Neither plays in a browser -- pip's OpenCV builds essentially never carry
    a licensed H.264 encoder -- so this is only ever an intermediate file;
    :func:`make_dataset` transcodes it to H.264 before handing back a path.
    """
    for fourcc, suffix in (("mp4v", ".mp4"), ("MJPG", ".avi")):
        target = path.with_suffix(suffix)
        writer = cv2.VideoWriter(
            str(target),
            cv2.VideoWriter_fourcc(*fourcc),
            spec.fps,
            (spec.width, spec.height),
        )
        if writer.isOpened():
            return writer, target
        writer.release()
    raise RuntimeError("OpenCV has no usable video writer (tried mp4v and MJPG)")


def make_dataset(
    outdir: str | Path, spec: SyntheticSpec | None = None
) -> SyntheticDataset:
    """Write ``pendulum.mp4``, ``voltage.csv`` and ``ground_truth.json``."""
    spec = spec or SyntheticSpec()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(spec.seed)

    n_frames = int(round(spec.duration_s * spec.fps))
    t_frames = np.arange(n_frames) / spec.fps
    x_m, y_m = _position_m(spec, t_frames)
    x_px, y_px = _to_px(spec, x_m, y_m)

    writer, raw_path = _open_writer(outdir / "pendulum_raw", spec)
    try:
        for i in range(n_frames):
            writer.write(
                _render_frame(
                    spec, rng, float(x_px[i]), float(y_px[i]), i >= spec.led_frame
                )
            )
    finally:
        writer.release()

    # Re-encode to H.264 so the same file plays in a browser (the point of a
    # demo dataset) and decodes on any OpenCV build, not just the one that
    # happened to write it.
    from .decode import transcode_to_h264

    video_path = outdir / "pendulum.mp4"
    transcode_to_h264(raw_path, video_path)
    raw_path.unlink(missing_ok=True)

    # The Arduino clock starts when the sketch lights the LED.
    t_led = spec.led_frame / spec.fps
    n_samples = int((spec.duration_s - t_led) * spec.sample_rate_hz)
    t_log = np.arange(n_samples) / spec.sample_rate_hz
    emf = emf_volts(spec, t_log + t_led)
    measured_mV = (
        emf * 1e3 + spec.voltage_offset_mV + rng.normal(0, spec.noise_mV, emf.shape)
    )

    voltage_path = outdir / "voltage.csv"
    with voltage_path.open("w", encoding="utf-8") as fh:
        fh.write(
            "# faraday-cv synthetic log -- ADS1115 @ %.0f SPS\n" % spec.sample_rate_hz
        )
        fh.write("t_ms,voltage_mV\n")
        for tt, vv in zip(t_log, measured_mV):
            fh.write(f"{tt * 1e3:.3f},{vv:.4f}\n")

    # Ground truth, on the LED-synchronised clock (t = 0 at the LED onset).
    fine = np.linspace(0, spec.duration_s - t_led, 20001)
    speeds = speed_m_s(spec, fine + t_led)
    emfs = emf_volts(spec, fine + t_led)
    cx_m, cy_m = coil_position_m(spec)
    coil_px = _to_px(spec, cx_m, cy_m)

    truth = {
        "fps": spec.fps,
        "n_frames": n_frames,
        "led_frame": spec.led_frame,
        "t0_video_s": t_led,
        "mm_per_px": 1000.0 / spec.px_per_m,
        "coil_px": [float(coil_px[0]), float(coil_px[1])],
        "led_roi": list(spec.led_box_px),
        "pivot_px": list(spec.pivot_px),
        "period_s": spec.period_s,
        "magnet_px": [[float(a), float(b)] for a, b in zip(x_px, y_px)],
        "t_max_speed_s": float(fine[int(np.argmax(speeds))]),
        "max_speed_m_s": float(np.max(speeds)),
        "t_max_abs_emf_s": float(fine[int(np.argmax(np.abs(emfs)))]),
        "max_abs_emf_mV": float(np.max(np.abs(emfs)) * 1e3),
        "voltage_offset_mV": spec.voltage_offset_mV,
        "video": video_path.name,
        "voltage": voltage_path.name,
    }
    truth_path = outdir / "ground_truth.json"
    truth_path.write_text(json.dumps(truth, indent=2))

    return SyntheticDataset(
        video=video_path,
        voltage=voltage_path,
        truth=truth_path,
        spec=spec,
        ground_truth=truth,
    )


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "example-data"
    ds = make_dataset(target)
    print(f"video   : {ds.video}")
    print(f"voltage : {ds.voltage}")
    print(f"truth   : {ds.truth}")
