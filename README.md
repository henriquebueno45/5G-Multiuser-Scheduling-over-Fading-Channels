# Multi-User 5G Scheduling over Fading Channels

Simulation of a 5G base station serving several users with different channel qualities. Each user's rate comes from the channel capacity (path loss, shadowing, small-scale fading, optional MRC antenna diversity), and traffic classes (voice, video, data) are served with different scheduling policies under increasing load. The study measures delay, jitter, packet loss, throughput, and starvation per class and per user.

Course project for Wireless Communications (UFSC).

**Status:** in development. Done: reused channel model and statistics, and the multi-user cell model (`cell/cell.py`: users placed over an annulus, independent shadowing and fading per user, Shannon rate per slot). Next: traffic, scheduling policies, and metrics. Plan and roadmap: [docs/PLAN.md](docs/PLAN.md).

## Reused from the Single-User Project

The channel model, its validation, and the statistics helpers come from [Traffic-Scheduling-with-QoS-in-a-Congested-5G-Base-Station](https://github.com/henriquebueno45/Traffic-Scheduling-with-QoS-in-a-Congested-5G-Base-Station) at tag `v1.0`, copied unchanged except for import paths:

| Here | Source (tag `v1.0`) |
|---|---|
| `channel/channel_model.py` | `channel/channel_model.py` |
| `analysis/validate_channel.py` | `analysis/validate_channel.py` |
| `analysis/stats.py` | `boot_ci`, `paired_ci`, `sla_capacity` from `analysis/exp_report.py` |
| `channel/calibration.py` | `equal_mean_distance` from `analysis/experiments.py` |

The channel is validated against theory (outage probability follows Gamma(L, 1) within 0.02 decades for P > 1e-3; level-crossing rate within 2% of Clarke's formula): see `results/outage_validation.png` and `results/channel_validation.png`. The real-time C/Pthreads core from the original project is deliberately not reused.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q tests
python -m analysis.validate_channel   # regenerates the validation plots
```

## License

MIT, see [LICENSE](LICENSE).
