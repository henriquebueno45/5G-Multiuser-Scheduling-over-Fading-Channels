"""Tests for the multi-user cell model."""
import numpy as np

from cell.cell import CellConfig, generate_cell, place_users
from channel.channel_model import ChannelConfig


def test_shapes_and_bounds():
    cfg = CellConfig(n_users=6)
    cell = generate_cell(500, cfg, seed=1)
    assert cell.se.shape == (6, 500) and cell.bits_per_prb.shape == (6, 500)
    assert cell.distance_m.min() >= cfg.r_min_m and cell.distance_m.max() <= cfg.r_max_m
    assert cell.se.min() >= 0 and cell.se.max() <= cfg.channel.se_max


def test_deterministic_and_users_independent_of_cell_size():
    a = generate_cell(300, CellConfig(n_users=4), seed=7)
    b = generate_cell(300, CellConfig(n_users=4), seed=7)
    assert np.array_equal(a.se, b.se)
    big = generate_cell(300, CellConfig(n_users=8), seed=7)
    # Per-user streams are spawned independently, so shadowing and fading of user 0 are unchanged
    assert big.shadow_db[0] == a.shadow_db[0]
    assert np.array_equal(big.se[0], a.se[0])


def test_user_channels_are_independent():
    cfg = CellConfig(n_users=2, r_min_m=100, r_max_m=101, channel=ChannelConfig(speed_mps=30.0))
    cell = generate_cell(20_000, cfg, seed=3)
    assert abs(np.corrcoef(cell.se[0], cell.se[1])[0, 1]) < 0.1


def test_farther_users_have_lower_spectral_efficiency_without_randomness():
    ch = ChannelConfig(fading=False, shadow_sigma_db=0.0)
    cell = generate_cell(10, CellConfig(n_users=12, channel=ch), seed=2)
    order = np.argsort(cell.distance_m)
    mean_se = cell.se.mean(axis=1)[order]
    assert np.all(np.diff(mean_se) <= 1e-12)


def test_placement_is_uniform_in_area():
    r = place_users(200_000, 20.0, 300.0, np.random.default_rng(0))
    # Median of r^2 for an area-uniform annulus is the midpoint of (r_min^2, r_max^2)
    assert abs(np.median(r**2) - (20.0**2 + 300.0**2) / 2) / 300.0**2 < 0.01


def test_diversity_raises_mean_spectral_efficiency():
    kw = dict(n_users=20, r_min_m=150, r_max_m=300)
    c1 = generate_cell(2000, CellConfig(channel=ChannelConfig(antennas=1, speed_mps=30.0), **kw), 5)
    c4 = generate_cell(2000, CellConfig(channel=ChannelConfig(antennas=4, speed_mps=30.0), **kw), 5)
    assert c4.se.mean() > c1.se.mean()


def test_static_spectral_efficiency_matches_hand_computed_link_budget():
    # Link budget written out independently of the channel module: free-space loss at 1 m plus
    # 10 n log10(d), thermal noise -174 dBm/Hz + 10 log10(B) + NF, Shannon rate capped at se_max
    ch = ChannelConfig(fading=False, shadow_sigma_db=0.0)
    cfg = CellConfig(n_users=5, channel=ch)
    cell = generate_cell(3, cfg, seed=11)
    for d, se in zip(cell.distance_m, cell.se[:, 0]):
        pl = 20 * np.log10(4 * np.pi * 3.5e9 / 3e8) + 35.0 * np.log10(d)
        noise = -174.0 + 10 * np.log10(360e3) + 7.0
        snr = 10 ** ((23.0 - pl - noise) / 10)
        assert abs(se - min(np.log2(1 + snr), 7.4)) < 1e-3


def _ergodic_se(snr_db: float, antennas: int, se_max: float = 7.4) -> float:
    """E[min(log2(1 + snr G), se_max)] for G ~ Gamma(L, 1) by numerical integration."""
    from math import lgamma
    g = np.linspace(1e-6, 60.0, 400_000)
    pdf = np.exp((antennas - 1) * np.log(g) - g - lgamma(antennas))
    f = np.minimum(np.log2(1 + 10 ** (snr_db / 10) * g), se_max)
    return float(np.sum(f * pdf) * (g[1] - g[0]))


def test_mean_spectral_efficiency_matches_rayleigh_theory():
    # A fast-moving user in Rayleigh fading (L-branch MRC) has ergodic SE = E[log2(1 + snr G)]
    for antennas in (1, 4):
        ch = ChannelConfig(antennas=antennas, shadow_sigma_db=0.0, speed_mps=60.0)
        cfg = CellConfig(n_users=1, r_min_m=150, r_max_m=150.001, channel=ch)
        cell = generate_cell(300_000, cfg, seed=2)
        snr_db = 23.0 - (20 * np.log10(4 * np.pi * 3.5e9 / 3e8)
                         + 35.0 * np.log10(cell.distance_m[0])) - (-174.0 + 10 * np.log10(360e3)
                                                                   + 7.0)
        theory = _ergodic_se(snr_db, antennas)
        assert abs(cell.se.mean() / theory - 1) < 0.03, (antennas, cell.se.mean(), theory)
