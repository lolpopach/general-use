"""Opening video files that OpenCV does not want to open.

The failure this guards against is the one a teacher actually hits: a clip
straight off a phone, HEVC inside an .mp4, which ``cv2.VideoCapture`` refuses
with no explanation at all.
"""

from __future__ import annotations

import pytest

from faradaycv.decode import (
    VideoOpenError,
    available_backends,
    ffmpeg_binary,
    readable_video,
    try_open,
    transcode_to_h264,
)
from faradaycv.video import probe


def test_a_readable_video_is_used_as_is(dataset):
    path, note = readable_video(dataset.video)
    assert path == dataset.video
    assert note is None  # nothing was converted, so nothing to report


def test_every_build_reports_at_least_one_backend():
    names = [name for name, _ in available_backends()]
    assert names
    assert try_open("no-such-file.mp4") == (None, None)


def test_a_missing_file_says_so_before_anything_else(tmp_path):
    with pytest.raises(FileNotFoundError):
        readable_video(tmp_path / "nope.mp4")


def test_an_empty_file_is_named_as_empty(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(VideoOpenError, match="empty"):
        readable_video(empty)


def test_an_undecodable_file_explains_what_to_do(tmp_path):
    """The message has to carry the fix, since the user sees only this."""
    junk = tmp_path / "broken.mp4"
    junk.write_bytes(b"\x00\x01\x02not a video at all" * 500)
    with pytest.raises(VideoOpenError) as exc:
        readable_video(junk)
    message = str(exc.value)
    assert "broken.mp4" in message
    assert "HEVC" in message  # names the usual cause
    assert "ffmpeg -i" in message  # and gives a command that fixes it


@pytest.mark.skipif(ffmpeg_binary() is None, reason="no ffmpeg available")
def test_a_forced_conversion_produces_a_video_opencv_can_read(dataset, truth):
    converted, note = readable_video(dataset.video, force_transcode=True)
    assert converted != dataset.video
    assert converted.exists() and converted.stat().st_size > 0
    assert note and "H.264" in note

    info = probe(converted)
    assert (info.width, info.height) == (640, 480)
    assert info.fps == pytest.approx(truth["fps"], rel=0.02)
    assert abs(info.frame_count - truth["n_frames"]) <= 1


@pytest.mark.skipif(ffmpeg_binary() is None, reason="no ffmpeg available")
def test_the_conversion_is_cached_not_repeated(dataset):
    first, _ = readable_video(dataset.video, force_transcode=True)
    stamp = first.stat().st_mtime_ns
    second, _ = readable_video(dataset.video, force_transcode=True)
    assert second == first
    assert second.stat().st_mtime_ns == stamp, "the file was re-encoded needlessly"


@pytest.mark.skipif(ffmpeg_binary() is None, reason="no ffmpeg available")
def test_conversion_can_be_pointed_at_a_chosen_file(dataset, tmp_path):
    target = transcode_to_h264(dataset.video, tmp_path / "out.mp4")
    assert target.exists()
    cap, backend = try_open(target)
    assert cap is not None and backend
    cap.release()


def test_conversion_can_be_refused(dataset, tmp_path):
    """``allow_transcode=False`` keeps a batch run from silently re-encoding."""
    junk = tmp_path / "broken.mp4"
    junk.write_bytes(b"not a video" * 900)
    with pytest.raises(VideoOpenError):
        readable_video(junk, allow_transcode=False)
