"""Per-user traffic: voice (periodic), video (periodic frames), and data (Poisson).

Packets are sized in bits and may be fragmented across slots. Load is expressed relative to the
saturation point of the realization: `load = 1` offers exactly the bits/s that would use every PRB
of the cell if each user were served at its mean bits-per-PRB (`saturation_scale`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CLASSES = ("voice", "video", "data")  # strict-priority order (highest first)


@dataclass(frozen=True)
class ClassSpec:
    name: str
    period_slots: int  # 0 for Poisson arrivals
    packet_bits: float  # bits per packet at load = 1 before scaling
    deadline_slots: int
    poisson_rate: float = 0.0  # packets per slot (data only)

    @property
    def bits_per_slot(self) -> float:
        rate = self.poisson_rate if self.period_slots == 0 else 1.0 / self.period_slots
        return self.packet_bits * rate


# Default profiles: voice 80 kbit/s (20 ms), video 2 Mbit/s (33 ms frames), data 2 Mbit/s Poisson
PROFILES = {
    "voice": ClassSpec("voice", 20, 1_600.0, 20),
    "video": ClassSpec("video", 33, 66_000.0, 50),
    "data": ClassSpec("data", 0, 12_000.0, 500, poisson_rate=2e6 * 1e-3 / 12_000.0),
}


def assign_classes(n_voice: int, n_video: int, n_data: int) -> np.ndarray:
    """Class index (into CLASSES) for each user, voice users first."""
    return np.array([0] * n_voice + [1] * n_video + [2] * n_data, dtype=int)


def saturation_scale(user_class: np.ndarray, mean_bits_per_prb: np.ndarray, n_prbs: int) -> float:
    """Packet-size multiplier that makes the offered load exactly saturate the cell (load = 1)."""
    base = np.array([PROFILES[CLASSES[c]].bits_per_slot for c in user_class])
    prbs_needed_per_slot = float((base / mean_bits_per_prb).sum())
    return n_prbs / prbs_needed_per_slot


@dataclass(frozen=True)
class Arrivals:
    """Packets of one user as parallel arrays sorted by arrival slot."""

    slot: np.ndarray
    bits: np.ndarray


def generate_arrivals(
    n_slots: int, user_class: np.ndarray, scale: float, load: float, seed: int
) -> list[Arrivals]:
    """Draw each user's packet arrivals; per-user streams are independent of the user count."""
    root = np.random.SeedSequence([seed, 1])
    streams = root.spawn(len(user_class))
    out = []
    for c, ss in zip(user_class, streams):
        spec = PROFILES[CLASSES[c]]
        rng = np.random.default_rng(ss)
        bits = spec.packet_bits * scale * load
        if spec.period_slots:
            slots = np.arange(rng.integers(spec.period_slots), n_slots, spec.period_slots)
            sizes = np.full(len(slots), bits)
        else:
            counts = rng.poisson(spec.poisson_rate, n_slots)
            slots = np.repeat(np.arange(n_slots), counts)
            sizes = np.full(len(slots), bits)
        out.append(Arrivals(slots, sizes))
    return out
