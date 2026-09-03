"""Command line front end.

    python -m faradaycv frame  swing.mp4 --out frame0.png
    python -m faradaycv pick   swing.mp4 --at 320,180
    python -m faradaycv track  swing.mp4 --hsv 0,10,120,255,80,255 -o track.csv
    python -m faradaycv analyze swing.mp4 --voltage log.csv --hsv ... -o out/
    python -m faradaycv serve

The web UI (``serve``) is the no-code path described in the paper; these
subcommands are the same pipeline for scripting and for batch re-runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from .analysis import Calibration
from .pipeline import AnalysisConfig, export_results, run_analysis
from .segmentation import (
    ColorRange,
    SegmentConfig,
    find_blobs,
    overlay_mask,
    sample_color_range,
    segment,
    select_blob,
)
from .video import probe, read_frame


def _pair(text: str) -> tuple[float, float]:
    parts = [p for p in text.replace(":", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected 'x,y', got {text!r}")
    return float(parts[0]), float(parts[1])


def _rect(text: str) -> tuple[int, int, int, int]:
    parts = [p for p in text.replace(":", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"expected 'x,y,w,h', got {text!r}")
    return tuple(int(float(p)) for p in parts)  # type: ignore[return-value]


def _add_segmentation_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--hsv",
        type=ColorRange.parse,
        required=True,
        help="colour range h_lo,h_hi,s_lo,s_hi,v_lo,v_hi (OpenCV HSV, hue 0-179)",
    )
    p.add_argument("--blur", type=int, default=5, help="Gaussian blur kernel (odd)")
    p.add_argument("--open", dest="open_ksize", type=int, default=3)
    p.add_argument("--close", dest="close_ksize", type=int, default=7)
    p.add_argument("--min-area", type=int, default=40, help="smallest blob in pixels")
    p.add_argument("--roi", type=_rect, default=None, help="search window x,y,w,h")
    p.add_argument(
        "--max-jump",
        type=float,
        default=None,
        help="reject a detection that moved more than this many pixels in one frame",
    )
    p.add_argument("--fps", type=float, default=None, help="override the video fps")
    p.add_argument("--start-frame", type=int, default=0)
    p.add_argument("--end-frame", type=int, default=None)


def _segment_config(args) -> SegmentConfig:
    return SegmentConfig(
        blur=args.blur,
        open_ksize=args.open_ksize,
        close_ksize=args.close_ksize,
        min_area=args.min_area,
        roi=args.roi,
    )


def cmd_info(args) -> int:
    print(json.dumps(probe(args.video).to_dict(), indent=2))
    return 0


def cmd_frame(args) -> int:
    frame = read_frame(args.video, args.index)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame)
    print(f"wrote {out} ({frame.shape[1]}x{frame.shape[0]})")
    return 0


def cmd_doctor(args) -> int:
    """Say why a video will not open, and what to do about it."""
    from .decode import diagnose

    report = diagnose(args.video)
    print(report.to_text())
    return 0 if (report.opencv_ok or report.ffmpeg_ok) else 1


def cmd_pick(args) -> int:
    frame = read_frame(args.video, args.index)
    x, y = (int(v) for v in args.at)
    color = sample_color_range(
        frame,
        x,
        y,
        radius=args.radius,
        h_tol=args.h_tol,
        s_tol=args.s_tol,
        v_tol=args.v_tol,
    )
    mask = segment(frame, color, SegmentConfig(min_area=args.min_area))
    blobs = find_blobs(mask, args.min_area)
    d = color.to_dict()
    print(
        json.dumps(
            {
                "hsv": d,
                "cli": "{h_lo},{h_hi},{s_lo},{s_hi},{v_lo},{v_hi}".format(**d),
                "blobs": len(blobs),
                "largest_blob": (
                    {"cx": blobs[0].cx, "cy": blobs[0].cy, "area": blobs[0].area}
                    if blobs
                    else None
                ),
                "mask_coverage": float((mask > 0).mean()),
            },
            indent=2,
        )
    )
    if args.preview:
        best = select_blob(blobs)
        cv2.imwrite(str(args.preview), overlay_mask(frame, mask, best))
        print(f"wrote {args.preview}")
    return 0


def cmd_track(args) -> int:
    cfg = AnalysisConfig(
        video=args.video,
        color=args.hsv,
        segment=_segment_config(args),
        calibration=Calibration(
            mm_per_px=args.mm_per_px,
            coil_px=args.coil,
            smooth_window=args.smooth,
        ),
        led_roi=args.led_roi,
        fps_override=args.fps,
        max_jump_px=args.max_jump,
        start_frame=args.start_frame,
        end_frame=args.end_frame,
    )
    result = run_analysis(cfg, progress=_progress)
    track = result.track
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("frame,t_video_s,x_px,y_px,area_px,found\n")
        for i in range(len(track)):
            x = "" if not np.isfinite(track.x[i]) else f"{track.x[i]:.3f}"
            y = "" if not np.isfinite(track.y[i]) else f"{track.y[i]:.3f}"
            fh.write(
                f"{track.frame[i]},{track.t[i]:.6f},{x},{y},"
                f"{track.area[i]:.0f},{int(track.found[i])}\n"
            )
    print(
        f"tracked {len(track)} frames, detected in {track.detection_rate:.1%}; wrote {out}"
    )
    if result.led_frame is not None:
        print(f"LED lit at frame {result.led_frame} (t0 = {result.t0_video:.3f} s)")
    for note in result.notes:
        print(f"note: {note}", file=sys.stderr)
    return 0


def cmd_analyze(args) -> int:
    calib = Calibration(
        mm_per_px=args.mm_per_px,
        coil_px=args.coil,
        origin_px=args.origin,
        smooth_window=args.smooth,
    )
    if args.scale_line and args.scale_length:
        p0 = (args.scale_line[0], args.scale_line[1])
        p1 = (args.scale_line[2], args.scale_line[3])
        calib.mm_per_px = Calibration.scale_from_line(p0, p1, args.scale_length)

    cfg = AnalysisConfig(
        video=args.video,
        voltage=args.voltage,
        color=args.hsv,
        segment=_segment_config(args),
        calibration=calib,
        led_roi=args.led_roi,
        led_threshold=args.led_threshold,
        t0_video=args.t0_video,
        t0_voltage=args.t0_voltage,
        voltage_unit=args.voltage_unit,
        baseline_seconds=args.baseline,
        v_min=args.v_min,
        fps_override=args.fps,
        max_jump_px=args.max_jump,
        start_frame=args.start_frame,
        end_frame=args.end_frame,
        title=args.title,
    )
    result = run_analysis(cfg, progress=_progress)
    written = export_results(result, args.out)

    print(
        f"frames analysed : {len(result.track)} ({result.track.detection_rate:.1%} detected)"
    )
    if result.led_frame is not None:
        print(
            f"LED onset       : frame {result.led_frame} -> t0 = {result.t0_video:.3f} s"
        )
    if result.log is not None:
        print(
            f"voltage log     : {len(result.log)} samples at "
            f"{result.log.sample_rate:.1f} Hz ({result.log.meta.get('voltage_unit')})"
        )
    if result.stats:
        s = result.stats
        print(
            f"max speed       : {s['max_speed_m_s']:.3f} m/s at t = {s['t_max_speed_s']:.3f} s\n"
            f"max |emf|       : {s['max_abs_voltage_mV']:.2f} mV at t = "
            f"{s['t_max_abs_voltage_s']:.3f} s\n"
            f"peak separation : {s['peak_separation_s']:+.3f} s "
            f"(speed at the emf peak: {s['speed_at_max_voltage_m_s']:.3f} m/s)"
        )
    for note in result.notes:
        print(f"note: {note}", file=sys.stderr)
    print("\nwrote:")
    for key, path in written.items():
        print(f"  {key:20s} {path}")
    return 0


def cmd_serve(args) -> int:
    from .webapp import create_app

    app = create_app(workdir=args.workdir, local_mode=not args.public)
    print(f"faraday-cv UI on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def _progress(done: int, total: int) -> None:
    if total:
        pct = 100.0 * done / max(total, 1)
        print(
            f"\rtracking {done}/{total} frames ({pct:4.1f}%)", end="", file=sys.stderr
        )
        if done + 25 >= total:
            print("", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="faradaycv",
        description="Colour-segmentation video analysis for the Faraday's law pendulum lab",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="print fps, frame count and size")
    p_info.add_argument("video")
    p_info.set_defaults(func=cmd_info)

    p_doctor = sub.add_parser("doctor", help="diagnose a video that will not open")
    p_doctor.add_argument("video")
    p_doctor.set_defaults(func=cmd_doctor)

    p_frame = sub.add_parser("frame", help="save one frame as an image")
    p_frame.add_argument("video")
    p_frame.add_argument("--index", type=int, default=0)
    p_frame.add_argument("--out", default="frame.png")
    p_frame.set_defaults(func=cmd_frame)

    p_pick = sub.add_parser(
        "pick", help="suggest an HSV range from a point on the magnet"
    )
    p_pick.add_argument("video")
    p_pick.add_argument(
        "--at", type=_pair, required=True, help="pixel x,y on the magnet"
    )
    p_pick.add_argument("--index", type=int, default=0, help="frame to sample")
    p_pick.add_argument("--radius", type=int, default=6)
    p_pick.add_argument("--h-tol", type=int, default=10)
    p_pick.add_argument("--s-tol", type=int, default=70)
    p_pick.add_argument("--v-tol", type=int, default=80)
    p_pick.add_argument("--min-area", type=int, default=40)
    p_pick.add_argument("--preview", default=None, help="write a mask overlay here")
    p_pick.set_defaults(func=cmd_pick)

    p_track = sub.add_parser("track", help="write the per-frame centroid track")
    p_track.add_argument("video")
    _add_segmentation_args(p_track)
    p_track.add_argument(
        "--led-roi", type=_rect, default=None, help="LED window x,y,w,h"
    )
    p_track.add_argument("--mm-per-px", type=float, default=1.0)
    p_track.add_argument(
        "--coil", type=_pair, default=None, help="coil centre in pixels"
    )
    p_track.add_argument("--smooth", type=int, default=7, help="Savitzky-Golay window")
    p_track.add_argument("-o", "--out", default="track.csv")
    p_track.set_defaults(func=cmd_track)

    p_an = sub.add_parser("analyze", help="full run: figures, tables and summary")
    p_an.add_argument("video")
    _add_segmentation_args(p_an)
    p_an.add_argument("--voltage", required=True, help="Arduino CSV log")
    p_an.add_argument("--voltage-unit", choices=["auto", "V", "mV"], default="auto")
    p_an.add_argument(
        "--baseline", type=float, default=0.2, help="seconds used for zeroing"
    )
    p_an.add_argument("--led-roi", type=_rect, default=None, help="LED window x,y,w,h")
    p_an.add_argument("--led-threshold", type=float, default=None)
    p_an.add_argument(
        "--t0-video", type=float, default=None, help="manual video t=0 (s)"
    )
    p_an.add_argument("--t0-voltage", type=float, default=0.0)
    p_an.add_argument("--mm-per-px", type=float, default=1.0)
    p_an.add_argument(
        "--scale-line",
        type=lambda s: tuple(float(v) for v in s.split(",")),
        default=None,
        help="x0,y0,x1,y1 of a line of known length",
    )
    p_an.add_argument(
        "--scale-length", type=float, default=None, help="its length in mm"
    )
    p_an.add_argument("--coil", type=_pair, default=None, help="coil centre in pixels")
    p_an.add_argument(
        "--origin", type=_pair, default=None, help="pixel origin of the axes"
    )
    p_an.add_argument("--smooth", type=int, default=7)
    p_an.add_argument(
        "--v-min", type=float, default=None, help="hide E/v below this speed"
    )
    p_an.add_argument("--title", default=None)
    p_an.add_argument("-o", "--out", default="out")
    p_an.set_defaults(func=cmd_analyze)

    p_serve = sub.add_parser("serve", help="run the no-code web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--workdir", default=None, help="where uploads and results go")
    p_serve.add_argument(
        "--public",
        action="store_true",
        help="serving to other machines: disables opening videos by local path",
    )
    p_serve.add_argument("--debug", action="store_true")
    p_serve.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
