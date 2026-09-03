"""Getting a phone video into OpenCV.

OpenCV's bundled FFmpeg does not decode everything a camera produces -- an
iPhone clip is usually HEVC in an .mp4 or .mov container, and on many builds
``cv2.VideoCapture`` simply reports failure with no reason given.  So before
giving up, this module tries every video backend the build offers and then
falls back to transcoding the file to H.264 with the ffmpeg binary shipped by
``imageio-ffmpeg`` (no system install needed).

The transcode also forces a constant frame rate.  That matters beyond
decoding: phones record variable frame rate, and the analysis reads a frame's
time as ``index / fps``, which is only true for constant-rate video.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import cv2

#: Backends worth trying, in order.  Names that this build does not have are
#: skipped -- AVFoundation only exists on macOS, MSMF only on Windows.
_BACKEND_NAMES = ("FFMPEG", "AVFOUNDATION", "MSMF", "GSTREAMER", "CV_IMAGES")

TRANSCODE_DIRNAME = "faraday-cv-transcoded"


class VideoOpenError(ValueError):
    """Raised when no backend and no fallback could read the video."""


def available_backends() -> list[tuple[str, int]]:
    """(name, id) for each video backend compiled into this OpenCV."""
    out: list[tuple[str, int]] = []
    for backend in cv2.videoio_registry.getBackends():
        name = cv2.videoio_registry.getBackendName(backend)
        if name not in {n for n, _ in out}:
            out.append((name, int(backend)))
    return out


def _ordered_backends() -> list[tuple[str, int]]:
    have = {name: bid for name, bid in available_backends()}
    ordered = [(name, have[name]) for name in _BACKEND_NAMES if name in have]
    ordered += [(name, bid) for name, bid in have.items() if name not in _BACKEND_NAMES]
    return ordered


def try_open(path: str | Path) -> tuple[cv2.VideoCapture | None, str | None]:
    """Open with the first backend that can actually decode a frame."""
    for name, backend in _ordered_backends():
        cap = cv2.VideoCapture(str(path), backend)
        opened = cap.isOpened() and cap.read()[0]
        cap.release()
        if opened:
            # Re-open rather than seek back: seeking to frame 0 is not reliable
            # on every codec, and a fresh capture certainly starts at the top.
            return cv2.VideoCapture(str(path), backend), name
    # Last resort: let OpenCV choose for itself.
    cap = cv2.VideoCapture(str(path))
    opened = cap.isOpened() and cap.read()[0]
    cap.release()
    if opened:
        return cv2.VideoCapture(str(path)), "default"
    return None, None


def ffmpeg_binary() -> str | None:
    """The ffmpeg shipped with imageio-ffmpeg, or a system one, or None."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which

        return which("ffmpeg")


def _cache_path(source: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / TRANSCODE_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"{source.stem}-{digest}.mp4"


def transcode_to_h264(
    source: str | Path,
    target: str | Path | None = None,
    timeout: float = 1800.0,
) -> Path:
    """Re-encode to constant-rate H.264 that any OpenCV build can read."""
    source = Path(source)
    target = Path(target) if target else _cache_path(source)
    if target.exists() and target.stat().st_size > 0:
        return target  # already converted in an earlier run

    ffmpeg = ffmpeg_binary()
    if ffmpeg is None:
        raise VideoOpenError(
            "this video needs converting, but no ffmpeg is available -- install "
            "it with: python3 -m pip install imageio-ffmpeg"
        )

    base = [ffmpeg, "-y", "-i", str(source), "-map", "0:v:0"]
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    tail = ["-pix_fmt", "yuv420p", "-an", str(target)]
    attempts = [
        base + ["-fps_mode", "cfr"] + encode + tail,  # ffmpeg >= 5
        base + ["-vsync", "cfr"] + encode + tail,  # older ffmpeg
        base + encode + tail,  # no rate control available
    ]

    errors: list[str] = []
    for cmd in attempts:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return target
        lines = (result.stderr or "").strip().splitlines()
        errors.append(lines[-1] if lines else "")
        target.unlink(missing_ok=True)

    detail = "; ".join(line for line in errors if line)
    raise VideoOpenError(f"ffmpeg could not convert this video: {detail[:400]}")


def readable_video(
    path: str | Path,
    allow_transcode: bool = True,
    force_transcode: bool = False,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, str | None]:
    """Return a path OpenCV can decode, plus a note when one was needed.

    Nothing is copied or re-encoded unless it has to be; a converted file is
    cached in the system temp directory and reused on later runs.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such video: {path}")
    if path.stat().st_size == 0:
        raise VideoOpenError(f"the video file is empty: {path}")

    if not force_transcode:
        cap, backend = try_open(path)
        if cap is not None:
            cap.release()
            return path, None

    if not allow_transcode:
        raise VideoOpenError(_cannot_open_message(path))

    if progress:
        progress("converting the video to H.264 (this happens once per file)...")
    try:
        converted = transcode_to_h264(path)
    except VideoOpenError as exc:
        raise VideoOpenError(f"{_cannot_open_message(path)}\n{exc}") from exc

    cap, _backend = try_open(converted)
    if cap is None:
        raise VideoOpenError(_cannot_open_message(path))
    cap.release()
    if force_transcode:
        return converted, "a constant-rate H.264 copy was made and analysed"
    return converted, (
        "this video could not be decoded directly (HEVC from a phone, most "
        "likely), so a constant-rate H.264 copy was made and analysed instead"
    )


def _cannot_open_message(path: Path) -> str:
    backends = ", ".join(name for name, _ in available_backends()) or "none"
    size_mb = path.stat().st_size / 1e6
    return (
        f"OpenCV cannot decode {path.name} ({size_mb:.1f} MB). "
        f"Backends tried: {backends}. "
        "Phone video is often HEVC/H.265, which many OpenCV builds cannot read. "
        "Install the bundled converter with "
        "'python3 -m pip install imageio-ffmpeg' and try again, or convert the "
        f"file yourself: ffmpeg -i {path.name} -c:v libx264 -pix_fmt yuv420p "
        "-an converted.mp4"
    )
