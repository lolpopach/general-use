"""One call from (video + Arduino log) to figures, tables and a summary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .analysis import Calibration, Motion, Synced, build_motion, summarize, synchronize
from .plots import (
    figure_diagnostics,
    figure_emf_over_velocity,
    figure_motion_and_voltage,
    needs_cjk_font,
    save_figure,
)
from .segmentation import ColorRange, SegmentConfig
from .video import Track, led_onset_frame, track_video
from .voltage import VoltageLog, load_voltage_csv


@dataclass
class AnalysisConfig:
    video: str
    voltage: str | None = None
    color: ColorRange = ColorRange(0, 10)
    segment: SegmentConfig = field(default_factory=SegmentConfig)
    calibration: Calibration = field(default_factory=Calibration)
    led_roi: tuple[int, int, int, int] | None = None
    led_threshold: float | None = None
    t0_video: float | None = None  # overrides the LED onset when set
    t0_voltage: float = 0.0
    voltage_unit: str = "auto"
    baseline_seconds: float = 0.2
    v_min: float | None = None
    fps_override: float | None = None
    max_jump_px: float | None = None
    start_frame: int = 0
    end_frame: int | None = None
    title: str | None = None

    def to_dict(self) -> dict:
        return {
            "video": self.video,
            "voltage": self.voltage,
            "color": self.color.to_dict(),
            "segment": self.segment.to_dict(),
            "calibration": self.calibration.to_dict(),
            "led_roi": list(self.led_roi) if self.led_roi else None,
            "led_threshold": self.led_threshold,
            "t0_video": self.t0_video,
            "t0_voltage": self.t0_voltage,
            "voltage_unit": self.voltage_unit,
            "baseline_seconds": self.baseline_seconds,
            "v_min": self.v_min,
            "fps_override": self.fps_override,
            "max_jump_px": self.max_jump_px,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisConfig":
        led_roi = data.get("led_roi")
        return cls(
            video=data["video"],
            voltage=data.get("voltage"),
            color=ColorRange.from_dict(data.get("color", {"h_lo": 0, "h_hi": 10})),
            segment=SegmentConfig.from_dict(data.get("segment", {})),
            calibration=Calibration.from_dict(data.get("calibration", {})),
            led_roi=tuple(int(v) for v in led_roi) if led_roi else None,
            led_threshold=data.get("led_threshold"),
            t0_video=data.get("t0_video"),
            t0_voltage=float(data.get("t0_voltage", 0.0)),
            voltage_unit=data.get("voltage_unit", "auto"),
            baseline_seconds=float(data.get("baseline_seconds", 0.2)),
            v_min=data.get("v_min"),
            fps_override=data.get("fps_override"),
            max_jump_px=data.get("max_jump_px"),
            start_frame=int(data.get("start_frame", 0)),
            end_frame=data.get("end_frame"),
            title=data.get("title"),
        )


@dataclass
class AnalysisResult:
    config: AnalysisConfig
    track: Track
    motion: Motion
    log: VoltageLog | None = None
    synced: Synced | None = None
    stats: dict = field(default_factory=dict)
    led_frame: int | None = None
    led_threshold: float | None = None
    t0_video: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video": self.track.info.to_dict() if self.track.info else {},
            "frames_analyzed": len(self.track),
            "detection_rate": self.track.detection_rate,
            "led_frame": self.led_frame,
            "led_threshold": self.led_threshold,
            "t0_video_s": self.t0_video,
            "voltage": self.log.to_dict() if self.log else None,
            "stats": self.stats,
            "notes": self.notes,
            "config": self.config.to_dict(),
        }


def run_analysis(
    cfg: AnalysisConfig,
    progress: Callable[[int, int], None] | None = None,
) -> AnalysisResult:
    """Track the magnet, read the log, synchronise, and derive E/v."""
    track = track_video(
        cfg.video,
        cfg.color,
        cfg.segment,
        led_roi=cfg.led_roi,
        fps_override=cfg.fps_override,
        max_jump_px=cfg.max_jump_px,
        start_frame=cfg.start_frame,
        end_frame=cfg.end_frame,
        progress=progress,
    )
    motion = build_motion(track, cfg.calibration)
    notes = list(track.notes)

    led_frame: int | None = None
    led_threshold: float | None = None
    if track.led is not None:
        led_frame, led_threshold = led_onset_frame(track.led, cfg.led_threshold)
        if led_frame is None:
            level = float(np.nanmean(track.led))
            if level > 150:
                notes.append(
                    "the LED region is bright in every frame -- the LED was already "
                    "lit when recording started, so start the video first, or set "
                    "the video t=0 by hand"
                )
            else:
                notes.append(
                    "the LED never crossed the on-threshold -- check that the LED "
                    "region covers the LED, or set the video t=0 by hand"
                )

    fps = track.info.fps if track.info else 30.0
    if cfg.t0_video is not None:
        t0_video = float(cfg.t0_video)
    elif led_frame is not None:
        t0_video = (cfg.start_frame + led_frame) / fps
    else:
        t0_video = 0.0
        if cfg.led_roi is None:
            notes.append(
                "no LED marker and no manual t=0: the video clock starts at its "
                "first analysed frame"
            )

    if needs_cjk_font(cfg.title):
        notes.append(
            "the figure title uses characters no installed font can draw -- install "
            "a Korean font (NanumGothic, Noto Sans KR) or use a Latin title"
        )

    result = AnalysisResult(
        config=cfg,
        track=track,
        motion=motion,
        led_frame=led_frame,
        led_threshold=led_threshold,
        t0_video=t0_video,
        notes=notes,
    )

    if cfg.voltage:
        log = load_voltage_csv(cfg.voltage, voltage_unit=cfg.voltage_unit)
        dropped = int(log.meta.get("out_of_order_rows", 0))
        if dropped:
            result.notes.append(
                f"{dropped} row(s) of the voltage log had out-of-order timestamps "
                "and were dropped"
            )
        unit = str(log.meta.get("voltage_unit", ""))
        if "guessed" in unit:
            result.notes.append(
                f"the voltage column had no unit in its header; it was read as {unit} "
                "-- set the unit explicitly if that is wrong"
            )
        if cfg.baseline_seconds > 0:
            log = log.baseline_corrected(cfg.baseline_seconds)
        result.log = log
        result.synced = synchronize(
            motion,
            log,
            t0_video=t0_video,
            t0_voltage=cfg.t0_voltage,
            v_min=cfg.v_min,
        )
        result.notes.extend(n for n in result.synced.notes if n not in result.notes)
        result.stats = summarize(result.synced)
    return result


def export_results(result: AnalysisResult, outdir: str | Path) -> dict[str, str]:
    """Write CSVs, figures and summary.json; return the files by short name."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    track_csv = outdir / "track.csv"
    _write_csv(
        track_csv,
        ["frame", "t_video_s", "x_px", "y_px", "area_px", "found"],
        [
            result.track.frame,
            result.track.t,
            result.track.x,
            result.track.y,
            result.track.area,
            result.track.found.astype(int),
        ],
    )
    written["track_csv"] = str(track_csv)

    motion_csv = outdir / "motion.csv"
    m = result.motion
    cols = [m.t - result.t0_video, m.x_m, m.y_m, m.speed]
    names = ["t_s", "x_m", "y_m", "speed_m_s"]
    if m.distance is not None:
        names.append("distance_m")
        cols.append(m.distance)
    _write_csv(motion_csv, names, cols)
    written["motion_csv"] = str(motion_csv)

    if result.synced is not None:
        s = result.synced
        names = ["t_s", "voltage_V", "speed_m_s", "emf_over_v_Vs_per_m"]
        cols = [s.t, s.voltage, s.speed, s.emf_over_v]
        if s.distance is not None:
            names.insert(3, "distance_m")
            cols.insert(3, s.distance)
        synced_csv = outdir / "synced.csv"
        _write_csv(synced_csv, names, cols)
        written["synced_csv"] = str(synced_csv)

        written["fig_motion_voltage"] = str(
            save_figure(
                figure_motion_and_voltage(s, title=result.config.title),
                outdir / "fig2_motion_and_voltage.png",
            )
        )
        written["fig_emf_over_v"] = str(
            save_figure(
                figure_emf_over_velocity(s),
                outdir / "fig3_emf_over_velocity.png",
            )
        )

    written["fig_diagnostics"] = str(
        save_figure(
            figure_diagnostics(result.track, result.led_threshold),
            outdir / "diagnostics.png",
        )
    )

    summary = outdir / "summary.json"
    summary.write_text(json.dumps(result.to_dict(), indent=2, default=_jsonable))
    written["summary"] = str(summary)
    return written


def _jsonable(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON serialisable: {type(obj)!r}")


def _write_csv(path: Path, names: list[str], columns: list[np.ndarray]) -> None:
    data = np.column_stack([np.asarray(c, dtype=float) for c in columns])
    with path.open("w", encoding="utf-8") as fh:
        fh.write(",".join(names) + "\n")
        for row in data:
            fh.write(",".join("" if not np.isfinite(v) else f"{v:.6g}" for v in row))
            fh.write("\n")
