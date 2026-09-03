"""Figure rendering: the parts that quietly go wrong (fonts, empty inputs)."""

from __future__ import annotations

import warnings

import matplotlib.pyplot as plt
import numpy as np
import pytest

from faradaycv.analysis import Synced
from faradaycv.plots import (
    PAPER_STYLE,
    figure_emf_over_velocity,
    figure_motion_and_voltage,
    font_stack,
    needs_cjk_font,
    save_figure,
)


def _synced(n=200):
    t = np.linspace(0, 2, n)
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


def test_a_run_without_a_coil_still_draws_the_other_panels(tmp_path):
    synced = _synced()
    synced.distance = None
    fig = figure_motion_and_voltage(synced)
    labels = [ax.get_ylabel() for ax in fig.axes]
    plt.close(fig)
    assert any("speed" in label for label in labels)
    assert any("voltage" in label for label in labels)
