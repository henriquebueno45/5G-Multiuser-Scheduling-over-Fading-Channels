"""Equal-mean-PRB calibration (reused from the single-user simulator, tag v1.0)."""
from __future__ import annotations

from scipy.optimize import brentq

from analysis.validate_channel import theory_prbs

TARGET_MEAN_PRBS = 50.0


def equal_mean_distance(antennas: int, target: float = TARGET_MEAN_PRBS) -> float:
    """Distance (m) where the theoretical mean PRBs with MRC and `antennas` branches equals `target`."""
    return float(brentq(lambda d: theory_prbs(d, antennas) - target, 20.0, 2000.0))
