#!/usr/bin/env python3
"""Capture the Arduino serial stream into the CSV the analysis expects.

    python3 tools/serial_logger.py --port /dev/ttyACM0 --out voltage.csv --seconds 20

Needs pyserial (``pip install pyserial``).  Lines are passed through as they
arrive, so the file is exactly what the sketch printed: a few ``#`` comments,
the ``t_ms,voltage_mV`` header, then the samples.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def list_ports() -> int:
    from serial.tools import list_ports as lp

    ports = list(lp.comports())
    if not ports:
        print("no serial ports found")
        return 1
    for port in ports:
        print(f"{port.device:20s} {port.description}")
    return 0


def capture(args) -> int:
    import serial

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    samples = 0

    with (
        serial.Serial(args.port, args.baud, timeout=1) as port,
        out.open("w", encoding="utf-8") as fh,
    ):
        time.sleep(2.0)  # the UNO resets when the port opens
        port.reset_input_buffer()
        if args.start_command:
            port.write(args.start_command.encode())
        print(f"logging from {args.port} -> {out} (ctrl-c to stop)", file=sys.stderr)
        try:
            while deadline is None or time.monotonic() < deadline:
                line = port.readline().decode("utf-8", "replace").strip()
                if not line:
                    continue
                fh.write(line + "\n")
                if not line.startswith("#") and not line[0].isalpha():
                    samples += 1
                    if samples % 100 == 0:
                        print(f"\r{samples} samples", end="", file=sys.stderr)
        except KeyboardInterrupt:
            pass
    print(f"\nwrote {samples} samples to {out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", help="serial port, e.g. /dev/ttyACM0 or COM3")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--out", default="voltage.csv")
    p.add_argument("--seconds", type=float, default=0, help="0 = until ctrl-c")
    p.add_argument("--start-command", default="", help="e.g. 's' if AUTOSTART is off")
    p.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = p.parse_args(argv)

    try:
        if args.list:
            return list_ports()
        if not args.port:
            p.error("--port is required (or use --list)")
        return capture(args)
    except ImportError:
        print("pyserial is not installed: pip install pyserial", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
