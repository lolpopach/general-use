"""faradaycv -- colour-segmentation video analysis for the Faraday's law lab.

Video in, magnet position and velocity out; combine with the Arduino voltage
log (uploaded separately) and get the paper's figures on a common time axis.
"""

from .analysis import Calibration, Motion, Synced, build_motion, summarize, synchronize
from .pipeline import (
    AnalysisConfig,
    AnalysisResult,
    analyse_track,
    export_results,
    run_analysis,
)
from .segmentation import (
    Blob,
    ColorRange,
    SegmentConfig,
    find_blobs,
    sample_color_range,
    segment,
)
from .track import Track, VideoInfo, led_onset_frame
from .voltage import VoltageLog, load_voltage_csv, parse_voltage_text

try:
    # OpenCV-backed video decoding.  Optional: a hosted deployment segments
    # video in the browser and never needs to decode one server-side, so this
    # package must stay importable without opencv-python installed.
    from .video import open_video, probe, read_frame, track_video  # noqa: F401
except ImportError as _exc:  # pragma: no cover - exercised by the no-cv2 check

    def _needs_opencv(*_args, _exc=_exc, **_kwargs):
        raise ImportError(
            "this needs OpenCV; install it with: "
            "python3 -m pip install opencv-python-headless"
        ) from _exc

    open_video = probe = read_frame = track_video = _needs_opencv

__version__ = "0.1.0"

__all__ = [
    "AnalysisConfig",
    "AnalysisResult",
    "Blob",
    "Calibration",
    "ColorRange",
    "Motion",
    "SegmentConfig",
    "Synced",
    "Track",
    "VideoInfo",
    "VoltageLog",
    "analyse_track",
    "build_motion",
    "export_results",
    "find_blobs",
    "led_onset_frame",
    "load_voltage_csv",
    "parse_voltage_text",
    "probe",
    "read_frame",
    "run_analysis",
    "sample_color_range",
    "segment",
    "summarize",
    "synchronize",
    "track_video",
]
