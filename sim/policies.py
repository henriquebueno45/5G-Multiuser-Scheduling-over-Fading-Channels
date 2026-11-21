"""Scheduling policies: each slot, split the cell's PRBs among users.

A policy receives the slot state and returns the integer PRBs given to each user. Every policy is
work-conserving and never gives a user more PRBs than it needs to empty its queue at the current
bits-per-PRB, so leftover PRBs flow to the next candidate.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sim.traffic import CLASSES


@dataclass
class SlotState:
    queue_bits: np.ndarray  # (n_users,) backlog in bits
    hol_arrival: np.ndarray  # (n_users,) arrival slot of the head-of-line packet (inf if empty)
    bits_per_prb: np.ndarray  # (n_users,) bits one PRB carries this slot
    user_class: np.ndarray  # (n_users,) index into CLASSES

    @property
    def need(self) -> np.ndarray:
        """PRBs each user needs to empty its queue this slot."""
        return np.ceil(self.queue_bits / self.bits_per_prb).astype(int)


def _fill(order: list[int], need: np.ndarray, budget: int, alloc: np.ndarray) -> int:
    """Give PRBs to users in `order` up to their remaining need; return the unused budget."""
    for u in order:
        give = min(int(need[u] - alloc[u]), budget)
        if give > 0:
            alloc[u] += give
            budget -= give
            if budget == 0:
                break
    return budget


def _oldest_first(users: np.ndarray, st: SlotState) -> list[int]:
    return sorted((int(u) for u in users if st.queue_bits[u] > 0),
                  key=lambda u: (st.hol_arrival[u], u))


class Policy:
    name = "base"

    def allocate(self, n_prbs: int, st: SlotState) -> np.ndarray:
        raise NotImplementedError

    def update(self, served_bits: np.ndarray) -> None:
        """Hook called after each slot with the bits served per user."""


class FIFO(Policy):
    """Oldest head-of-line packet first, regardless of class or channel."""

    name = "fifo"

    def allocate(self, n_prbs, st):
        alloc = np.zeros(len(st.queue_bits), dtype=int)
        _fill(_oldest_first(np.arange(len(alloc)), st), st.need, n_prbs, alloc)
        return alloc


class StrictPriority(Policy):
    """Voice, then video, then data; oldest packet first inside a class."""

    name = "prio"

    def allocate(self, n_prbs, st):
        alloc = np.zeros(len(st.queue_bits), dtype=int)
        budget = n_prbs
        for c in range(len(CLASSES)):
            budget = _fill(_oldest_first(np.flatnonzero(st.user_class == c), st), st.need, budget,
                           alloc)
            if budget == 0:
                break
        return alloc


class DWRR(Policy):
    """Deficit weighted round robin across classes, with a PRB quantum proportional to the weight."""

    name = "dwrr"

    def __init__(self, weights=(8, 4, 2)):
        self.quantum = np.asarray(weights, dtype=float)
        self.deficit = np.zeros(len(CLASSES))
        self.start = 0

    def allocate(self, n_prbs, st):
        alloc = np.zeros(len(st.queue_bits), dtype=int)
        budget = n_prbs
        need = st.need
        members = [np.flatnonzero(st.user_class == c) for c in range(len(CLASSES))]
        # Each round gives every backlogged class its quantum (quanta >= 1 PRB), so a round with
        # pending demand and spare PRBs always makes progress and the loop terminates.
        while budget > 0:
            any_pending = False
            for k in range(len(CLASSES)):
                c = (self.start + k) % len(CLASSES)
                pending = [u for u in members[c] if need[u] > alloc[u]]
                if not pending:
                    self.deficit[c] = 0.0
                    continue
                any_pending = True
                self.deficit[c] += self.quantum[c]
                grant = min(int(self.deficit[c]), budget)
                left = _fill(sorted(pending, key=lambda u: (st.hol_arrival[u], u)), need, grant,
                             alloc)
                used = grant - left
                budget -= used
                self.deficit[c] -= used
                if all(need[u] <= alloc[u] for u in members[c]):
                    self.deficit[c] = 0.0
                if budget == 0:
                    break
            if not any_pending:
                break
        self.start = (self.start + 1) % len(CLASSES)
        return alloc


class ProportionalFair(Policy):
    """Class-blind: highest instantaneous rate over average throughput first."""

    name = "pf"

    def __init__(self, beta: float = 0.01):
        self.beta = beta
        self.avg: np.ndarray | None = None

    def allocate(self, n_prbs, st):
        if self.avg is None:
            self.avg = np.ones(len(st.queue_bits))
        alloc = np.zeros(len(st.queue_bits), dtype=int)
        metric = st.bits_per_prb / self.avg
        order = [int(u) for u in np.argsort(-metric, kind="stable") if st.queue_bits[u] > 0]
        _fill(order, st.need, n_prbs, alloc)
        return alloc

    def update(self, served_bits):
        if self.avg is not None:
            self.avg = (1 - self.beta) * self.avg + self.beta * served_bits


POLICIES = {"fifo": FIFO, "prio": StrictPriority, "dwrr": DWRR, "pf": ProportionalFair}
