"""Tests for the reused channel model and statistics (copied from the v1.0 reference tests)."""
import numpy as np
import pandas as pd

from analysis.stats import paired_ci, sla_capacity
from analysis.validate_channel import theory_prbs
from channel.calibration import equal_mean_distance
from channel.channel_model import ChannelConfig, generate_prbs, path_loss_db, rayleigh_power_gain


def test_path_loss_slope_matches_exponent():
    cfg = ChannelConfig(path_loss_exp=3.5)
    assert np.isclose(path_loss_db(1000, cfg) - path_loss_db(100, cfg), 35.0)


def test_rayleigh_gain_mean_is_antenna_count():
    rng = np.random.default_rng(0)
    for L in (1, 2, 4):
        g = rayleigh_power_gain(200_000, ChannelConfig(antennas=L, speed_mps=30.0), rng)
        assert abs(g.mean() - L) < 0.1 * L


def test_rayleigh_outage_matches_theory():
    rng = np.random.default_rng(1)
    g = rayleigh_power_gain(200_000, ChannelConfig(speed_mps=30.0), rng)
    assert abs((g < 0.1).mean() - (1 - np.exp(-0.1))) < 0.02


def test_capacity_decreases_with_distance():
    near = generate_prbs(2000, ChannelConfig(distance_m=50, fading=False), seed=3).mean()
    far = generate_prbs(2000, ChannelConfig(distance_m=400, fading=False), seed=3).mean()
    assert near > far


def test_diversity_reduces_deep_fades():
    p1 = generate_prbs(20_000, ChannelConfig(distance_m=300, antennas=1, speed_mps=30.0), seed=5)
    p4 = generate_prbs(20_000, ChannelConfig(distance_m=300, antennas=4, speed_mps=30.0), seed=5)
    assert p4.mean() > p1.mean()


def test_sla_capacity_interpolation_and_censoring():
    loads = np.array([1.0, 2.0, 3.0])
    cap, st = sla_capacity(loads, np.array([1.0, 1.0, 0.90]))
    assert st == "ok" and np.isclose(cap, 2.1)
    assert sla_capacity(loads, np.array([1.0, 1.0, 1.0])) == (3.0, "right")
    assert sla_capacity(loads, np.array([0.5, 0.4, 0.3])) == (1.0, "left")


def test_equal_mean_distance_and_paired_ci():
    d = [equal_mean_distance(L) for L in (1, 2, 4)]
    assert d[0] < d[1] < d[2]
    assert np.isclose(theory_prbs(d[1], 2), 50.0, atol=0.01)
    a = pd.Series([1.0, 1.1, 0.9, 1.2], index=[1, 2, 3, 4])
    m, lo, hi = paired_ci(a + 0.5, a)
    assert np.isclose([m, lo, hi], 0.5).all()
