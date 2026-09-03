"""The no-code web UI.

Upload the swing video, click the magnet to pick its colour, click the coil,
drag the LED box, upload the Arduino log *separately*, press run.  Out come
the two figures and the CSV tables.

It is a local single-user tool: sessions are directories under a work folder,
and one background thread runs the analysis while the page polls for status.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

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

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg"}
RESULT_FILES = {
    "track.csv",
    "motion.csv",
    "synced.csv",
    "summary.json",
    "fig2_motion_and_voltage.png",
    "fig3_emf_over_velocity.png",
    "diagnostics.png",
}


@dataclass
class Session:
    sid: str
    root: Path
    video: Path | None = None
    voltage: Path | None = None
    info: dict = field(default_factory=dict)
    voltage_info: dict = field(default_factory=dict)
    state: str = "idle"  # idle | running | done | error
    progress: float = 0.0
    message: str = ""
    result: dict = field(default_factory=dict)

    @property
    def outdir(self) -> Path:
        return self.root / "out"

    def public(self) -> dict:
        return {
            "session": self.sid,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "video": self.info,
            "voltage": self.voltage_info,
            "result": self.result,
        }


def create_app(
    workdir: str | Path | None = None,
    local_mode: bool | None = None,
) -> Flask:
    """Build the app.

    ``local_mode`` enables conveniences that are only safe when the server and
    the browser are the same machine -- above all opening a video by its path
    on disk.  Served to anyone else, that endpoint would read arbitrary files,
    so it is refused unless local mode is on.  It defaults to on, and to off
    when FARADAYCV_LOCAL_MODE is set to 0/false/no.
    """
    if local_mode is None:
        env = os.environ.get("FARADAYCV_LOCAL_MODE", "1").strip().lower()
        local_mode = env not in {"0", "false", "no", "off"}
    base = Path(workdir) if workdir else Path(tempfile.gettempdir()) / "faraday-cv"
    base.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent.parent

    app = Flask(
        __name__,
        static_folder=str(here / "static"),
        template_folder=str(here / "templates"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024**3  # 2 GB videos are plausible
    sessions: dict[str, Session] = {}
    lock = threading.Lock()

    def get_session(sid: str) -> Session:
        with lock:
            session = sessions.get(sid)
        if session is None:
            raise KeyError(sid)
        return session

    @app.errorhandler(KeyError)
    def _unknown_session(exc):  # pragma: no cover - trivial
        return jsonify({"error": f"unknown session {exc}"}), 404

    @app.errorhandler(ValueError)
    def _bad_request(exc):
        return jsonify({"error": str(exc)}), 400

    @app.get("/")
    def index():
        return send_from_directory(str(here / "templates"), "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):  # pragma: no cover - served by Flask in practice
        return send_from_directory(str(here / "static"), name)

    # ---------------------------------------------------------------- uploads

    @app.post("/api/video")
    def upload_video():
        file = request.files.get("file")
        if file is None or not file.filename:
            raise ValueError("no video file in the request")
        suffix = Path(file.filename).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise ValueError(
                f"unsupported video type {suffix!r}; use one of "
                + ", ".join(sorted(VIDEO_SUFFIXES))
            )
        sid = uuid.uuid4().hex[:12]
        root = base / sid
        root.mkdir(parents=True, exist_ok=True)
        target = root / secure_filename(file.filename)
        file.save(target)

        # A large upload that stops early leaves a plausible-looking file whose
        # video index is missing.  The browser tells us how big it should be, so
        # say "the upload was cut short" instead of "this codec is unsupported".
        expected = request.form.get("size", type=int)
        received = target.stat().st_size
        if expected and received != expected:
            shutil.rmtree(root, ignore_errors=True)
            raise ValueError(
                f"the upload was cut short: {received / 1e6:.1f} MB arrived out of "
                f"{expected / 1e6:.1f} MB. Try again, or open the file by path "
                "instead of uploading it (see the field under the file picker)."
            )

        session = _start_session(sid, root, target)
        with lock:
            sessions[sid] = session
        return jsonify(session.public())

    @app.get("/api/config")
    def client_config():
        """What the page is allowed to offer, decided by the server."""
        return jsonify({"local_mode": bool(local_mode)})

    @app.post("/api/video/path")
    def open_video_path():
        """Analyse a file where it already is -- no copy, no upload wait."""
        if not local_mode:
            return jsonify(
                {
                    "error": "opening files by path is only available when "
                    "faraday-cv runs on your own machine; upload the video instead"
                }
            ), 403
        data = request.get_json(force=True)
        raw = (data.get("path") or "").strip().strip("'\"")
        if not raw:
            raise ValueError("no path given")
        target = Path(raw).expanduser()
        if not target.is_absolute():
            raise ValueError(f"give the full path, starting from / : {raw}")
        if not target.exists() or not target.is_file():
            raise ValueError(f"no such file: {target}")
        if target.suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError(
                f"unsupported video type {target.suffix!r}; use one of "
                + ", ".join(sorted(VIDEO_SUFFIXES))
            )
        sid = uuid.uuid4().hex[:12]
        root = base / sid
        root.mkdir(parents=True, exist_ok=True)
        session = _start_session(sid, root, target, cleanup=root)
        with lock:
            sessions[sid] = session
        return jsonify(session.public())

    @app.post("/api/session/<sid>/voltage")
    def upload_voltage(sid: str):
        """The Arduino log is uploaded on its own, after the video."""
        session = get_session(sid)
        file = request.files.get("file")
        if file is None or not file.filename:
            raise ValueError("no voltage file in the request")
        target = session.root / secure_filename(file.filename)
        file.save(target)
        from .voltage import load_voltage_csv

        unit = request.form.get("voltage_unit", "auto")
        try:
            log = load_voltage_csv(target, voltage_unit=unit)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise ValueError(f"cannot read that voltage log: {exc}") from exc
        session.voltage = target
        session.voltage_info = log.to_dict()
        session.voltage_info["filename"] = target.name
        return jsonify(session.public())

    # ------------------------------------------------------------ inspection

    @app.get("/api/session/<sid>")
    def session_state(sid: str):
        return jsonify(get_session(sid).public())

    @app.get("/api/session/<sid>/frame")
    def frame(sid: str):
        session = get_session(sid)
        index = int(request.args.get("index", 0))
        img = read_frame(session.video, index)
        return _jpeg(img)

    @app.post("/api/session/<sid>/pick")
    def pick(sid: str):
        """Suggest an HSV box from a click on the magnet."""
        session = get_session(sid)
        data = request.get_json(force=True)
        img = read_frame(session.video, int(data.get("index", 0)))
        color = sample_color_range(
            img,
            int(data["x"]),
            int(data["y"]),
            radius=int(data.get("radius", 6)),
            h_tol=int(data.get("h_tol", 10)),
            s_tol=int(data.get("s_tol", 70)),
            v_tol=int(data.get("v_tol", 80)),
        )
        return jsonify({"color": color.to_dict()})

    @app.post("/api/session/<sid>/preview")
    def preview(sid: str):
        """Return the frame with the current segmentation drawn on top."""
        session = get_session(sid)
        data = request.get_json(force=True)
        img = read_frame(session.video, int(data.get("index", 0)))
        color = ColorRange.from_dict(data.get("color", {}))
        cfg = SegmentConfig.from_dict(data.get("segment", {}))
        mask = segment(img, color, cfg)
        blobs = find_blobs(mask, cfg.min_area)
        best = select_blob(blobs)
        if data.get("stats"):
            return jsonify(
                {
                    "blobs": len(blobs),
                    "centroid": [best.cx, best.cy] if best else None,
                    "area": best.area if best else 0,
                    "coverage": float((mask > 0).mean()),
                }
            )
        return _jpeg(overlay_mask(img, mask, best))

    # --------------------------------------------------------------- running

    @app.post("/api/session/<sid>/run")
    def run(sid: str):
        session = get_session(sid)
        if session.state == "running":
            raise ValueError("this session is already running")
        data = request.get_json(force=True)
        cfg = _config_from_request(session, data)
        session.state = "running"
        session.progress = 0.0
        session.message = "tracking the magnet..."
        session.result = {}

        thread = threading.Thread(
            target=_run_job, args=(session, cfg), name=f"faraday-{sid}", daemon=True
        )
        thread.start()
        return jsonify(session.public())

    @app.get("/api/session/<sid>/file/<name>")
    def result_file(sid: str, name: str):
        session = get_session(sid)
        if name not in RESULT_FILES:
            raise ValueError(f"unknown result file {name!r}")
        path = session.outdir / name
        if not path.exists():
            raise ValueError(f"{name} has not been produced yet")
        return send_file(path, max_age=0)

    return app


def _start_session(
    sid: str, root: Path, video: Path, cleanup: Path | None = None
) -> Session:
    """Probe the video (converting it if need be) and build the session."""
    session = Session(sid=sid, root=root, video=video)
    try:
        session.info = probe(video).to_dict()
    except Exception as exc:
        shutil.rmtree(cleanup or root, ignore_errors=True)
        raise ValueError(f"cannot read that video: {exc}") from exc
    return session


def _run_job(session: Session, cfg: AnalysisConfig) -> None:
    def progress(done: int, total: int) -> None:
        session.progress = 100.0 * done / max(total, 1)

    try:
        result = run_analysis(cfg, progress=progress)
        session.message = "writing figures..."
        written = export_results(result, session.outdir)
        session.result = {
            "stats": result.stats,
            "notes": result.notes,
            "led_frame": result.led_frame,
            "t0_video_s": result.t0_video,
            "detection_rate": result.track.detection_rate,
            "files": {k: Path(v).name for k, v in written.items()},
            "voltage": result.log.to_dict() if result.log else None,
        }
        session.progress = 100.0
        session.state = "done"
        session.message = "done"
    except Exception as exc:  # surfaced in the UI, not swallowed
        session.state = "error"
        session.message = f"{type(exc).__name__}: {exc}"
        (session.root / "error.log").write_text(traceback.format_exc())


def _config_from_request(session: Session, data: dict) -> AnalysisConfig:
    if session.video is None:
        raise ValueError("this session has no video")
    calib_data = dict(data.get("calibration", {}))
    scale = calib_data.pop("scale_line", None)
    calib = Calibration.from_dict(calib_data)
    if scale and scale.get("length_mm"):
        calib.mm_per_px = Calibration.scale_from_line(
            (float(scale["x0"]), float(scale["y0"])),
            (float(scale["x1"]), float(scale["y1"])),
            float(scale["length_mm"]),
        )
    led_roi = data.get("led_roi")
    return AnalysisConfig(
        video=str(session.video),
        voltage=str(session.voltage) if session.voltage else None,
        color=ColorRange.from_dict(data.get("color", {})),
        segment=SegmentConfig.from_dict(data.get("segment", {})),
        calibration=calib,
        led_roi=tuple(int(v) for v in led_roi) if led_roi else None,
        led_threshold=_opt_float(data.get("led_threshold")),
        t0_video=_opt_float(data.get("t0_video")),
        t0_voltage=float(data.get("t0_voltage") or 0.0),
        voltage_unit=data.get("voltage_unit", "auto"),
        baseline_seconds=float(data.get("baseline_seconds", 0.2)),
        v_min=_opt_float(data.get("v_min")),
        fps_override=_opt_float(data.get("fps_override")),
        max_jump_px=_opt_float(data.get("max_jump_px")),
        start_frame=int(data.get("start_frame") or 0),
        end_frame=int(data["end_frame"]) if data.get("end_frame") else None,
        title=data.get("title") or None,
    )


def _opt_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _jpeg(image: np.ndarray):
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise ValueError("failed to encode the frame")
    from flask import Response

    return Response(buf.tobytes(), mimetype="image/jpeg")


if __name__ == "__main__":  # pragma: no cover
    create_app().run(host="127.0.0.1", port=8000)
