"""Slot-level engine: arrivals -> queues -> policy allocation -> service, with deadline drops.

Each slot t (1 ms): packets arriving at t are queued, packets that can no longer meet their
deadline are dropped, the policy splits the cell's PRBs among users, and each user's PRBs
(`bits_per_prb[u, t]` bits each) drain its FIFO queue, fragmenting packets across slots.
A packet that arrives in slot a and completes in slot t has delay (t - a + 1) slots.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cell.cell import CellRealization
from sim.policies import Policy, SlotState
from sim.traffic import CLASSES, PROFILES, Arrivals


@dataclass
class SimResult:
    packets: pd.DataFrame  # one row per packet: user, cls, arrival, bits, delay_slots, status
    backlogged: np.ndarray  # (n_classes, n_slots) bool: class had queued data
    prbs: np.ndarray  # (n_classes, n_slots) PRBs the class received
    user_class: np.ndarray
    n_slots: int


def run(cell: CellRealization, user_class: np.ndarray, arrivals: list[Arrivals], policy: Policy,
        n_prbs: int, buffer_bits: float | None = None,
        deadline_slots: dict[str, int] | None = None) -> SimResult:
    """Simulate the cell. `buffer_bits` adds a shared tail-drop buffer (an arriving packet is
    dropped if the total backlog would exceed it); `deadline_slots` overrides class deadlines."""
    n_users, n_slots = cell.bits_per_prb.shape
    n_cls = len(CLASSES)
    dl = {k: v.deadline_slots for k, v in PROFILES.items()} | (deadline_slots or {})
    deadlines = np.array([dl[CLASSES[c]] for c in user_class])
    queues: list[deque] = [deque() for _ in range(n_users)]  # [arrival, remaining, size, id]
    cursor = [0] * n_users
    records: list[tuple] = []
    backlogged = np.zeros((n_cls, n_slots), dtype=bool)
    prbs_cls = np.zeros((n_cls, n_slots), dtype=int)
    queue_bits = np.zeros(n_users)

    for t in range(n_slots):
        for u in range(n_users):
            a, q = arrivals[u], queues[u]
            while cursor[u] < len(a.slot) and a.slot[cursor[u]] == t:
                b = a.bits[cursor[u]]
                cursor[u] += 1
                if buffer_bits is not None and queue_bits.sum() + b > buffer_bits:
                    records.append((u, user_class[u], t, b, np.nan, "dropped"))
                    continue
                q.append([t, b, b])
                queue_bits[u] += b
            while q and t - q[0][0] + 1 > deadlines[u]:
                p = q.popleft()
                queue_bits[u] -= p[1]
                records.append((u, user_class[u], p[0], p[2], np.nan, "dropped"))
            if not q:
                queue_bits[u] = 0.0  # clear floating-point residue
        hol = np.array([q[0][0] if q else np.inf for q in queues])
        bpp = cell.bits_per_prb[:, t]
        st = SlotState(queue_bits.copy(), hol, bpp, user_class)
        for c in range(n_cls):
            backlogged[c, t] = bool((queue_bits[user_class == c] > 0).any())
        alloc = policy.allocate(n_prbs, st)
        served = np.zeros(n_users)
        for u in np.flatnonzero(alloc):
            q, cap = queues[u], alloc[u] * bpp[u]
            prbs_cls[user_class[u], t] += alloc[u]
            while q and cap > 0:
                p = q[0]
                take = min(cap, p[1])
                p[1] -= take
                cap -= take
                served[u] += take
                queue_bits[u] -= take
                if p[1] <= 1e-9:
                    q.popleft()
                    records.append((u, user_class[u], p[0], p[2], t - p[0] + 1, "delivered"))
            if not q:
                queue_bits[u] = 0.0
        policy.update(served)

    for u in range(n_users):
        for p in queues[u]:
            records.append((u, user_class[u], p[0], p[2], np.nan, "pending"))
    df = pd.DataFrame(records, columns=["user", "cls", "arrival", "bits", "delay_slots", "status"])
    return SimResult(df, backlogged, prbs_cls, user_class, n_slots)
