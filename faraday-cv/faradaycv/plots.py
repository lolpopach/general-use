"""Publication-style figures: the paper's Fig. 2 and Fig. 3.

Fig. 2 puts distance, speed and induced voltage on one time axis so that the
two dashed markers -- maximum speed and maximum |emf| -- can be seen not to
coincide.  Fig. 3 adds E/v, which by Eq. (3) tracks -N dPhi/dx.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .analysis import Synced, summarize  # noqa: E402
from .track import Track  # noqa: E402

#: Fonts that carry Hangul glyphs, best first.  Matplotlib only falls back
#: glyph by glyph when ``font.family`` is an explicit list of families (the
#: generic "serif" alias does not chain), so the style below builds one -- that
#: is what keeps a Korean title from rendering as a row of boxes while Latin
#: text and the maths still come from DejaVu Serif.
CJK_FONT_CANDIDATES = (
    "Noto Serif CJK KR",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "NanumMyeongjo",
    "NanumGothic",
    "Malgun Gothic",  # Windows
    "AppleGothic",  # macOS
    "Apple SD Gothic Neo",
    "Source Han Sans KR",
    "UnDotum",
    "WenQuanYi Zen Hei",
    "Unifont",
)

#: Syllables a font must actually contain to count as Korean-capable.  Being
#: named like a CJK font is not enough -- several cover Chinese only.
_HANGUL_PROBE = "가힣한글"


@lru_cache(maxsize=None)
def _charmap(family: str) -> frozenset[int]:
    """Code points a font family can draw, empty if it is not installed."""
    from matplotlib import font_manager
    from matplotlib.ft2font import FT2Font

    try:
        path = font_manager.findfont(family, fallback_to_default=False)
        return frozenset(FT2Font(path).get_charmap())
    except Exception:
        return frozenset()


@lru_cache(maxsize=1)
def available_cjk_fonts() -> tuple[str, ...]:
    """Installed families that really can draw Hangul, in preference order."""
    return tuple(
        name
        for name in CJK_FONT_CANDIDATES
        if all(ord(ch) in _charmap(name) for ch in _HANGUL_PROBE)
    )


def font_stack() -> list[str]:
    """DejaVu Serif for the Latin text and maths, then Hangul fallbacks."""
    return ["DejaVu Serif", *available_cjk_fonts()]


def needs_cjk_font(*texts: str | None) -> bool:
    """True when a caption needs characters no installed font can draw."""
    wanted = {ord(ch) for text in texts if text for ch in text if not ch.isascii()}
    if not wanted:
        return False
    covered: set[int] = set()
    for family in font_stack():
        covered |= _charmap(family)
    return not wanted.issubset(covered)


PAPER_STYLE = {
    "font.family": font_stack(),
    "mathtext.fontset": "dejavuserif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "axes.linewidth": 0.9,
    "axes.edgecolor": "0.35",
    "axes.spines.top": True,
    "axes.spines.right": True,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "0.87",
    "grid.linestyle": "--",
    "grid.linewidth": 0.7,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.frameon": True,
    "legend.edgecolor": "0.8",
    "legend.framealpha": 0.95,
    "legend.fontsize": 9,
    "lines.linewidth": 1.4,
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
}

# Three series on one time axis, and one of them is red: a plain red/green
# pair is invisible to a deuteranope (CVD delta-E 2.9, well under the 8 the
# check wants).  The darker green below clears it at 8.3, and the speed curve
# is dotted on top of that, so identity never rests on hue alone.
C_DISTANCE = "#1f77b4"
C_SPEED = "#1b7837"
C_VOLTAGE = "#e8000b"
C_RATIO = "#1a4fd6"

#: A little air above the tallest curve, so a peak does not sit on the spine.
_HEADROOM = 1.12


def _legend_below(ax, handles, y: float = -0.17) -> None:
    """One row of keys under the axes.

    A legend box inside the axes is the usual place for it, but a bipolar
    signal on a symmetric axis peaks near the top on the right-hand side --
    exactly where the box goes -- and no amount of stretching the scale moves
    the peak out from under it (a symmetric axis stretched by r only pushes
    the peak to 0.5 + 0.5/r).  Below the axes nothing is ever covered.
    """
    ax.legend(
        handles,
        [h.get_label() for h in handles],
        loc="upper center",
        bbox_to_anchor=(0.5, y),
        ncol=len(handles),
        frameon=False,
        columnspacing=1.6,
        handlelength=2.2,
    )


#: Where each extra right-hand axis stands, in points outward from the frame.
_AXIS_OFFSETS = (34, 96)


def _extra_axis(ax, outward: float = 0.0):
    """A new y axis on its own spine, ``outward`` points clear of the frame.

    Stepping each one out keeps two sets of ticks off the same line and leaves
    the plot frame itself unpainted by any single series.  Only the base axes
    draws the grid -- three overlaid grids on three different scales is a
    moire, not a guide.
    """
    twin = ax.twinx()
    twin.grid(False)
    twin.patch.set_visible(False)  # so the curves below stay visible
    twin.spines["right"].set_visible(True)
    if outward:
        twin.spines["right"].set_position(("outward", outward))
    return twin


def _own_axis(ax, label: str, color: str) -> None:
    """Paint an axis in its series' colour, label and spine together.

    With a scale per quantity the reader has to be able to tell at a glance
    which ticks belong to which curve, and the colour is what says so.
    """
    ax.set_ylabel(label, color=color)
    ax.tick_params(axis="y", colors=color)
    side = "left" if ax.yaxis.get_ticks_position() == "left" else "right"
    ax.spines[side].set_color(color)


def _mark(ax, t: float, color: str, label: str | None = None) -> None:
    ax.axvline(t, color=color, ls="--", lw=1.0, alpha=0.75, zorder=1, label=label)


def _window_mask(t: np.ndarray, window: tuple[float, float] | None):
    """Index the samples inside ``window``; everything when it is None."""
    if window is None:
        return slice(None)
    lo, hi = window
    return (t >= lo) & (t <= hi)


def detail_window(
    synced: Synced, seconds: float = 3.0, margin: float = 1.25
) -> tuple[float, float] | None:
    """A ``seconds``-long slice around the strongest |emf| peak, or None.

    Ten swings drawn at figure width are a picket fence: the curves cross so
    often that the one thing the figure exists to show -- that the speed peak
    and the emf peak fall at different instants -- stops being visible.  The
    paper's figures show three periods, so a long record gets a second, zoomed
    copy of each figure.  None means the record is already short enough to be
    read whole, and no zoom is worth a second file.
    """
    t = np.asarray(synced.t, dtype=float)
    if t.size < 2 or (t[-1] - t[0]) <= seconds * margin:
        return None
    centre = float(t[int(np.nanargmax(np.abs(synced.voltage)))])
    lo, hi = centre - 0.5 * seconds, centre + 0.5 * seconds
    if lo < t[0]:
        lo, hi = float(t[0]), float(t[0]) + seconds
    if hi > t[-1]:
        lo, hi = float(t[-1]) - seconds, float(t[-1])
    return (lo, hi)


def figure_motion_and_voltage(
    synced: Synced,
    title: str | None = None,
    mark_peaks: bool = True,
    window: tuple[float, float] | None = None,
):
    """Fig. 2 -- distance, speed and induced voltage on a common time axis.

    One time axis and a y axis per quantity: distance on the left, then speed
    and the induced voltage on their own spines stepped out to the right, each
    in its series' colour so there is never a question which ticks belong to
    which curve.  Three scales let every curve use the full height of the
    figure, which is what makes the point of the experiment visible -- the
    speed maximum and the |emf| maximum are plainly not at the same instant.

    The cost of separate scales is that vertical position no longer compares
    between curves: only the shapes and the timing do.
    """
    stats = summarize(synced)
    sel = _window_mask(synced.t, window)
    t = synced.t[sel]
    speed = synced.speed[sel] * 100  # cm/s
    voltage = synced.voltage[sel] * 1e3  # mV
    distance = synced.distance[sel] * 100 if synced.distance is not None else None

    with plt.rc_context(PAPER_STYLE):
        fig, ax = plt.subplots(figsize=(9.0, 4.6))
        handles = []

        if distance is not None:
            handles.append(
                ax.plot(
                    t, distance, color=C_DISTANCE, lw=1.9, label="Distance to coil (cm)"
                )[0]
            )
            _own_axis(ax, "Distance (cm)", C_DISTANCE)
            lo, hi = float(np.nanmin(distance)), float(np.nanmax(distance))
            ax.set_ylim(lo - 0.12 * (hi - lo), hi + 0.12 * (hi - lo))
            ax_speed = _extra_axis(ax, _AXIS_OFFSETS[0])
        else:
            ax_speed = ax  # nothing to put on the left but the speed itself

        # Dotted, not just green: red and green are the one pair a red-green
        # colour blindness flattens, and this is the curve that has to stay
        # apart from the voltage.
        handles.append(
            ax_speed.plot(
                t, speed, color=C_SPEED, lw=2.1, ls=":", label="Magnet speed (cm/s)"
            )[0]
        )
        _own_axis(ax_speed, "Speed (cm/s)", C_SPEED)
        ax_speed.set_ylim(0, float(np.nanmax(speed)) * 1.08 if speed.size else 1.0)

        ax_volt = _extra_axis(ax, _AXIS_OFFSETS[1] if distance is not None else 0)
        handles.append(
            ax_volt.plot(
                t, voltage, color=C_VOLTAGE, lw=1.9, label="Induced voltage (mV)"
            )[0]
        )
        ax_volt.axhline(0, color="0.6", lw=0.9, zorder=1)
        _own_axis(ax_volt, "Induced voltage (mV)", C_VOLTAGE)
        # Symmetric, so the zero line sits at mid-height and a positive half
        # swing is not drawn larger than the negative one it mirrors.
        span = float(np.nanmax(np.abs(voltage))) if voltage.size else 1.0
        ax_volt.set_ylim(-span * 1.08, span * 1.08)

        ax.set_xlabel("Time (s)")
        if t.size:
            ax.set_xlim(float(t[0]), float(t[-1]))

        if mark_peaks and stats:
            for key, color, label in (
                ("t_max_speed_s", C_SPEED, "Peak speed"),
                ("t_max_abs_voltage_s", C_VOLTAGE, "Peak |emf|"),
            ):
                when = stats[key]
                if t.size and t[0] <= when <= t[-1]:
                    _mark(ax, when, color, label=label)
                    handles.append(ax.get_lines()[-1])

        ax.set_title(title or "Distance, Speed, and Induced Voltage vs Time")
        _legend_below(ax, handles)
        fig.tight_layout()
    return fig


def figure_emf_over_velocity(
    synced: Synced,
    title: str | None = None,
    window: tuple[float, float] | None = None,
):
    """Fig. 3 -- the induced emf together with E/v (proportional to -N dPhi/dx).

    Both curves on one time axis, each with its own scale: dividing out the
    speed is supposed to leave the flux gradient behind, and the figure earns
    its place by letting the reader see how far that holds.
    """
    sel = _window_mask(synced.t, window)
    t = synced.t[sel]
    voltage = synced.voltage[sel] * 1e3  # mV
    ratio = synced.emf_over_v[sel] * 10  # (V.s/m) -> mV.s/cm
    clamped = synced.clamped[sel] if synced.clamped is not None else None

    with plt.rc_context(PAPER_STYLE):
        fig, ax = plt.subplots(figsize=(8.6, 4.6))

        # Shade the turning points, where the floor stands in for v: the curve
        # is continuous there but it is E/v_min, not E/v.  Saying so on the
        # figure is the price of not leaving the trace full of holes.
        if clamped is not None and clamped.any():
            _shade_spans(ax, t, clamped)

        line_e = ax.plot(
            t,
            voltage,
            color=C_VOLTAGE,
            lw=1.9,
            label=r"Induced voltage $\mathcal{E}$ (mV)",
        )[0]
        ax.axhline(0, color="0.6", lw=0.9, zorder=1)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(r"Induced voltage $\mathcal{E}$ (mV)", color=C_VOLTAGE)
        ax.tick_params(axis="y", colors=C_VOLTAGE)
        span = float(np.nanmax(np.abs(voltage))) if voltage.size else 1.0
        ax.set_ylim(-span * _HEADROOM, span * _HEADROOM)
        if t.size:
            ax.set_xlim(float(t[0]), float(t[-1]))

        ax2 = ax.twinx()
        ax2.grid(False)
        line_r = ax2.plot(
            t,
            ratio,
            color=C_RATIO,
            lw=1.9,
            label=r"$\mathcal{E}/v \;\propto\; -N\,d\Phi/dx$",
        )[0]
        ax2.set_ylabel(r"$\mathcal{E}/v$ (mV$\cdot$s/cm)", color=C_RATIO)
        ax2.tick_params(axis="y", colors=C_RATIO)
        if np.isfinite(ratio).any():
            lo, hi = float(np.nanmin(ratio)), float(np.nanmax(ratio))
            pad = 0.06 * (hi - lo) or 1.0
            ax2.set_ylim(lo - pad, hi + pad)

        ax.set_title(
            title or r"Comparison of induced voltage $\mathcal{E}$ and $\mathcal{E}/v$"
        )
        _legend_below(ax, [line_e, line_r])
        if synced.v_min > 0 and clamped is not None and clamped.any():
            ax.text(
                0.0,
                -0.34,
                f"Shaded: turning points where $v < {synced.v_min * 100:.1f}$ cm/s; "
                r"there $v$ is held at that floor so $\mathcal{E}/v$ stays finite.",
                transform=ax.transAxes,
                fontsize=8.5,
                color="0.40",
            )
        fig.tight_layout()
    return fig


def _shade_spans(ax, t: np.ndarray, mask: np.ndarray) -> None:
    """Shade every run of True in `mask` as a band on `ax`.

    Bands are widened by half a sample at each end so that a run of a single
    sample -- which a turning point often is -- is still wide enough to see.
    """
    mask = np.asarray(mask, bool)
    if not mask.any():
        return
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1  # index of the last True in the run
    half = 0.5 * float(np.median(np.diff(t))) if t.size > 1 else 0.0
    for a, b in zip(starts, ends):
        ax.axvspan(t[a] - half, t[b] + half, color="0.88", zorder=0, lw=0)


def figure_diagnostics(track: Track, led_threshold: float | None = None):
    """Sanity check: detection rate, blob area and the LED marker trace."""
    with plt.rc_context(PAPER_STYLE):
        nrows = 3 if track.led is not None else 2
        fig, axes = plt.subplots(nrows, 1, figsize=(6.5, 2.1 * nrows), sharex=True)
        axes = np.atleast_1d(axes)

        # Video seconds, not frame index: the LED may have been sampled over a
        # different stretch than the magnet was tracked over (the browser reads
        # it from the top of the clip even when the analysis range starts
        # later), and only a real time axis lines those two up honestly.
        axes[0].plot(track.t, track.x, ".", ms=3, color=C_DISTANCE, label="x (px)")
        axes[0].plot(track.t, track.y, ".", ms=3, color=C_SPEED, label="y (px)")
        axes[0].set_ylabel("centroid (px)")
        axes[0].margins(y=0.28)  # keep the legend off the traces
        axes[0].legend(loc="upper right", ncol=2)

        axes[1].plot(track.t, track.area, color="0.35")
        axes[1].set_ylabel("blob area (px)")
        missing = ~track.found
        if missing.any():
            axes[1].plot(
                track.t[missing],
                np.zeros(missing.sum()),
                "x",
                color=C_VOLTAGE,
                ms=4,
                label="not detected",
            )
            axes[1].legend(loc="upper right")

        if track.led is not None:
            led_t = track.led_t if track.led_t is not None else track.t
            axes[2].plot(led_t, track.led, color="#e08a00")
            if led_threshold is not None and np.isfinite(led_threshold):
                axes[2].axhline(led_threshold, color="0.5", ls="--", lw=0.8)
            axes[2].set_ylabel("LED level")
        axes[-1].set_xlabel("video time (s)")
        fig.align_ylabels(axes)
        fig.tight_layout()
    return fig


def save_figure(fig, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
