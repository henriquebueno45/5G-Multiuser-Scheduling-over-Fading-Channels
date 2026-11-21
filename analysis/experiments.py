"""Resumable experiment driver: policy x load x antennas x seed.

Each run appends per-class rows to results/<name>_class.csv and per-user rows to
results/<name>_user.csv. Finished (policy, load, antennas, seed) jobs are skipped on re-run, so an
interrupted sweep can simply be restarted with the same command.

Example:
    python -m analysis.experiments --name smoke --seeds 3 --duration 5
    python -m analysis.experiments --name main --seeds 30 --workers 6
"""
from __future__ import annotations

import argparse
import itertools
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from sim.run import POLICY_NAMES, simulate

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
LOADS = [0.2, 0.4, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 2.0]
ANTENNAS = [1, 2, 4]
KEY = ["policy", "load", "antennas", "seed"]


def _job(args):
    policy, load, antennas, seed, duration = args
    pc, pu, _ = simulate(policy, load, seed, antennas, duration_s=duration)
    meta = {"policy": policy, "load": load, "antennas": antennas, "seed": seed}
    return pc.assign(**meta), pu.assign(**meta)


def _done(path: Path) -> set:
    if not path.exists():
        return set()
    d = pd.read_csv(path, usecols=KEY).drop_duplicates()
    return set(map(tuple, d.itertuples(index=False, name=None)))


def _append(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True, help="output tag")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--policies", nargs="+", default=POLICY_NAMES)
    ap.add_argument("--loads", nargs="+", type=float, default=LOADS)
    ap.add_argument("--antennas", nargs="+", type=int, default=ANTENNAS)
    a = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)
    cpath, upath = RESULTS / f"{a.name}_class.csv", RESULTS / f"{a.name}_user.csv"
    done = _done(cpath)
    jobs = [(p, l, k, s, a.duration)
            for s, l, k, p in itertools.product(range(1, a.seeds + 1), a.loads, a.antennas,
                                                a.policies)
            if (p, l, k, s) not in done]
    print(f"{len(jobs)} jobs to run ({len(done)} already done)", flush=True)
    with Pool(a.workers) as pool:
        for i, (pc, pu) in enumerate(pool.imap_unordered(_job, jobs, chunksize=1), 1):
            _append(pu, upath)
            _append(pc, cpath)  # written last: it marks the job as finished
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
