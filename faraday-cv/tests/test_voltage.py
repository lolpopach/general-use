"""Reading the Arduino log, in the shapes it actually arrives in."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from faradaycv.voltage import load_voltage_csv, parse_voltage_text


def test_sketch_format_becomes_seconds_and_volts():
    log = parse_voltage_text(
        "# faraday-cv voltage log\n"
        "# t = 0 is the LED onset\n"
        "t_ms,voltage_mV\n"
        "0.000,1.7031\n"
        "8.621,12.5\n"
        "17.241,-9.25\n"
    )
    assert len(log) == 3
    assert log.t[-1] == pytest.approx(0.017241)
    assert log.v[1] == pytest.approx(0.0125)
    assert log.meta["time_unit"] == "ms"
    assert log.meta["voltage_unit"] == "mV"
    assert log.sample_rate == pytest.approx(116.0, rel=0.01)


def test_headerless_milliseconds_are_recognised_from_the_step():
    text = "\n".join(f"{i * 10},{i}" for i in range(50))
    log = parse_voltage_text(text)
    assert log.t[-1] == pytest.approx(0.49)
    assert "ms" in log.meta["time_unit"]


def test_seconds_and_volts_pass_through():
    text = "time_s;voltage_V\n0.0;0.5\n0.01;-0.25\n0.02;0.1\n"
    log = parse_voltage_text(text)
    assert log.t[1] == pytest.approx(0.01)
    assert log.v[1] == pytest.approx(-0.25)
    assert log.meta["voltage_unit"] == "V"


def test_large_unlabelled_values_are_read_as_millivolts():
    text = "\n".join(f"{i * 0.01:.2f} {40 * np.sin(i):.3f}" for i in range(200))
    log = parse_voltage_text(text)
    assert "mV" in log.meta["voltage_unit"]
    assert np.max(np.abs(log.v)) < 0.05


def test_unit_override_beats_the_guess():
    text = "t_ms,value\n0,100\n10,120\n20,90\n"
    assert parse_voltage_text(text, voltage_unit="V").v[0] == pytest.approx(100.0)
    assert parse_voltage_text(text, voltage_unit="mV").v[0] == pytest.approx(0.1)


def test_extra_columns_are_selected_by_name():
    text = "sample,t_ms,raw_adc,voltage_mV\n1,0,320,2.5\n2,10,318,2.4\n3,20,300,-1.0\n"
    log = parse_voltage_text(text)
    assert log.t[2] == pytest.approx(0.02)
    assert log.v[2] == pytest.approx(-0.001)


def test_a_single_out_of_order_row_is_dropped_not_sorted():
    """A serial log is monotonic, so a stray timestamp is a glitch.

    Sorting it into place would invent a gap (and a longer record) where the
    logger only ever emitted one bad line.
    """
    rows = ["t_ms,voltage_mV", "9999,42"] + [f"{i * 10},{i}" for i in range(30)]
    log = parse_voltage_text("\n".join(rows))
    assert len(log) == 30
    assert log.t[-1] == pytest.approx(0.29)
    assert log.meta["out_of_order_rows"] == 1
    assert np.all(np.diff(log.t) > 0)


def test_garbage_rows_are_skipped_not_fatal():
    log = parse_voltage_text("t_ms,voltage_mV\n0,1\nNaNsense,x\n10,2\n20,3\n")
    assert len(log) == 3
    assert log.meta["skipped_rows"] == 1


def test_empty_and_tiny_files_raise():
    with pytest.raises(ValueError):
        parse_voltage_text("# only comments\n")
    with pytest.raises(ValueError):
        parse_voltage_text("t_ms,voltage_mV\n0,1\n")


def test_baseline_uses_a_quiet_head_when_there_is_one():
    t = np.arange(1000) / 100.0
    v = np.where(t < 2, 0.0, np.sin(t)) + 0.0017
    text = "t_s,voltage_V\n" + "\n".join(f"{a},{b}" for a, b in zip(t, v))
    log = parse_voltage_text(text)
    offset, how = log.baseline_offset(0.2)
    assert offset == pytest.approx(0.0017, abs=1e-6)
    assert how.startswith("first")


def test_baseline_falls_back_to_the_median_when_the_head_is_busy():
    t = np.arange(1000) / 100.0
    v = np.sin(2 * np.pi * t) + 0.0017  # already swinging at t = 0
    text = "t_s,voltage_V\n" + "\n".join(f"{a},{b}" for a, b in zip(t, v))
    log = parse_voltage_text(text)
    offset, how = log.baseline_offset(0.2)
    assert how == "record median"
    assert offset == pytest.approx(0.0017, abs=5e-3)
    assert log.baseline_corrected(0.2).meta["baseline_from"] == "record median"


def test_the_generated_log_loads_from_disk(dataset, truth):
    log = load_voltage_csv(dataset.voltage)
    assert log.sample_rate == pytest.approx(116.0, rel=0.02)
    corrected = log.baseline_corrected(0.2)
    removed = corrected.meta["baseline_v"] * 1e3
    assert removed == pytest.approx(truth["voltage_offset_mV"], abs=0.2)


REAL_LOG = Path(__file__).parent / "data" / "ads1115_real_excerpt.csv"


def test_a_real_ads1115_log_parses_as_millivolts_on_a_clean_clock():
    """Excerpt of a real 100 Hz log: no header, 9 columns, and two glitches.

    Row 1 carries a stray timestamp from before the run (37.75 s) and the
    capture ends with the last sample flushed three times.  Sorting those into
    place would stretch the record to 37.75 s and open a 12 s hole in it.
    """
    log = load_voltage_csv(REAL_LOG)

    assert np.all(np.diff(log.t) > 0), "timestamps must come out strictly increasing"
    assert log.meta["out_of_order_rows"] == 3  # the stray row + two duplicates
    assert log.t[0] == pytest.approx(0.010004)
    assert log.t[-1] == pytest.approx(25.79)
    assert log.sample_rate == pytest.approx(100.0, rel=0.01)
    # +-9 mV of induced emf, not +-9 V
    assert "mV" in log.meta["voltage_unit"]
    assert abs(log.v).max() < 0.02


def test_the_adc_step_identifies_millivolts_when_the_span_is_small():
    """A log inside +-6 V either way is settled by the ADS1115 step size."""
    steps = np.arange(-120, 121) * 0.03125  # GAIN_FOUR: 31.25 uV = 0.03125 mV
    text = "\n".join(f"{i * 0.01:.2f},{v:.5f}" for i, v in enumerate(steps))
    log = parse_voltage_text(text)
    assert "mV" in log.meta["voltage_unit"]
    assert abs(log.v).max() == pytest.approx(0.00375)


def test_a_genuine_volt_log_is_left_alone():
    rng = np.random.default_rng(3)
    values = rng.uniform(-2.5, 2.5, 300)  # continuous, no ADC-looking step
    text = "\n".join(f"{i * 0.01:.2f},{v:.6f}" for i, v in enumerate(values))
    log = parse_voltage_text(text)
    assert "V" in log.meta["voltage_unit"] and "mV" not in log.meta["voltage_unit"]
    assert abs(log.v).max() > 1.0


def test_a_fully_reversed_file_is_sorted_rather_than_gutted():
    text = "\n".join(f"{(100 - i) * 0.01:.2f},{i}" for i in range(100))
    log = parse_voltage_text(text)
    assert len(log) == 100
    assert np.all(np.diff(log.t) > 0)
