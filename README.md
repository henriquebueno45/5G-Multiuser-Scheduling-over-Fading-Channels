# Multi-User 5G Scheduling over Fading Channels

Simulation of a 5G base station serving several users with different channel qualities. Each user's rate comes from the channel capacity (path loss, shadowing, small-scale fading, optional MRC antenna diversity), and traffic classes (voice, video, data) are served with different scheduling policies under increasing load. The study measures delay, jitter, packet loss, throughput, and starvation per class and per user.

Course project for Wireless Communications (UFSC).

**Status:** simulator, experiments (policy x load x antenna diversity, 30 seeds), sensitivity study, imperfect-CSI study and tests are done. The article (Portuguese, 6 pages) is in `report/`; still to do: theory comparisons (multiuser diversity, M/G/1 priority queue). Plan and roadmap: [docs/PLAN.md](docs/PLAN.md).

## Reused from the Single-User Project

The channel model, its validation, and the statistics helpers come from [Traffic-Scheduling-with-QoS-in-a-Congested-5G-Base-Station](https://github.com/henriquebueno45/Traffic-Scheduling-with-QoS-in-a-Congested-5G-Base-Station) at tag `v1.0`, copied unchanged except for import paths:

| Here | Source (tag `v1.0`) |
|---|---|
| `channel/channel_model.py` | `channel/channel_model.py` |
| `analysis/validate_channel.py` | `analysis/validate_channel.py` |
| `analysis/stats.py` | `boot_ci`, `paired_ci`, `sla_capacity` from `analysis/exp_report.py` |
| `channel/calibration.py` | `equal_mean_distance` from `analysis/experiments.py` |

The channel is validated against theory (outage probability follows Gamma(L, 1) within 0.02 decades for P > 1e-3; level-crossing rate within 2% of Clarke's formula): see `results/outage_validation.png` and `results/channel_validation.png`. The real-time C/Pthreads core from the original project is deliberately not reused.

## Architecture

```mermaid
flowchart TD
    %% -------------------------------------------------------------
    %% STAGE 1: Inputs & Parameters
    %% -------------------------------------------------------------
    subgraph IN ["1. Experiment Parameters & Inputs"]
        direction TB
        CFG["<b>Simulation Configuration (sim/run.py)</b><br/>• Seeds: 30 independent runs (SeedSequence.spawn)<br/>• Duration: 10 s (10,000 slots of 1 ms)<br/>• 5G Downlink: 50 PRBs (360 kHz bandwidth, fc = 3.5 GHz)<br/>• Antenna Diversity: L ∈ {1, 2, 4} (MRC)<br/>• Mobility: v ∈ {1.5, 15.0} m/s (Doppler fd = v·fc/c)<br/>• Offered Load: ρ ∈ [0.2, 3.0] (13 sweep points)"]
    end

    %% -------------------------------------------------------------
    %% STAGE 2: Realization & Environment Pre-Computation
    %% -------------------------------------------------------------
    subgraph PRE ["2. Realization & Environment Pre-Computation (Offline)"]
        direction TB

        subgraph PRE_CHAN ["Physical Layer & Channel Model (cell/cell.py, channel/channel_model.py)"]
            direction TB
            GEOM["<b>User Spatial Placement</b> (cell/cell.py)<br/>• 10 users placed in annulus r ∈ [20, 300] m<br/>• Area-uniform distribution: r_u ~ √(U(r_min², r_max²))<br/>• Independent PRNG per user stream (SeedSequence)"]
            CHAN["<b>Radio Propagation Chain</b> (channel/channel_model.py)<br/>• Path loss: PL(d) = PL(d0) + 10·n·log10(d/d0), n = 3.5<br/>• Shadowing: Log-normal X ~ N(0, σ²), σ = 6 dB<br/>• Fast fading: Correlated Rayleigh (Jakes 32-path)<br/>• MRC Diversity: L-antenna gain G ~ Gamma(L, 1)"]
            RATE["<b>Shannon Link Capacity Matrix</b> (cell/cell.py)<br/>• SNR_u(t) = Ptx - PL(r_u) - X_u - N0 + 10·log10(G_u(t))<br/>• SE_u(t) = min(log2(1 + SNR_u(t)), 7.4) bit/s/Hz (256-QAM)<br/>• Physical capacity: <b>b_u[t]</b> = SE · 360 kHz · 1 ms [bits/PRB]"]
            GEOM --> CHAN --> RATE
        end

        subgraph PRE_TRAF ["Traffic Profiles & Saturation Scaling (sim/traffic.py)"]
            direction TB
            PROFILES["<b>Heterogeneous QoS Traffic Classes</b><br/>• <b>Voice</b> (4 users): Periodic 20 ms, 1.6 kbit, deadline 20 ms<br/>• <b>Video</b> (3 users): Periodic 33 ms frames, 66 kbit, deadline 50 ms<br/>• <b>Data</b> (3 users): Poisson arrivals, 12 kbit, deadline 500 ms"]
            SCALE["<b>Saturation Scale Normalization</b><br/>• Offered bits scaled relative to mean capacity E[b_u[t]]<br/>• Scale factor: S_sat = 50 / Σ (R_u / E[b_u])<br/>• <b>Load ρ = 1.0</b> exactly saturates 50 PRBs at ergodic rate"]
            ARR["<b>Packet Arrivals Queue Matrix</b><br/>• Pre-computed packet list per user: (arrival_slot, bits)<br/>• Deterministic across policies for fair paired comparison"]
            PROFILES --> SCALE --> ARR
        end
    end

    %% -------------------------------------------------------------
    %% STAGE 3: Slotted MAC Simulation Engine (1 ms Loop)
    %% -------------------------------------------------------------
    subgraph SIM ["3. Slotted Discrete-Time MAC Engine (1 ms Loop - sim/engine.py)"]
        direction TB

        subgraph STEP_QUEUE ["Buffer & Deadline Management (sim/engine.py)"]
            direction TB
            ENQ["<b>Packet Ingestion</b><br/>Push arrivals at slot t into per-user FIFO queues"]
            BUF{"<b>Shared Buffer Check</b><br/>(Optional fifobuf variant)"}
            TAILDROP["<b>Tail Drop</b><br/>Discard if total backlog > buffer_bits"]
            HOL_CHECK{"<b>HOL Deadline Check</b><br/>t - arrival + 1 > deadline_u?"}
            DROP_PKT["<b>HOL Drop</b><br/>Discard expired packet (status: 'dropped')"]

            ENQ --> BUF
            BUF -- "Backlog overflow" --> TAILDROP
            BUF -- "Admitted" --> HOL_CHECK
            HOL_CHECK -- "Expired" --> DROP_PKT
        end

        subgraph STEP_ALLOC ["Scheduling Allocation & Feedback (sim/policies.py)"]
            direction TB
            STATE["<b>Slot State Vector Assembly (sim/policies.py)</b><br/>• Backlog: queue_bits[u], HOL arrival: hol_arrival[u]<br/>• Rate: bits_per_prb[u, t] (or reported rate under imperfect CSI)<br/>• Demand in PRBs: need_u = ⌈queue_bits[u] / bits_per_prb[u, t]⌉"]
            
            POL{{"<b>Work-Conserving Scheduling Policy (sim/policies.py)</b><br/>Allocates 50 PRBs budget among backlogged users (alloc[u])<br/>────────────────────────────────────────────────────────<br/>• <b>FIFO</b>: Oldest HOL packet first (class- & channel-blind)<br/>• <b>fifobuf</b>: FIFO with 20 ms shared tail-drop buffer<br/>• <b>Priority (prio)</b>: Strict Voice > Video > Data (oldest-first)<br/>• <b>DWRR</b>: Deficit Weighted Round Robin (weights 8:4:2 PRB quanta)<br/>• <b>Proportional Fair (pf)</b>: Maximize b_u(t) / R_avg,u (EWMA β=0.01)"}}
            
            STATE --> POL
        end

        subgraph STEP_CSI ["Link Adaptation & Imperfect CSI (sim/run.py, analysis/csi.py)"]
            direction TB
            CSI_EVAL{"<b>CSI Feedback Mode</b>"}
            PERF_CSI["<b>Perfect CSI</b><br/>Transmitter uses true instantaneous rate b_u[t]"]
            IMP_CSI["<b>Delayed CQI & Back-off</b><br/>Report delayed by d ∈ {5, 10} ms<br/>MCS back-off by β_backoff ∈ {0, 3, 6} dB<br/>Estimated rate: b_est_u[t]"]
            BLER_CHECK{"<b>True Rate < b_est?</b>"}
            TX_FAIL["<b>Transmission Fails (BLER Outage)</b><br/>PRBs wasted, 0 bits delivered,<br/>bits remain queued for retransmission"]

            CSI_EVAL -- "Ideal CSI" --> PERF_CSI
            CSI_EVAL -- "Imperfect CSI" --> IMP_CSI --> BLER_CHECK
            BLER_CHECK -- "Channel Outage" --> TX_FAIL
        end

        subgraph STEP_TX ["Packet Service & Queue Draining (sim/engine.py)"]
            direction TB
            SERVE["<b>Packet Service & Fragmentation</b><br/>• Drain user queue up to capacity: alloc[u] · rate[u]<br/>• Partial packets fragmented across slots until completed<br/>• On completion: Delay = t - arrival + 1, Status = 'delivered'"]
            UPDATE["<b>Feedback & Policy Updates</b><br/>• Record PRBs per class & backlog status<br/>• PF state update: R_avg = (1 - β)·R_avg + β·served_bits"]
            SERVE --> UPDATE
        end

        HOL_CHECK -- "Active Packets" --> STATE
        POL -- "Allocation alloc[u]" --> CSI_EVAL
        PERF_CSI --> SERVE
        BLER_CHECK -- "Supported" --> SERVE
        UPDATE -. "Next slot (t+1) backlog" .-> ENQ
    end

    %% -------------------------------------------------------------
    %% STAGE 4: Post-Processing, Sweeps & Statistical Analysis
    %% -------------------------------------------------------------
    subgraph POST ["4. Metrics Extraction, Sweeps & Statistical Inference (analysis/)"]
        direction TB

        subgraph EVAL ["Performance Metrics (sim/metrics.py)"]
            direction TB
            FILTER["<b>Stationary Window Filtering</b><br/>Discard warmup (t < 1,000 slots = 1 s) and tail (last 500 slots = 0.5 s)"]
            METRICS["<b>Evaluated Performance Metrics (Per-Class & Per-User)</b><br/>• <b>Packet Loss Rate</b>: dropped / offered packets<br/>• <b>Latency & Jitter</b>: Mean delay, 95th percentile delay (ms), packet-to-packet jitter<br/>• <b>Throughput & Starvation</b>: Delivered Mbit/s, fraction of time backlogged with 0 PRBs<br/>• <b>Imperfect CSI BLER</b>: Failed transmission ratio (tx_failed / tx_total)<br/>• <b>User Fairness</b>: Jain's index J = (Σ x_u)² / (N·Σ x_u²) on delivered ratio (1 - loss)<br/>• <b>Spatial Disparity</b>: Cell-Centre (r < 100 m) vs Cell-Edge (r > 200 m) loss"]
            FILTER --> METRICS
        end

        subgraph SWEEPS ["Resumable Multi-Core Sweeps (analysis/experiments.py, csi.py, sensitivity.py)"]
            direction TB
            EXP["<b>Main Experiment Sweep (experiments.py)</b><br/>5 policies × 13 loads × 3 antenna counts × 30 seeds (multiprocessing)<br/><b>Sensitivity Sweep (sensitivity.py)</b><br/>Robustness to deadlines, DWRR weights (16:4:1, 1:1:1), mix, buffer size<br/><b>Imperfect CSI Sweep (csi.py)</b><br/>Delays {5, 10} ms × Back-offs {0, 3, 6} dB across speeds {1.5, 15} m/s"]
        end

        subgraph STATS ["Statistical Synthesis & Reporting (analysis/report.py, analysis/stats.py)"]
            direction TB
            BOOT["<b>Statistical Analysis & Hypothesis Testing</b><br/>• Non-parametric Bootstrap Confidence Intervals (95% CI, 1,000 resamples)<br/>• Seed-Paired Differences: Δ_loss = Loss(Prio) - Loss(FIFO) with paired CIs<br/>• SLA Capacity Estimation: Maximum offered load sustaining ≥ 99% packet delivery"]
            OUTPUTS[("<b>Generated Artifacts (results/)</b><br/>• CSVs: main_summary, main_paired, main_capacity, main_edge, main_fairness<br/>• Figures: Policies L1/L2/L4, Diversity gain, Edge-vs-Centre, CSI loss, Sensitivity")]
            BOOT --> OUTPUTS
        end

        EVAL --> SWEEPS --> STATS
    end

    %% -------------------------------------------------------------
    %% Inter-Stage Connections
    %% -------------------------------------------------------------
    CFG --> GEOM
    CFG --> CHAN
    CFG --> PROFILES
    RATE -- "b_u[t] capacity matrix" --> STATE
    RATE -. "True channel SE" .-> CSI_EVAL
    SCALE --> ARR
    ARR -- "Pre-computed arrivals" --> ENQ
    SERVE -- "Raw SimResult (packets, prbs, backlog)" --> FILTER

    %% -------------------------------------------------------------
    %% Visual Styling & Color Coding
    %% -------------------------------------------------------------
    classDef cfgStyle fill:#fff8e1,stroke:#f57f17,stroke-width:1.5px,color:#212121
    classDef phyStyle fill:#e1f5fe,stroke:#0288d1,stroke-width:1.5px,color:#01579b
    classDef trafStyle fill:#e0f2f1,stroke:#00897b,stroke-width:1.5px,color:#004d40
    classDef macStyle fill:#ede7f6,stroke:#5e35b1,stroke-width:1.5px,color:#311b92
    classDef polStyle fill:#f3e5f5,stroke:#8e24aa,stroke-width:2px,color:#4a148c
    classDef csiStyle fill:#fbe9e7,stroke:#d84315,stroke-width:1.5px,color:#bf360c
    classDef postStyle fill:#e8f5e9,stroke:#2e7d32,stroke-width:1.5px,color:#1b5e20
    classDef outStyle fill:#c8e6c9,stroke:#1b5e20,stroke-width:2px,color:#004d40

    class CFG cfgStyle
    class GEOM,CHAN,RATE phyStyle
    class PROFILES,SCALE,ARR trafStyle
    class ENQ,BUF,TAILDROP,HOL_CHECK,DROP_PKT,STATE,SERVE,UPDATE macStyle
    class POL polStyle
    class CSI_EVAL,PERF_CSI,IMP_CSI,BLER_CHECK,TX_FAIL csiStyle
    class FILTER,METRICS,EXP,BOOT postStyle
    class OUTPUTS outStyle
```

### Reading the diagram

The architecture is divided into four distinct phases designed for computational efficiency, reproducibility, and rigorous scientific evaluation:

1. **Experiment Parameters & Configuration (Stage 1):** Sets global parameters (seed sequence, 10 s duration, 50 PRBs at 360 kHz, antennas $L \in \{1, 2, 4\}$, speeds $v \in \{1.5, 15\}\text{ m/s}$, loads $\rho \in [0.2, 3.0]$).
2. **Realization & Environment Pre-Computation (Stage 2):** Generates all stochastic channel conditions and packet arrivals offline:
   - **Physical Layer & Channel** (`cell/cell.py`, `channel/channel_model.py`): Places users uniformly over the $20\text{--}300\text{ m}$ cell annulus and computes path loss ($n=3.5$), static log-normal shadowing ($\sigma=6\text{ dB}$), and Jakes Rayleigh fading with $L$-branch MRC diversity. Outputs the physical link capacity matrix $b_u[t]$ ($\text{bits/PRB}$) via Shannon capacity capped at 7.4 bit/s/Hz (256-QAM).
   - **Traffic Profiles & Saturation Scaling** (`sim/traffic.py`): Models 3 5G QoS classes (voice, video, data) with specific packet sizes, periodic/Poisson arrivals, and deadlines. A critical normalization scale factor $S_{\text{sat}}$ anchors $\text{load} = 1.0$ to the exact aggregate PRB capacity of the cell at ergodic user rates.
   - *Decoupling benefit:* Pre-computing the channel and traffic traces guarantees that all scheduling policies are benchmarked against identical realization instances, enabling statistically valid paired comparisons.
3. **Slotted Discrete-Time MAC Engine (Stage 3, 1 ms loop):** Evaluates the gNB downlink per millisecond:
   - **Intake & Buffer:** Enqueues arriving packets; drops on overflow if the optional shared buffer is active (`fifobuf`, 20 ms capacity).
   - **Latency Deadlines:** Checks head-of-line (HOL) packet age against class deadlines (20 ms voice, 50 ms video, 500 ms data) and drops expired packets before wasting radio resources.
   - **State Compilation:** Builds the `SlotState` vector (`queue_bits`, `hol_arrival`, `bits_per_prb`) and computes PRB demand $\text{need}_u = \lceil \text{backlog}_u / b_u[t] \rceil$.
   - **Scheduling Policies** (`sim/policies.py`): Allocates the 50 PRB budget under work-conserving rules. Policies include FIFO, FIFO with buffer (`fifobuf`), Strict Priority (`prio`), DWRR (`dwrr`, weights 8:4:2), and Proportional Fair (`pf`).
   - **Link Adaptation & Imperfect CSI Feedback:** In ideal CSI mode, the transmitter uses true rates $b_u[t]$. In imperfect CSI mode, the scheduler relies on stale CQI (delayed by 5 or 10 ms) with a back-off margin (0, 3, or 6 dB). If the true channel rate is lower than estimated, the transmission fails (BLER outage): PRBs are wasted, 0 bits are delivered, and bits remain queued for retransmission.
   - **Packet Service & Fragmentation:** Transmits queued bits up to allocated capacity, fragmenting large packets across slots, recording delivered packet delays, and updating policy states (e.g., PF exponential moving average rate $\bar{R}_u$).
4. **Post-Processing, Sweeps & Statistical Inference (Stage 4):**
   - **Stationary Windowing:** Discards the initial 1,000 slots (warmup) and final 500 slots (tail) to eliminate transient bias.
   - **Comprehensive Metrics** (`sim/metrics.py`): Measures packet loss, delay (mean and 95th percentile), jitter, throughput, starvation, BLER, Jain's fairness index, and spatial centre-versus-edge disparity.
   - **Resumable Sweeps & Bootstrap Statistics** (`analysis/`): Executes multi-core sweeps across loads, antenna counts, and seeds. Calculates 95% bootstrap confidence intervals, seed-paired differences ($\Delta_{\text{loss}}$), and SLA capacity ($\ge 99\%$ delivery). Produces all publication tables and figures in `results/`.

### Technical description

The simulator is a slotted (1 ms) discrete-time model of one gNB downlink, in four layers that only depend downwards. A run is fully determined by `(policy, load, seed, antennas, ...)`.

1. **Channel layer** (`channel/channel_model.py`, reused from the single-user project). For one user it generates the spectral efficiency per PRB over time: log-distance path loss, static log-normal shadowing, Rayleigh fading from a sum-of-sinusoids Jakes model (32 paths, Doppler from the speed) and MRC over `L` antennas (a Gamma(`L`, 1) gain). The result is `min(log2(1 + SNR), 7.4)`.
2. **Cell layer** (`cell/cell.py`). `generate_cell` draws the user positions (uniform in area over a 20–300 m annulus) and one channel per user, each from its own `SeedSequence.spawn` stream so that a user's channel does not depend on how many other users exist. It returns a `CellRealization` with `bits_per_prb[user, slot]` (SE × 360 kHz × 1 ms), the SE and the distances.
3. **Simulation layer** (`sim/`).
   - `traffic.py` builds per-user packet arrivals (voice and video periodic, data Poisson) and a *saturation scale* so that load 1 fills the 50 PRBs at the realisation's mean rates.
   - `engine.run` is the slot loop. Each slot it (i) enqueues arrivals (tail drop if a shared buffer is set), (ii) drops head-of-line packets past their deadline, (iii) builds a `SlotState` (backlog, head-of-line arrival, bits per PRB, class) and asks the policy for a PRB allocation, (iv) serves each user's queue, fragmenting packets across slots, and (v) records the PRBs per class and the backlog. With `rate_est` set, the policy and the transmitter use the estimated rate and a transmission fails (PRBs wasted, bits stay queued) when the true rate is lower.
   - `policies.py` defines the `Policy` interface (`allocate`, `update`) and its implementations. A new policy only needs to implement `allocate` and be added to the `POLICIES` registry; the engine never looks inside it.
   - `run.simulate` wires it all together, builds `rate_est` from a delayed SE and a back-off, and holds the variant registry (`fifobuf`), the DWRR weights, deadline and buffer overrides and the CLI.
   - `metrics.py` turns the `SimResult` into per-class and per-user tables (the first 1,000 and last 500 slots are excluded).
4. **Experiment layer** (`analysis/`). `experiments.py`, `sensitivity.py` and `csi.py` are resumable sweeps over a `multiprocessing.Pool`: every `(configuration, seed)` job is independent and appends its rows to a CSV, keyed so completed jobs are skipped on restart. `report.py` and `stats.py` read the CSVs and produce bootstrap confidence intervals, paired differences, SLA capacity, edge/centre and fairness tables and the plots in `results/`.

Design choices: all randomness derives from the seed (runs are reproducible and policies are compared on identical channels and traffic, which makes the paired differences valid); the channel and the engine are decoupled by the `bits_per_prb` array, so another channel model can be plugged in without touching the scheduler; and the tests (`tests/`) check each layer separately (channel statistics, link budget, policy invariants, an exact queue recursion, the saturation bound).

## Results

Setup: one cell with 50 PRBs (360 kHz, 1 ms slots), 10 users uniform over 20-300 m (4 voice, 3 video, 3 data), Rayleigh fading with 1.5 m/s mobility, 10 s per run, 30 seeds, 95% bootstrap intervals (loads 0.2 to 3.0). **Load 1 is the point where the offered bits would use every PRB** at each user's mean rate. A packet that cannot meet its deadline (voice 20 ms, video 50 ms, data 500 ms) is dropped. Policies: FIFO (oldest packet first, deadline drops only), FIFO with a 20 ms shared tail-drop buffer (`fifobuf`), strict priority (`prio`), DWRR with weights 8/4/2 (`dwrr`), and class-blind proportional fair (`pf`). Single receive antenna unless stated.

### Who wins and who loses under congestion

Packet loss at load 1.2 (the cell is 20% overloaded), one antenna:

| Class | FIFO | FIFO + buffer | Priority | DWRR 8/4/2 | PF |
|---|---|---|---|---|---|
| Voice | 99.6% | 76.9% | 0.1% | 0.1% | 0.4% |
| Video | 67.0% | 52.4% | 5.0% | 17.4% | 14.7% |
| Data | 0.3% | 12.5% | 68.1% | 46.1% | 6.5% |

![Policies, 1 antenna](results/main_policies_L1.png)

- **Class-blind FIFO sacrifices the most delay-sensitive traffic.** Older data always sits ahead of new voice packets, and under fading a user in a deep fade needs many PRBs and blocks everyone behind it. Even at load 0.4 FIFO loses voice, which strict priority and DWRR do not.
- **Strict priority** keeps voice and video alive and moves the loss to data, which is starved 73% of the time at load 1.2.
- **DWRR** never starves data (0% starvation), at the price of more video loss than priority. Its behaviour is set by its weights (see sensitivity).
- **PF** has the best overall fairness but no class guarantees; its voice protection comes from favouring good channels, not from class awareness.

Priority over FIFO at load 1.2, paired over seeds: voice -99.6 percentage points [-99.9, -98.9], video -62 [-70, -54], data +68 [+62, +74].

### Load each class can carry (>= 99% delivered)

Highest load at which the class still delivers 99% of its packets, one antenna. Voice values for priority, DWRR and PF are lower bounds: most seeds never violate the 99% target up to the highest simulated load, 3.0.

| Class | FIFO | FIFO + buffer | Priority | DWRR | PF |
|---|---|---|---|---|---|
| Voice | 0.30 | 0.30 | >= 2.91 | >= 2.82 | >= 2.59 |
| Video | 0.57 | 0.54 | 1.21 | 0.92 | 0.82 |
| Data | 1.90 | 0.80 | 0.73 | 0.92 | 1.36 |

### Antenna diversity

![Effect of diversity](results/main_diversity.png)

More receive antennas (MRC, L = 1, 2, 4) raise the load that voice and video can carry under every policy. Video capacity under priority goes from 1.21 to 1.75, and under FIFO from 0.57 to 0.93; voice under FIFO from 0.30 to 0.80. Diversity helps most the classes that were being hurt by deep fades. An exception is PF, which gets *worse* for video and data with more antennas (video loss at load 1.2 goes from 14.7% to 26.4%, and its data capacity falls from 1.36 to about 1.1), because diversity flattens the fading peaks that PF exploits.

### Cell centre versus cell edge

![Cell centre versus cell edge](results/main_edge_centre.png)

At load 1.2, edge users (> 200 m) lose far more than centre users (< 100 m) under channel-aware policies: PF video loss is 27% at the edge and 2% in the centre, DWRR video 26% against 8%. Priority is the most even (video 8% against 1%, voice below 0.2% everywhere). Per-user fairness (Jain index of delivered fractions) at load 1.2: PF 0.97, DWRR 0.90, priority 0.85, FIFO + buffer 0.72, FIFO 0.46. PF is "fair" because it spreads loss evenly across classes, which is not the same as protecting voice.

### How robust are these conclusions?

![Sensitivity](results/sens_loss.png)

One assumption was changed at a time (data deadline 100 ms / 2000 ms, voice deadline 50 ms, user mix 6/2/2 and 2/4/4, DWRR weights, FIFO buffer), 20 seeds, load 1.2.

- **Robust:** the policy ranking never changes. Priority, DWRR and PF keep voice loss at or below 0.6% in every variant; FIFO loses 98% or more of voice in all but the variant that relaxes the voice deadline to 50 ms (37%).
- **FIFO has no good operating point.** Shrinking its buffer to 5 ms protects voice (14% loss) but loses 78% of video and 21% of data; a 100 ms buffer loses 99% of voice. A single FIFO number would be misleading, so both variants are reported.
- **DWRR is a dial, not a single result.** With weights 16/4/1 data loses 57% and video 9.5%; with equal weights video loses 35% and data 27%.

### Do the conclusions survive imperfect channel knowledge?

![Imperfect CSI](results/csi_loss.png)

The base station is given a CQI report that is 5 or 10 ms old and transmits at that rate minus a back-off (0, 3 or 6 dB). If the true channel is worse, the transmission fails: the PRBs are wasted and the data is sent again. 20 seeds, speeds 1.5 and 15 m/s, loads 0.8 and 1.2, 1 and 4 antennas (`analysis/csi.py`).

- **Policy ranking survives.** Priority, DWRR and PF still protect voice (below about 11% loss at load 1.2, below 2% with a 3 dB back-off); FIFO and FIFO with a buffer still lose almost all voice. Priority is still the best for video and still starves data (97-99% loss).
- **Everything loses capacity.** At load 0.8 with a 5 ms delay and 3 dB back-off, video loss at 1.5 m/s goes from 3% to 31% (DWRR) and 17% (priority) and data loss from about 0% to 55% (DWRR) and 87% (priority), so load 0.8 is no longer below capacity.
- **PF is the most sensitive to speed.** It picks users at their fading peaks, which a stale report overestimates: its block error rate is 0.32-0.71 at 15 m/s against 0.19 for the others, and its video loss at load 0.8 is 52% (priority: 26%).
- **A moderate back-off is best.** At 1.5 m/s 3 dB beats 6 dB and 0 dB.
- This model is harsher than a real link (no outer-loop adaptation to a 10% error target, no HARQ combining); read it as the direction of the effect, not its size.

### Limitations

- The traffic mix, deadlines and DWRR weights are modelling choices, not measured values; the sensitivity study shows which results depend on them.
- Load 1 is relative to each seed's realisation, so it varies slightly between seeds.
- Service spent on a packet that then misses its deadline is wasted, so goodput under overload is below the cell capacity.
- Voice capacity of the protected policies is censored at load 3.0 (it is a lower bound, because voice is a small share of the total traffic).

Raw outputs: `results/main_*.csv` (summary, paired differences, capacity, edge/centre, fairness) and `results/sens_*.csv`.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q tests
python -m analysis.validate_channel   # regenerates the validation plots
python -m sim.run --policy prio --load 1.3 --seed 1   # one multi-user run: per-class and per-user metrics
```

### Reproducing the results

```bash
python -m analysis.experiments --name main --seeds 30 --workers 6   # about 15 min, resumable
python -m analysis.report --name main                                # tables and plots
python -m analysis.sensitivity run --seeds 20 --workers 6            # about 15 min, resumable
python -m analysis.sensitivity report
python -m analysis.csi run --seeds 20 --workers 6                    # about 25 min, resumable
python -m analysis.csi report --load 1.2 --antennas 1                # also try --load 0.8
```

## License

MIT, see [LICENSE](LICENSE).
