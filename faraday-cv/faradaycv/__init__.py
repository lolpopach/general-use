"""faradaycv -- colour-segmentation video analysis for the Faraday's law lab.

Video in, magnet position and velocity out; combine with the Arduino voltage
log (uploaded separately) and get the paper's figures on a common time axis.
"""

from .analysis import Calibration, Motion, Synced, build_motion, summarize, synchronize
from .pipeline import AnalysisConfig, AnalysisResult, export_results, run_analysis
from .segmentation import (
    Blob,
    ColorRange,
    SegmentConfig,
    find_blobs,
    sample_color_range,
    segment,
)
from .video import Track, VideoInfo, led_onset_frame, probe, read_frame, track_video
from .voltage import VoltageLog, load_voltage_csv, parse_voltage_text

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
