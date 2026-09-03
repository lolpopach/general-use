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
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "lines.linewidth": 1.4,
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
}

C_DISTANCE = "#1f4e79"
C_SPEED = "#2e7d32"
C_VOLTAGE = "#b3261e"
C_RATIO = "#6a1b9a"


def _mark(ax, t: float, color: str, label: str | None = None) -> None:
    ax.axvline(t, color=color, ls="--", lw=0.9, alpha=0.8, zorder=0, label=label)


def figure_motion_and_voltage(
    synced: Synced,
    title: str | None = None,
    mark_peaks: bool = True,
):
    """Fig. 2 -- distance, speed and induced voltage on a common time axis."""
    stats = summarize(synced)
    with plt.rc_context(PAPER_STYLE):
        fig, axes = plt.subplots(3, 1, figsize=(6.5, 6.4), sharex=True)
        ax_d, ax_v, ax_e = axes

        if synced.distance is not None:
            ax_d.plot(synced.t, synced.distance * 1e3, color=C_DISTANCE)
            ax_d.set_ylabel("distance to coil\n(mm)")
        else:
            ax_d.text(
                0.5,
                0.5,
                "no coil position set",
                ha="center",
                va="center",
                transform=ax_d.transAxes,
                color="0.5",
            )
            ax_d.set_ylabel("distance to coil")

        ax_v.plot(synced.t, synced.speed, color=C_SPEED)
        ax_v.set_ylabel("speed\n(m/s)")

        ax_e.plot(synced.t, synced.voltage * 1e3, color=C_VOLTAGE)
        ax_e.axhline(0, color="0.75", lw=0.7, zorder=0)
        ax_e.set_ylabel("induced voltage\n(mV)")
        ax_e.set_xlabel("time (s)")

        if mark_peaks and stats:
            for ax in axes:
                _mark(ax, stats["t_max_speed_s"], C_SPEED)
                _mark(ax, stats["t_max_abs_voltage_s"], C_VOLTAGE)
            ax_v.annotate(
                f"max speed\n{stats['t_max_speed_s']:.2f} s",
                xy=(stats["t_max_speed_s"], stats["max_speed_m_s"]),
                xytext=(4, -2),
                textcoords="offset points",
                color=C_SPEED,
                fontsize=8,
                va="top",
            )
            ax_e.annotate(
                f"max |emf|\n{stats['t_max_abs_voltage_s']:.2f} s",
                xy=(
                    stats["t_max_abs_voltage_s"],
                    np.sign(stats["voltage_at_max_speed_mV"] or 1)
                    * stats["max_abs_voltage_mV"],
                ),
                xytext=(4, 0),
                textcoords="offset points",
                color=C_VOLTAGE,
                fontsize=8,
                va="center",
            )

        for label, ax in zip("abc", axes):
            ax.text(
                -0.13, 1.02, f"({label})", transform=ax.transAxes, fontweight="bold"
            )
        if title:
            fig.suptitle(title, y=0.98)
        fig.align_ylabels(axes)
        fig.tight_layout()
    return fig


def figure_emf_over_velocity(synced: Synced, title: str | None = None):
    """Fig. 3 -- the induced emf together with E/v (proportional to -N dPhi/dx)."""
    with plt.rc_context(PAPER_STYLE):
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        ax.plot(synced.t, synced.voltage * 1e3, color=C_VOLTAGE, label=r"$\mathcal{E}$")
        ax.axhline(0, color="0.75", lw=0.7, zorder=0)
        ax.set_xlabel("time (s)")
        ax.set_ylabel(r"induced voltage $\mathcal{E}$ (mV)", color=C_VOLTAGE)
        ax.tick_params(axis="y", colors=C_VOLTAGE)

        ax2 = ax.twinx()
        ax2.spines["right"].set_visible(True)
        ax2.plot(
            synced.t,
            synced.emf_over_v * 1e3,
            color=C_RATIO,
            ls="-",
            alpha=0.9,
            label=r"$\mathcal{E}/v$",
        )
        ax2.set_ylabel(
            r"$\mathcal{E}/v \;\propto\; -N\,d\Phi/dx$  (mV$\cdot$s/m)", color=C_RATIO
        )
        ax2.tick_params(axis="y", colors=C_RATIO)

        handles = ax.get_lines()[:1] + ax2.get_lines()[:1]
        ax.legend(handles, [h.get_label() for h in handles], loc="upper right")
        if synced.v_min > 0:
            ax.text(
                0.01,
                0.02,
                f"$\\mathcal{{E}}/v$ hidden where $v < {synced.v_min:.3f}$ m/s",
                transform=ax.transAxes,
                fontsize=8,
                color="0.4",
            )
        if title:
            ax.set_title(title)
        fig.tight_layout()
    return fig


def figure_diagnostics(track: Track, led_threshold: float | None = None):
    """Sanity check: detection rate, blob area and the LED marker trace."""
    with plt.rc_context(PAPER_STYLE):
        nrows = 3 if track.led is not None else 2
        fig, axes = plt.subplots(nrows, 1, figsize=(6.5, 2.1 * nrows), sharex=True)
        axes = np.atleast_1d(axes)

        axes[0].plot(track.frame, track.x, ".", ms=3, color=C_DISTANCE, label="x (px)")
        axes[0].plot(track.frame, track.y, ".", ms=3, color=C_SPEED, label="y (px)")
        axes[0].set_ylabel("centroid (px)")
        axes[0].legend(loc="upper right", ncol=2)

        axes[1].plot(track.frame, track.area, color="0.35")
        axes[1].set_ylabel("blob area (px)")
        missing = ~track.found
        if missing.any():
            axes[1].plot(
                track.frame[missing],
                np.zeros(missing.sum()),
                "x",
                color=C_VOLTAGE,
                ms=4,
                label="not detected",
            )
            axes[1].legend(loc="upper right")

        if track.led is not None:
            axes[2].plot(track.frame, track.led, color="#e08a00")
            if led_threshold is not None and np.isfinite(led_threshold):
                axes[2].axhline(led_threshold, color="0.5", ls="--", lw=0.8)
            axes[2].set_ylabel("LED level")
        axes[-1].set_xlabel("frame")
        fig.align_ylabels(axes)
        fig.tight_layout()
    return fig


def save_figure(fig, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
