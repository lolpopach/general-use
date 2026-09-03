"""Reader for the Arduino voltage log (uploaded as its own file).

The sketch in ``arduino/faraday_logger`` writes ``t_ms,voltage_mV`` at about
116 Hz, but student logs arrive in every shape: extra comment lines, a
different column order, seconds instead of milliseconds, volts instead of
millivolts.  This module normalises all of that to seconds and volts.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

_TIME_HINTS = ("t_ms", "time_ms", "millis", "t_us", "micros", "t_s", "time", "t")
_VOLT_HINTS = ("volt", "emf", "v_mv", "mv", "v", "value", "adc")

# The ADS1115 cannot read past +-6.144 V, and its step size (LSB) at each gain
# setting, written in millivolts, is one of these.  Both facts are used to tell
# a millivolt column from a volt one when the file has no header.
ADS1115_FULL_SCALE_V = 6.2
ADS1115_LSB_MV = (0.1875, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125)


@dataclass
class VoltageLog:
    """Voltage record on its own clock: ``t`` in seconds, ``v`` in volts."""

    t: np.ndarray
    v: np.ndarray
    source: str = ""
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.t.size)

    @property
    def sample_rate(self) -> float:
        if len(self) < 2:
            return float("nan")
        dt = float(np.median(np.diff(self.t)))
        return 1.0 / dt if dt > 0 else float("nan")

    def zeroed(self, t0: float = 0.0) -> "VoltageLog":
        """Shift the time axis so that ``t0`` becomes t = 0."""
        return VoltageLog(self.t - t0, self.v, self.source, dict(self.meta))

    def baseline_offset(self, seconds: float = 0.2) -> tuple[float, str]:
        """Estimate the ADC offset, and say where the estimate came from.

        If the record starts quiet -- the magnet had not reached the coil yet --
        the head of the record *is* the zero level.  If it does not (the swing
        was already under way when logging began), the head is a poor estimate
        and the median of the whole record is used instead: an emf that swings
        symmetrically about zero has a median at its offset.
        """
        if len(self) == 0:
            return 0.0, "none"
        overall = float(np.median(self.v))
        head = self.t <= self.t[0] + seconds
        if seconds > 0 and int(head.sum()) >= 5:
            head_std = float(np.std(self.v[head]))
            all_std = float(np.std(self.v))
            if all_std == 0 or head_std < 0.25 * all_std:
                return float(np.median(self.v[head])), f"first {seconds:g} s"
        return overall, "record median"

    def baseline_corrected(self, seconds: float = 0.2) -> "VoltageLog":
        """Remove the ADC offset (see :meth:`baseline_offset`)."""
        if len(self) == 0:
            return self
        offset, how = self.baseline_offset(seconds)
        meta = dict(self.meta)
        meta["baseline_v"] = offset
        meta["baseline_from"] = how
        return VoltageLog(self.t, self.v - offset, self.source, meta)

    def to_dict(self) -> dict:
        return {
            "samples": len(self),
            "sample_rate_hz": self.sample_rate,
            "t_start_s": float(self.t[0]) if len(self) else None,
            "t_end_s": float(self.t[-1]) if len(self) else None,
            "v_min_mV": float(np.min(self.v) * 1e3) if len(self) else None,
            "v_max_mV": float(np.max(self.v) * 1e3) if len(self) else None,
            "source": self.source,
            **self.meta,
        }


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t ").delimiter
    except csv.Error:
        for cand in (",", ";", "\t"):
            if cand in sample:
                return cand
        return " "


def _is_number(token: str) -> bool:
    return bool(_NUMERIC.match(token.strip()))


def _pick_columns(header: list[str] | None, ncols: int) -> tuple[int, int]:
    """Choose (time column, voltage column) from a header row, else 0 and 1."""
    if not header:
        return 0, min(1, ncols - 1)
    low = [h.strip().lower() for h in header]

    def find(hints: tuple[str, ...]) -> int | None:
        for hint in hints:
            for i, name in enumerate(low):
                if hint in name:
                    return i
        return None

    t_col = find(_TIME_HINTS)
    v_col = find(_VOLT_HINTS)
    if t_col is None:
        t_col = 0
    if v_col is None or v_col == t_col:
        v_col = 1 if ncols > 1 and t_col != 1 else min(ncols - 1, t_col + 1)
    return t_col, v_col


def _time_scale(name: str, values: np.ndarray) -> tuple[float, str]:
    """Return the factor that converts the time column to seconds."""
    low = name.lower()
    if "us" in low or "micro" in low:
        return 1e-6, "us"
    if "ms" in low or "milli" in low:
        return 1e-3, "ms"
    if low.endswith("_s") or low in ("t", "time", "time_s", "t_s", "seconds", "sec"):
        return 1.0, "s"
    # No usable header: guess from the median step.  A 100+ Hz logger writing
    # seconds steps by ~0.01; writing milliseconds it steps by ~10.
    if values.size > 2:
        step = float(np.median(np.abs(np.diff(values))))
        if step > 1000:
            return 1e-6, "us (guessed)"
        if step > 1.5:
            return 1e-3, "ms (guessed)"
    return 1.0, "s (guessed)"


def _voltage_scale(
    name: str, values: np.ndarray, unit: str = "auto"
) -> tuple[float, str]:
    """Return the factor that converts the voltage column to volts."""
    if unit == "V":
        return 1.0, "V"
    if unit == "mV":
        return 1e-3, "mV"
    low = name.lower()
    if "mv" in low:
        return 1e-3, "mV"
    if "uv" in low:
        return 1e-6, "uV"
    if re.search(r"(^|[^m])v($|[^a-z])", low) or "volt" in low:
        return 1.0, "V"

    # Nothing in the header to go on.  Two physical arguments decide it:
    span = float(np.max(np.abs(values))) if values.size else 0.0
    if span > ADS1115_FULL_SCALE_V:
        # Beyond what the ADC can read in volts, so the column is millivolts.
        return 1e-3, "mV (guessed)"
    quantum = _quantum(values)
    if quantum is not None and any(
        abs(quantum / lsb - round(quantum / lsb)) < 0.02 and quantum >= lsb * 0.99
        for lsb in ADS1115_LSB_MV
    ):
        # The samples land on multiples of an ADS1115 step *expressed in mV*.
        # The same step read as volts would need a +-1000 V input range.
        return 1e-3, "mV (guessed from the ADC step)"
    return 1.0, "V (guessed)"


def _quantum(values: np.ndarray) -> float | None:
    """Smallest gap between distinct sample values -- the ADC's step size."""
    unique = np.unique(values[np.isfinite(values)])
    if unique.size < 8:
        return None
    gaps = np.diff(unique)
    gaps = gaps[gaps > 1e-12]
    return float(np.min(gaps)) if gaps.size else None


def _monotonic_indices(values: np.ndarray) -> np.ndarray:
    """Indices of the longest strictly increasing run of timestamps.

    A serial log is monotonic by construction, so a timestamp that breaks the
    order is a glitch: a stray line from a previous run, a duplicated flush at
    the end of the capture.  Sorting such a row into place would silently open
    a gap in the record (and stretch its duration), so it is dropped instead.
    """
    n = values.size
    if n == 0:
        return np.empty(0, dtype=int)
    tails: list[int] = []  # index of the smallest tail per run length
    prev = np.full(n, -1, dtype=int)
    for i, x in enumerate(values):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if values[tails[mid]] < x:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            prev[i] = tails[lo - 1]
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    out: list[int] = []
    k = tails[-1]
    while k != -1:
        out.append(k)
        k = int(prev[k])
    return np.asarray(out[::-1], dtype=int)


def parse_voltage_text(
    text: str,
    *,
    source: str = "",
    time_column: int | None = None,
    voltage_column: int | None = None,
    voltage_unit: str = "auto",
) -> VoltageLog:
    """Parse a voltage log from CSV/TSV/whitespace text."""
    lines = [
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", "//", ";;"))
    ]
    if not lines:
        raise ValueError("voltage file contains no data rows")

    delimiter = _sniff_delimiter("\n".join(lines[:20]))
    reader = csv.reader(
        io.StringIO("\n".join(lines)), delimiter=delimiter, skipinitialspace=True
    )
    rows = [[c for c in row if c != ""] for row in reader]
    rows = [r for r in rows if r]
    if not rows:
        raise ValueError("voltage file contains no data rows")

    header: list[str] | None = None
    if not all(_is_number(c) for c in rows[0][:2]):
        header = rows[0]
        rows = rows[1:]
    if not rows:
        raise ValueError("voltage file has a header but no data rows")

    ncols = max(len(r) for r in rows)
    t_col, v_col = _pick_columns(header, ncols)
    if time_column is not None:
        t_col = time_column
    if voltage_column is not None:
        v_col = voltage_column

    t_vals: list[float] = []
    v_vals: list[float] = []
    skipped = 0
    for row in rows:
        if len(row) <= max(t_col, v_col):
            skipped += 1
            continue
        try:
            t_vals.append(float(row[t_col]))
            v_vals.append(float(row[v_col]))
        except ValueError:
            skipped += 1
    if len(t_vals) < 2:
        raise ValueError("voltage file has fewer than 2 usable rows")

    t_raw = np.asarray(t_vals, dtype=float)
    v_raw = np.asarray(v_vals, dtype=float)
    t_name = header[t_col] if header and t_col < len(header) else ""
    v_name = header[v_col] if header and v_col < len(header) else ""
    t_factor, t_unit = _time_scale(t_name, t_raw)
    v_factor, v_unit = _voltage_scale(v_name, v_raw, voltage_unit)

    keep = _monotonic_indices(t_raw)
    if keep.size < 0.5 * t_raw.size:
        # Not a glitch but a genuinely unordered file (a reversed export, say).
        keep = np.argsort(t_raw, kind="stable")
    out_of_order = int(t_raw.size - keep.size)

    return VoltageLog(
        t=t_raw[keep] * t_factor,
        v=v_raw[keep] * v_factor,
        source=source,
        meta={
            "time_column": t_name or t_col,
            "voltage_column": v_name or v_col,
            "time_unit": t_unit,
            "voltage_unit": v_unit,
            "skipped_rows": skipped,
            "out_of_order_rows": out_of_order,
            "delimiter": delimiter,
        },
    )


def load_voltage_csv(path: str | Path, **kwargs) -> VoltageLog:
    path = Path(path)
    return parse_voltage_text(
        path.read_text(encoding="utf-8", errors="replace"),
        source=str(path),
        **kwargs,
    )
