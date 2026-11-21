"""Tests for traffic, policies, the engine, and metrics."""
import numpy as np

from channel.channel_model import ChannelConfig
from cell.cell import CellConfig, CellRealization, generate_cell
from sim.engine import run
from sim.metrics import jain
from sim.policies import POLICIES, ProportionalFair, SlotState
from sim.run import simulate
from sim.traffic import PROFILES, Arrivals, assign_classes, generate_arrivals, saturation_scale


def _const_cell(n_users, n_slots, bpp):
    bits = np.full((n_users, n_slots), float(bpp))
    return CellRealization(np.full(n_users, 100.0), np.zeros(n_users), bits / 360.0, bits)


def test_fragmentation_and_delay():
    # One voice user, PRB carries 100 bits, packet of 300 bits at slot 0 and 1 PRB per slot
    cell = _const_cell(1, 10, 100)
    arr = [Arrivals(np.array([0]), np.array([300.0]))]
    res = run(cell, np.array([0]), arr, POLICIES["prio"](), n_prbs=1)
    row = res.packets.iloc[0]
    assert row.status == "delivered" and row.delay_slots == 3


def test_packet_dropped_after_deadline():
    # 1 PRB of 10 bits per slot cannot deliver 1000 bits within the 20-slot voice deadline
    cell = _const_cell(1, 60, 10)
    arr = [Arrivals(np.array([0]), np.array([1000.0]))]
    res = run(cell, np.array([0]), arr, POLICIES["prio"](), n_prbs=1)
    assert res.packets.iloc[0].status == "dropped"


def test_allocation_respects_budget_and_need():
    rng = np.random.default_rng(0)
    classes = assign_classes(3, 2, 3)
    for name, cls in POLICIES.items():
        pol = cls()
        for _ in range(50):
            st = SlotState(rng.uniform(0, 5000, 8) * (rng.random(8) > 0.3),
                           rng.uniform(0, 100, 8), rng.uniform(100, 1000, 8), classes)
            st.hol_arrival[st.queue_bits == 0] = np.inf
            a = pol.allocate(50, st)
            assert a.sum() <= 50 and (a <= st.need).all() and (a >= 0).all(), name
            # Work-conserving: PRBs are only left over if every queue is empty
            assert a.sum() == min(50, st.need.sum()), name


def test_pf_prefers_the_better_channel_when_averages_are_equal():
    pf = ProportionalFair()
    st = SlotState(np.array([1e6, 1e6]), np.array([0.0, 0.0]), np.array([100.0, 300.0]),
                   np.array([2, 2]))
    assert pf.allocate(10, st).tolist() == [0, 10]


def test_every_arrival_is_accounted_for():
    classes = assign_classes(4, 3, 3)
    arr = generate_arrivals(5000, classes, 100.0, 1.2, seed=3)
    cell = generate_cell(5000, CellConfig(n_users=10), seed=3)
    res = run(cell, classes, arr, POLICIES["dwrr"](), 50)
    assert len(res.packets) == sum(len(a.slot) for a in arr)
    assert set(res.packets.status) <= {"delivered", "dropped", "pending"}


def test_underloaded_static_cell_loses_nothing_under_any_policy():
    cfg = CellConfig(channel=ChannelConfig(fading=False))
    for pol in POLICIES:
        pc, _, _ = simulate(pol, 0.4, 2, duration_s=6, cfg=cfg)
        assert (pc["loss"] == 0).all(), pol


def test_fading_causes_head_of_line_blocking_for_channel_blind_fifo():
    # Same traffic and load: with no fading nothing is lost, with fading FIFO loses voice
    # because a user in a deep fade needs many PRBs and blocks the packets behind it.
    fifo = simulate("fifo", 0.4, 2, duration_s=6)[0].set_index("class")
    prio = simulate("prio", 0.4, 2, duration_s=6)[0].set_index("class")
    assert fifo.loc["voice", "loss"] > 0.05 > prio.loc["voice", "loss"]


def test_policies_distribute_overload_differently():
    out = {pol: simulate(pol, 1.3, 1, duration_s=8)[0].set_index("class") for pol in POLICIES}
    # Priority protects voice; FIFO lets backlogged data delay voice past its deadline
    assert out["prio"].loc["voice", "loss"] < 0.05 < out["fifo"].loc["voice", "loss"]
    # Priority sacrifices data and starves it; DWRR guarantees it a share
    assert out["prio"].loc["data", "starved_frac"] > 0.3
    assert out["dwrr"].loc["data", "starved_frac"] < out["prio"].loc["data", "starved_frac"]


def test_saturation_scale_uses_all_prbs_at_unit_load():
    classes = assign_classes(4, 3, 3)
    bpp = np.random.default_rng(0).uniform(200, 2000, 10)
    s = saturation_scale(classes, bpp, 50)
    demand = np.array([PROFILES[("voice", "video", "data")[c]].bits_per_slot for c in classes])
    assert np.isclose((demand * s / bpp).sum(), 50)


def test_metrics_basics():
    assert np.isclose(jain([1, 1, 1, 1]), 1.0) and np.isclose(jain([1, 0, 0, 0]), 0.25)
    pc, pu, _ = simulate("prio", 0.5, 4, duration_s=6)
    assert list(pc["class"]) == ["voice", "video", "data"]
    assert len(pu) == 10 and (pu["throughput_mbps"] >= 0).all()


def test_shared_buffer_tail_drops_all_classes_alike():
    # Conventional FIFO: a finite shared buffer drops arrivals of every class, so voice is no
    # longer starved by older data (unlike deadline-only FIFO).
    cfg = CellConfig(channel=ChannelConfig(fading=False))
    old, _, _ = simulate("fifo", 1.4, 3, duration_s=6, cfg=cfg)
    buf, _, _ = simulate("fifobuf", 1.4, 3, duration_s=6, cfg=cfg, buffer_ms=10)
    old, buf = old.set_index("class"), buf.set_index("class")
    assert old.loc["voice", "loss"] > 0.9
    assert buf.loc["voice", "loss"] < 0.05
    assert buf.loc["data", "loss"] > old.loc["data", "loss"]


def test_buffer_never_exceeded():
    cell = _const_cell(1, 50, 100)
    arr = [Arrivals(np.array([0, 0, 0]), np.array([300.0, 300.0, 300.0]))]
    res = run(cell, np.array([2]), arr, POLICIES["fifo"](), n_prbs=1, buffer_bits=700)
    assert (res.packets.status == "dropped").sum() == 1


def test_matches_independent_discrete_queue_recursion():
    # 1 PRB carrying exactly one packet per slot turns the engine into a discrete-time queue with
    # one departure per slot; compare every packet delay with a direct recursion.
    n = 4000
    arr = generate_arrivals(n, np.array([2]), 1.0, 0.7, seed=5)
    arr = [Arrivals(arr[0].slot, np.full(len(arr[0].slot), 100.0))]
    res = run(_const_cell(1, n, 100), np.array([2]), arr, POLICIES["fifo"](), n_prbs=1)
    got = res.packets[res.packets.status == "delivered"].sort_values("arrival").delay_slots
    free, ref = 0, []
    for a in arr[0].slot:
        start = max(int(a), free)
        free = start + 1
        ref.append(start - int(a) + 1)
    assert (got.to_numpy() == np.array(ref)[: len(got)]).all() and len(got) == len(ref)


def test_static_saturation_bound_and_work_conservation():
    # Equal static channels and heavy load: every work-conserving policy carries (almost) the
    # cell capacity, and none can exceed it.
    n, bpp, n_prbs = 6000, 1000.0, 50
    cap_mbps = n_prbs * bpp * 1000 / 1e6
    classes = assign_classes(4, 3, 3)
    scale = saturation_scale(classes, np.full(10, bpp), n_prbs)
    arr = generate_arrivals(n, classes, scale, 2.0, seed=4)
    from sim.metrics import per_class
    for name, cls in POLICIES.items():
        res = run(_const_cell(10, n, bpp), classes, arr, cls(), n_prbs)
        thr = per_class(res)["throughput_mbps"].sum()
        assert thr <= cap_mbps * 1.001, name
        # Work-conserving: nearly every PRB is used (goodput is lower because service spent on
        # packets that later miss their deadline is wasted)
        assert res.prbs.sum() >= 0.98 * n * n_prbs, name
