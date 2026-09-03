"""The scripting front end, for batch re-runs of an already-tuned setup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faradaycv.cli import main


def test_info_prints_the_video_geometry(dataset, truth, capsys):
    assert main(["info", str(dataset.video)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["frame_count"] == truth["n_frames"]


def test_frame_writes_an_image(dataset, tmp_path, capsys):
    target = tmp_path / "frame.png"
    assert (
        main(["frame", str(dataset.video), "--index", "5", "--out", str(target)]) == 0
    )
    assert target.stat().st_size > 1000


def test_pick_suggests_a_range_that_can_be_pasted_back(
    dataset, truth, tmp_path, capsys
):
    x, y = truth["magnet_px"][0]
    preview = tmp_path / "preview.png"
    code = main(
        [
            "pick",
            str(dataset.video),
            "--at",
            f"{int(x)},{int(y)}",
            "--preview",
            str(preview),
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out.split("wrote")[0])
    assert out["blobs"] == 1
    assert out["largest_blob"]["cx"] == pytest.approx(x, abs=1.5)
    assert preview.exists()

    # the printed "cli" string is exactly what --hsv accepts
    from faradaycv.segmentation import ColorRange

    assert ColorRange.parse(out["cli"]).to_dict() == out["hsv"]


def test_track_writes_a_csv_with_one_row_per_frame(dataset, truth, tmp_path, capsys):
    target = tmp_path / "track.csv"
    code = main(
        [
            "track",
            str(dataset.video),
            "--hsv",
            "170,10,120,255,80,255",
            "--min-area",
            "60",
            "-o",
            str(target),
        ]
    )
    assert code == 0
    rows = target.read_text().splitlines()
    assert rows[0] == "frame,t_video_s,x_px,y_px,area_px,found"
    assert len(rows) == truth["n_frames"] + 1


def test_analyze_runs_the_whole_pipeline(dataset, truth, tmp_path, capsys):
    outdir = tmp_path / "out"
    code = main(
        [
            "analyze",
            str(dataset.video),
            "--voltage",
            str(dataset.voltage),
            "--hsv",
            "170,10,120,255,80,255",
            "--min-area",
            "60",
            "--led-roi",
            ",".join(str(v) for v in truth["led_roi"]),
            "--mm-per-px",
            str(truth["mm_per_px"]),
            "--coil",
            f"{truth['coil_px'][0]},{truth['coil_px'][1]}",
            "-o",
            str(outdir),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "LED onset" in printed and "peak separation" in printed
    assert (outdir / "fig2_motion_and_voltage.png").exists()
    assert (outdir / "fig3_emf_over_velocity.png").exists()

    summary = json.loads((outdir / "summary.json").read_text())
    assert summary["stats"]["t_max_abs_voltage_s"] == pytest.approx(
        truth["t_max_abs_emf_s"], abs=0.02
    )


def test_a_scale_line_on_the_command_line_sets_mm_per_px(dataset, tmp_path):
    outdir = tmp_path / "scaled"
    code = main(
        [
            "analyze",
            str(dataset.video),
            "--voltage",
            str(dataset.voltage),
            "--hsv",
            "170,10,120,255,80,255",
            "--min-area",
            "60",
            "--scale-line",
            "0,0,200,0",
            "--scale-length",
            "500",
            "-o",
            str(outdir),
        ]
    )
    assert code == 0
    summary = json.loads((outdir / "summary.json").read_text())
    assert summary["config"]["calibration"]["mm_per_px"] == pytest.approx(2.5)


def test_a_malformed_colour_range_is_rejected_before_any_work(dataset):
    with pytest.raises(SystemExit) as exc:
        main(["track", str(dataset.video), "--hsv", "1,2,3", "-o", "unused.csv"])
    assert exc.value.code == 2
    assert not Path("unused.csv").exists()


def test_doctor_passes_a_healthy_video(dataset, capsys):
    assert main(["doctor", str(dataset.video)]) == 0
    printed = capsys.readouterr().out
    assert "verdict" in printed and "fine" in printed


def test_doctor_fails_and_explains_a_part_copied_video(dataset, tmp_path, capsys):
    cut = tmp_path / "half.mp4"
    data = dataset.video.read_bytes()
    cut.write_bytes(data[: len(data) // 2])
    assert main(["doctor", str(cut)]) == 1
    printed = capsys.readouterr().out
    assert "moov" in printed
    assert "re-copy" in printed or "re-export" in printed
