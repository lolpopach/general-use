"""Shared fixtures: one synthetic dataset, generated once per test session."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faradaycv.synthetic import SyntheticSpec, make_dataset  # noqa: E402


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    """Video + voltage log + ground truth for the pendulum experiment."""
    outdir = tmp_path_factory.mktemp("synthetic")
    return make_dataset(outdir, SyntheticSpec())


@pytest.fixture(scope="session")
def truth(dataset):
    return dataset.ground_truth


@pytest.fixture(scope="session")
def color():
    """The colour box for the synthetic magnet: red, so the hue wraps."""
    from faradaycv.segmentation import ColorRange

    return ColorRange(h_lo=170, h_hi=10, s_lo=120, s_hi=255, v_lo=80, v_hi=255)
