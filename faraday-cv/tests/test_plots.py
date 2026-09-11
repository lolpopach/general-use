"""Figure rendering: the parts that quietly go wrong (fonts, empty inputs)."""

from __future__ import annotations

import warnings

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pytest

from faradaycv.analysis import Synced
from faradaycv.plots import (
    C_DISTANCE,
    C_SPEED,
    C_VOLTAGE,
    PAPER_STYLE,
    _shade_spans,
    detail_window,
    figure_emf_over_velocity,
    figure_motion_and_voltage,
    font_stack,
    needs_cjk_font,
    save_figure,
)


@pytest.mark.parametrize(
    "mask, expected",
    [
        ([0, 0, 1, 1, 1, 0, 0], [(1.5, 4.5)]),
        ([1, 1, 0, 0, 1, 1, 0], [(-0.5, 1.5), (3.5, 5.5)]),  # run at the start
        ([0, 0, 1, 1, 0, 1, 1], [(1.5, 3.5), (4.5, 6.5)]),  # run at the end
        ([1, 1, 1, 1, 1, 1, 1], [(-0.5, 6.5)]),
        ([0, 0, 0, 1, 0, 0, 0], [(2.5, 3.5)]),  # one sample must still show
        ([1, 0, 1, 0, 1, 0, 1], [(-0.5, 0.5), (1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]),
        ([0, 0, 0, 0, 0, 0, 0], []),
    ],
)
def test_shading_marks_exactly_the_runs_it_is_given(mask, expected):
    """The floored stretches are marked on the figure, so the shading has to
    land on the right samples -- an off-by-one here mislabels which points are
    E/v and which are E/v_min."""
    fig, ax = plt.subplots()
    try:
        _shade_spans(ax, np.arange(7, dtype=float), np.array(mask, bool))
        got = [(p.get_x(), p.get_x() + p.get_width()) for p in ax.patches]
        assert [(pytest.approx(a), pytest.approx(b)) for a, b in got] == expected
    finally:
        plt.close(fig)


def _synced(n=200):
    return _synced_over(2.0, n)


def _synced_over(duration, n=None):
    """A swinging record of any length, so the close-up rules can be tested."""
    n = n if n is not None else int(200 * duration)
    t = np.linspace(0, duration, n)
    speed = 0.5 * np.abs(np.sin(2 * np.pi * t))
    voltage = 0.01 * np.sin(4 * np.pi * t)
    return Synced(
        t=t,
        voltage=voltage,
        speed=speed,
        distance=0.05 + 0.2 * np.abs(np.cos(2 * np.pi * t)),
        emf_over_v=np.where(speed > 0.05, voltage / np.maximum(speed, 1e-9), np.nan),
        v_min=0.05,
    )


def test_the_font_stack_starts_with_the_paper_face():
    assert font_stack()[0] == "DejaVu Serif"
    assert PAPER_STYLE["font.family"] == font_stack()


def test_ascii_captions_never_need_a_fallback_font():
    assert not needs_cjk_font("Swing 1", None, "")


def test_a_korean_title_renders_without_missing_glyph_warnings():
    """Korean is the UI language, so Korean titles must not come out as boxes."""
    title = "진자 스윙 - 유도전압"
    if needs_cjk_font(title):
        pytest.skip("no Hangul-capable font installed on this machine")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig = figure_motion_and_voltage(_synced(), title=title)
        fig.canvas.draw()
        plt.close(fig)
    missing = [w for w in caught if "missing from font" in str(w.message)]
    assert not missing, f"tofu boxes in the figure: {missing[:3]}"


def test_figures_save_at_publication_size(tmp_path):
    path = save_figure(figure_emf_over_velocity(_synced()), tmp_path / "fig3.png")
    assert path.stat().st_size > 10_000
    assert not plt.get_fignums(), "save_figure must close the figure it wrote"


def test_a_run_without_a_coil_still_draws_speed_and_voltage():
    """No coil clicked means no distance curve -- but the two series that do
    not need one must still be drawn, and the axis must not promise a distance
    it is not showing."""
    synced = _synced()
    synced.distance = None
    fig = figure_motion_and_voltage(synced)
    labels = [ax.get_ylabel() for ax in fig.axes]
    plt.close(fig)
    assert "Speed (cm/s)" in labels
    assert "Induced voltage (mV)" in labels
    assert not any("Distance" in label for label in labels)


def test_the_axes_are_the_papers_units_not_si():
    """The figures replace the paper's, so they carry the paper's units --
    centimetres and millivolts.  Drifting back to mm/(m/s) would make every
    number on the figure disagree with the text around it."""
    synced = _synced()
    fig = figure_motion_and_voltage(synced)
    labels = [ax.get_ylabel() for ax in fig.axes]
    drawn = fig.axes[0].get_lines()[0].get_ydata()
    plt.close(fig)
    assert labels == ["Distance (cm)", "Speed (cm/s)", "Induced voltage (mV)"]
    assert np.allclose(drawn, synced.distance * 100)


def test_every_quantity_gets_its_own_axis_in_its_own_colour():
    """Three scales means three sets of ticks, and the only thing saying which
    belongs to which curve is the colour -- so the spine, the ticks and the
    label all have to carry their series' colour, and the two extra axes have
    to stand clear of the frame instead of on top of each other."""
    fig = figure_motion_and_voltage(_synced())
    by_label = {ax.get_ylabel(): ax for ax in fig.axes}
    curves = {
        "Distance (cm)": C_DISTANCE,
        "Speed (cm/s)": C_SPEED,
        "Induced voltage (mV)": C_VOLTAGE,
    }
    offsets = []
    for label, color in curves.items():
        ax = by_label[label]
        side = "left" if ax.yaxis.get_ticks_position() == "left" else "right"
        assert ax.yaxis.label.get_color() == color, label
        assert ax.spines[side].get_edgecolor() == mcolors.to_rgba(color), label
        if side == "right":
            offsets.append(ax.spines["right"].get_position())
    plt.close(fig)
    assert len(offsets) == 2, "speed and voltage each need their own right axis"
    assert len(set(offsets)) == 2, "the two right axes sit on the same line"


def test_without_a_coil_the_speed_takes_the_left_axis():
    """Two series need two axes, not three with an empty one on the left."""
    synced = _synced()
    synced.distance = None
    fig = figure_motion_and_voltage(synced)
    labels = [ax.get_ylabel() for ax in fig.axes]
    left = [ax for ax in fig.axes if ax.yaxis.get_ticks_position() == "left"]
    plt.close(fig)
    assert labels == ["Speed (cm/s)", "Induced voltage (mV)"]
    assert [ax.get_ylabel() for ax in left] == ["Speed (cm/s)"]


def test_the_voltage_axis_is_symmetric_so_zero_sits_mid_height():
    """A bipolar signal drawn on a lopsided axis reads as though one half
    swing were bigger than the other."""
    synced = _synced()
    fig = figure_motion_and_voltage(synced)
    right = [ax for ax in fig.axes if ax.get_ylabel() == "Induced voltage (mV)"][0]
    lo, hi = right.get_ylim()
    plt.close(fig)
    assert lo == pytest.approx(-hi)


def test_the_legend_sits_below_the_axes_where_it_covers_nothing():
    """An opaque legend box inside the axes hides exactly the peak the reader
    came for, and a symmetric voltage axis cannot be stretched far enough to
    get out from under it -- so it has to live below the frame."""
    fig = figure_motion_and_voltage(_synced())
    fig.canvas.draw()
    ax = fig.axes[0]
    legend = ax.get_legend()
    labels = [text.get_text() for text in legend.get_texts()]
    box = legend.get_window_extent()
    frame = ax.get_window_extent()
    plt.close(fig)
    assert box.y1 <= frame.y0, "the legend overlaps the plotting area"
    assert "Magnet speed (cm/s)" in labels


@pytest.mark.parametrize(
    "duration, expected",
    [
        (2.0, None),  # shorter than one window: nothing to zoom into
        (3.0, None),  # still inside the margin
        (10.0, "window"),
    ],
)
def test_a_long_record_asks_for_a_close_up_and_a_short_one_does_not(duration, expected):
    synced = _synced_over(duration)
    got = detail_window(synced, seconds=3.0)
    if expected is None:
        assert got is None
        return
    lo, hi = got
    assert hi - lo == pytest.approx(3.0)
    assert lo >= synced.t[0] and hi <= synced.t[-1]
    # centred on the strongest emf peak, which is what the window is for
    peak = synced.t[int(np.argmax(np.abs(synced.voltage)))]
    assert lo <= peak <= hi


def test_a_close_up_near_the_start_is_pushed_inside_the_record():
    """argmax at the first sample would otherwise ask for a window that
    begins before the record does."""
    synced = _synced_over(10.0)
    synced.voltage = np.zeros_like(synced.voltage)
    synced.voltage[0] = 1.0  # peak at the very first sample
    lo, hi = detail_window(synced, seconds=3.0)
    assert lo == pytest.approx(synced.t[0])
    assert hi == pytest.approx(synced.t[0] + 3.0)


def test_a_close_up_near_the_end_is_pushed_inside_the_record():
    synced = _synced_over(10.0)
    synced.voltage = np.zeros_like(synced.voltage)
    synced.voltage[-1] = 1.0
    lo, hi = detail_window(synced, seconds=3.0)
    assert hi == pytest.approx(synced.t[-1])
    assert lo == pytest.approx(synced.t[-1] - 3.0)


@pytest.mark.parametrize("maker", [figure_motion_and_voltage, figure_emf_over_velocity])
def test_a_window_draws_only_that_slice(maker):
    """The close-up has to actually cut the data, not just rescale the axes --
    an autoscaled y on the whole record would flatten the very peaks the
    close-up exists to show."""
    synced = _synced_over(10.0)
    fig = maker(synced, window=(4.0, 7.0))
    x0, x1 = fig.axes[0].get_xlim()
    spans = [
        line.get_xdata()
        for ax in fig.axes
        for line in ax.get_lines()
        if len(line.get_xdata()) > 2
    ]
    plt.close(fig)
    assert spans, "the figure drew no data at all"
    assert (x0, x1) == pytest.approx((4.0, 7.0), abs=0.05)
    for xs in spans:
        assert xs.min() >= 4.0 and xs.max() <= 7.0
