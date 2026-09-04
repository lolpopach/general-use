"""Opening video files that OpenCV does not want to open.

The failure this guards against is the one a teacher actually hits: a clip
straight off a phone, HEVC inside an .mp4, which ``cv2.VideoCapture`` refuses
with no explanation at all.
"""

from __future__ import annotations

import pytest

from faradaycv.decode import (
    VideoOpenError,
    _contains_moov_signature,
    _read_mp4_boxes,
    available_backends,
    diagnose,
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
    assert "not a video container" in message
    assert "doctor" in message  # points at the full report
    assert "HEVC" not in message, "must not blame the codec when it is not one"


def _truncate(source, target, fraction=0.6):
    """A part-copied MP4: header and data, but no index at the end."""
    data = source.read_bytes()
    target.write_bytes(data[: int(len(data) * fraction)])
    return target


def test_a_part_copied_video_is_named_as_incomplete(dataset, tmp_path):
    """The failure a large upload actually produces, and the one to name."""
    cut = _truncate(dataset.video, tmp_path / "half.mp4")
    report = diagnose(cut)

    assert report.container and report.container.startswith("MP4/MOV")
    assert "moov" not in report.box_names(), "the index is what a cut copy loses"
    assert "mdat" in report.box_names()
    assert not report.opencv_ok and not report.ffmpeg_ok
    assert "moov" in report.verdict and "incomplete" in report.verdict
    assert "re-copy" in report.advice or "re-export" in report.advice


def test_moov_signature_rescues_what_the_box_walk_can_miss(tmp_path):
    """A box declaring size 0 ("runs to EOF") makes the sequential box walk
    jump straight past anything written after it. Real ffmpeg follows the
    same rule and would fail on this exact layout too -- so this does not
    reproduce a file a real decoder can open -- but it is still the layout a
    walker desync of this shape produces, and `_verdict` must not take the
    walk's word alone before blaming a missing index."""
    ftyp = source_box(b"ftyp", b"isom" + b"\x00" * 12)
    mdat = bytearray(8 + 2000)
    mdat[4:8] = b"mdat"  # size left as 0: "runs to end of file"
    moov = source_box(b"moov", b"\x00" * 300)
    quirky = tmp_path / "quirky.mp4"
    quirky.write_bytes(ftyp + bytes(mdat) + moov)

    boxes = {name for name, _ in _read_mp4_boxes(quirky)}
    assert "moov" not in boxes, "the naive walk is expected to miss it here"
    assert _contains_moov_signature(quirky), "the raw bytes still hold a real moov"


def test_moov_signature_is_false_for_a_genuinely_truncated_file(dataset, tmp_path):
    """The safety net must not turn an actually-incomplete copy into a false
    negative: a cut-short file never had a moov box written at all."""
    cut = _truncate(dataset.video, tmp_path / "half.mp4")
    assert not _contains_moov_signature(cut), "a cut-short copy has no moov anywhere"


def source_box(name: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + name + payload


def test_a_healthy_video_is_reported_as_healthy(dataset):
    report = diagnose(dataset.video)
    assert report.opencv_ok and report.ffmpeg_ok
    assert set(report.box_names()) >= {"ftyp", "mdat", "moov"}
    assert "fine" in report.verdict
    assert "size" in report.to_text() and "verdict" in report.to_text()


def test_an_empty_file_diagnoses_as_empty(tmp_path):
    empty = tmp_path / "nothing.mp4"
    empty.write_bytes(b"")
    assert "empty" in diagnose(empty).verdict


def test_diagnosis_needs_the_file_to_exist(tmp_path):
    with pytest.raises(FileNotFoundError):
        diagnose(tmp_path / "ghost.mp4")


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
