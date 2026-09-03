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
from dataclasses import dataclass
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
    """Explain the actual defect, rather than guessing at the codec."""
    size_mb = path.stat().st_size / 1e6
    try:
        report = diagnose(path)
    except Exception:  # diagnosis must never mask the original failure
        return (
            f"cannot read {path.name} ({size_mb:.1f} MB), and the file could not "
            "be inspected either"
        )
    return (
        f"cannot read {path.name} ({size_mb:.1f} MB): {report.verdict}. "
        f"What to do: {report.advice}. "
        f"For the full report run: python3 -m faradaycv doctor '{path}'"
    )


# --------------------------------------------------------------------- doctor

#: Leading bytes that identify a container we might be handed.
_SIGNATURES = {
    b"\x1aE\xdf\xa3": "Matroska/WebM",
    b"RIFF": "AVI (RIFF)",
    b"OggS": "Ogg",
    b"FLV\x01": "FLV",
}

#: Top-level MP4/MOV boxes that carry no meaning for us, so seeing only these
#: means the interesting parts of the file are missing.
_FILLER_BOXES = {"free", "skip", "wide", "pnot"}


@dataclass
class VideoDiagnosis:
    """What is actually wrong with a file that will not open."""

    path: Path
    size_bytes: int
    container: str | None
    boxes: list[tuple[str, int]]
    opencv_backend: str | None
    ffmpeg_error: str | None
    verdict: str
    advice: str

    @property
    def opencv_ok(self) -> bool:
        return self.opencv_backend is not None

    @property
    def ffmpeg_ok(self) -> bool:
        return self.ffmpeg_error is None

    def box_names(self) -> list[str]:
        return [name for name, _size in self.boxes]

    def to_text(self) -> str:
        lines = [
            f"file          : {self.path}",
            f"size          : {self.size_bytes / 1e6:.1f} MB",
            f"container     : {self.container or 'unrecognised'}",
        ]
        if self.boxes:
            shown = ", ".join(f"{n}({s / 1e6:.1f}MB)" for n, s in self.boxes[:8])
            lines.append(f"mp4 boxes     : {shown}")
        lines += [
            f"OpenCV        : {'opens with ' + self.opencv_backend if self.opencv_ok else 'cannot open'}",
            f"ffmpeg        : {'reads it' if self.ffmpeg_ok else self.ffmpeg_error}",
            "",
            f"verdict       : {self.verdict}",
            f"what to do    : {self.advice}",
        ]
        return "\n".join(lines)


def _read_mp4_boxes(path: Path, limit: int = 40) -> list[tuple[str, int]]:
    """Walk the top-level MP4/MOV boxes without decoding anything."""
    boxes: list[tuple[str, int]] = []
    size = path.stat().st_size
    with path.open("rb") as fh:
        offset = 0
        while offset < size and len(boxes) < limit:
            fh.seek(offset)
            header = fh.read(8)
            if len(header) < 8:
                break
            box_size = int.from_bytes(header[:4], "big")
            name = header[4:8].decode("latin-1")
            if not name.isprintable():
                break
            if box_size == 1:  # 64-bit size follows the header
                extended = fh.read(8)
                if len(extended) < 8:
                    break
                box_size = int.from_bytes(extended, "big")
            elif box_size == 0:  # runs to the end of the file
                box_size = size - offset
            if box_size < 8:
                break
            boxes.append((name, box_size))
            offset += box_size
    return boxes


def _container_of(head: bytes, boxes: list[tuple[str, int]]) -> str | None:
    for magic, name in _SIGNATURES.items():
        if head.startswith(magic):
            return name
    if boxes and boxes[0][0] == "ftyp":
        brand = head[8:12].decode("latin-1", "replace").strip()
        return f"MP4/MOV (brand {brand})"
    return None


def _ffmpeg_check(path: Path, timeout: float = 60.0) -> str | None:
    """None if ffmpeg can read the file, else its complaint."""
    ffmpeg = ffmpeg_binary()
    if ffmpeg is None:
        return "ffmpeg is not installed"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-v",
        "error",
        "-i",
        str(path),
        "-t",
        "0.1",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "ffmpeg timed out reading the file"
    if result.returncode == 0:
        return None
    lines = [ln for ln in (result.stderr or "").strip().splitlines() if ln]
    return lines[0][:200] if lines else f"exit code {result.returncode}"


def diagnose(path: str | Path) -> VideoDiagnosis:
    """Say what is wrong with a video file, in terms the user can act on."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(32)
    boxes = _read_mp4_boxes(path) if head[4:8] == b"ftyp" else []
    container = _container_of(head, boxes)

    cap, backend = try_open(path)
    if cap is not None:
        cap.release()
    ffmpeg_error = _ffmpeg_check(path)

    names = {name for name, _ in boxes}
    verdict, advice = _verdict(
        size, container, names, backend is not None, ffmpeg_error
    )
    return VideoDiagnosis(
        path=path,
        size_bytes=size,
        container=container,
        boxes=boxes,
        opencv_backend=backend,
        ffmpeg_error=ffmpeg_error,
        verdict=verdict,
        advice=advice,
    )


def _verdict(
    size: int,
    container: str | None,
    boxes: set[str],
    opencv_ok: bool,
    ffmpeg_error: str | None,
) -> tuple[str, str]:
    if size == 0:
        return ("the file is empty", "copy the video across again")
    if opencv_ok:
        return ("the file is fine -- OpenCV reads it directly", "nothing to do")
    if ffmpeg_error is None:
        return (
            "OpenCV cannot decode this codec, but ffmpeg can",
            "faraday-cv will convert it automatically; just upload it again",
        )
    if container is None:
        return (
            "this is not a video container faraday-cv recognises",
            "check that the file really is the video, and not a placeholder, an "
            "alias, or a partially downloaded iCloud item",
        )
    if boxes and "moov" not in boxes:
        missing = "only " + ", ".join(sorted(boxes)) if boxes else "nothing"
        return (
            f"the MP4 index (moov atom) is missing -- the file holds {missing}, "
            "so it is incomplete, not merely an odd codec",
            "the copy stopped early: re-copy or re-export the whole video (in "
            "Photos use File > Export > Export Unmodified Original, and wait for "
            "the iCloud download to finish), then check the byte size matches",
        )
    if boxes <= _FILLER_BOXES | {"ftyp"}:
        return (
            "the file has a header but no video data",
            "re-export the video; this copy carries no frames",
        )
    return (
        f"ffmpeg cannot read the file either: {ffmpeg_error}",
        "the file is damaged; re-copy it from the camera or phone",
    )
