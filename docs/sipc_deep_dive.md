# SIPC Deep Dive: Items 2, 3, 4, 7 & 8

**Date:** 2026-03-31
**Classification:** UNCLASSIFIED
**Context:** Space Intercept Planning Console — Implementation Architecture for Priority TODO Items

---

## Item 2: TLE Cadence Filtering & Deduplication

### The Problem

TLE data from UDL/Space-Track arrives at irregular intervals. For active objects, you may receive multiple TLEs within minutes (multiple sensors updating the catalogue near-simultaneously), followed by gaps of hours or days. This creates two distinct problems for SIPC:

1. **Manoeuvre detection noise.** Clumped TLEs with slightly different epochs and element values create false delta-V signatures when you difference sequential element sets. A "manoeuvre" that is actually just two sensors disagreeing on the same pass will pollute your Pattern of Life analysis.
2. **Propagation input ambiguity.** When feeding TLEs into SGP4 for historical state reconstruction, using every available TLE overweights time periods with dense coverage and underweights periods with sparse coverage, biasing any time-series analysis.

### Why Averaging TLEs Is Wrong

Averaging two TLE element sets is not physically meaningful. A TLE is not a raw measurement — it is the output of a differential correction process (a batch least-squares fit) against a specific force model (SGP4/SDP4's analytical theory). The mean elements in a TLE are defined relative to SGP4's specific perturbation model. Averaging the mean motion from two TLEs doesn't produce a valid mean motion in the SGP4 sense — it produces a number that, when fed back into SGP4, will propagate to a state that matches neither original TLE. The error introduced is non-trivial and epoch-dependent.

### Recommended Approach: Epoch-Spacing Filter with Quality Selection

The architecture has three stages:

**Stage 1: Cluster Detection**

Define a minimum epoch spacing threshold. TLEs whose epochs fall within this threshold of each other are grouped into a cluster. Recommended starting values:

| Orbit Regime | Min Spacing | Rationale |
|---|---|---|
| LEO (< 2,000 km) | 15 minutes | Roughly one orbital period segment; distinguishes same-pass updates from next-pass updates |
| MEO (2,000–35,000 km) | 30 minutes | Longer orbital period, sensors typically update less frequently |
| GEO (35,000+ km) | 60 minutes | Very long period, updates often clustered around station passes |

These are starting points — tune based on your data. The clustering algorithm is straightforward: sort TLEs by epoch, walk forward, and start a new cluster whenever the epoch gap exceeds the threshold.

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

@dataclass
class TLERecord:
    """Single TLE with metadata for filtering."""
    norad_id: int
    epoch: datetime              # TLE epoch (UTC)
    line1: str
    line2: str
    classification: str          # U, C, S
    data_source: str             # Sensor/source identifier
    rms_residual: float | None   # Fit residual if available from UDL
    element_set_number: int
    # Parsed elements for quick access
    mean_motion_rev_per_day: float
    eccentricity: float
    inclination_deg: float
    raan_deg: float
    arg_perigee_deg: float
    mean_anomaly_deg: float
    bstar: float

@dataclass
class TLECluster:
    """A group of TLEs within the epoch-spacing threshold."""
    tles: list[TLERecord] = field(default_factory=list)

    @property
    def earliest_epoch(self) -> datetime:
        return min(t.epoch for t in self.tles)

    @property
    def latest_epoch(self) -> datetime:
        return max(t.epoch for t in self.tles)

    @property
    def span_seconds(self) -> float:
        return (self.latest_epoch - self.earliest_epoch).total_seconds()


def cluster_tles(
    tles: Sequence[TLERecord],
    min_spacing: timedelta
) -> list[TLECluster]:
    """
    Group TLEs into clusters where consecutive epochs are within min_spacing.

    Parameters
    ----------
    tles : Sequence[TLERecord]
        TLEs for a single NORAD ID, need not be sorted.
    min_spacing : timedelta
        Minimum epoch gap to start a new cluster.

    Returns
    -------
    list[TLECluster]
        Clusters in chronological order, each containing 1+ TLEs.
    """
    if not tles:
        return []

    sorted_tles = sorted(tles, key=lambda t: t.epoch)
    clusters: list[TLECluster] = [TLECluster(tles=[sorted_tles[0]])]

    for tle in sorted_tles[1:]:
        prev_epoch = clusters[-1].tles[-1].epoch
        if (tle.epoch - prev_epoch) >= min_spacing:
            clusters.append(TLECluster(tles=[tle]))
        else:
            clusters[-1].tles.append(tle)

    return clusters
```

**Stage 2: Representative Selection Within Each Cluster**

For each cluster, select exactly one representative TLE. Selection criteria, in priority order:

1. **Lowest RMS residual** (if available from UDL metadata). This is the most direct indicator of fit quality — the TLE that best matched the underlying observations.
2. **Most recent epoch** within the cluster. If RMS data is not available, prefer the latest update as it incorporates the most recent observations.
3. **Highest element set number** as a tiebreaker. Higher ESN indicates a more recent differential correction run.

```python
def select_representative(cluster: TLECluster) -> TLERecord:
    """
    Select the best TLE from a cluster.

    Priority: lowest RMS residual > most recent epoch > highest element set number.
    """
    candidates = cluster.tles

    # Filter to those with RMS data if any have it
    with_rms = [t for t in candidates if t.rms_residual is not None]
    if with_rms:
        return min(with_rms, key=lambda t: (t.rms_residual, -t.epoch.timestamp()))

    # Fall back to most recent epoch, then highest element set number
    return max(candidates, key=lambda t: (t.epoch, t.element_set_number))
```

**Stage 3: Quality Flagging on the Output Sequence**

After selection, the output is a clean, evenly-cadenced (approximately) sequence of TLEs. Before passing this to downstream analysis, flag potential issues:

- **Staleness warning:** If the gap between consecutive representatives exceeds a regime-dependent threshold (e.g., >24h for LEO, >72h for GEO), flag the gap. This matters for manoeuvre detection — a gap may hide a manoeuvre.
- **B* discontinuity:** If `bstar` jumps significantly between consecutive representatives, flag it — this may indicate a catalogue maintenance event rather than a physical change.
- **Element discontinuity vs manoeuvre:** Large jumps in semi-major axis, eccentricity, or inclination between consecutive representatives are candidate manoeuvre detections. But after filtering, you need to verify these aren't artefacts of cluster selection (e.g., you picked a low-RMS TLE in one cluster and a high-RMS TLE in the next, and the difference is fit quality, not a real manoeuvre).

### Edge Cases to Handle

- **Single-TLE clusters** are the common case for well-behaved objects and pass through unchanged.
- **Very large clusters** (10+ TLEs within the threshold) may indicate a tracking campaign or a manoeuvre being tracked in real-time. Log these — they're operationally interesting even if you only select one representative.
- **Manoeuvre detection windows:** If your manoeuvre detection algorithm operates on raw TLE sequences, run it *before* filtering. The filtering is for clean propagation input and PoL analysis. The raw sequence with its noise signature may actually help detect manoeuvres (a sudden cluster of TLEs after a quiet period often indicates the catalogue is catching up after a manoeuvre).

### Configuration

Externalise all thresholds to TOML/YAML config:

```toml
[tle_filtering]
min_spacing_leo_seconds = 900       # 15 minutes
min_spacing_meo_seconds = 1800      # 30 minutes
min_spacing_geo_seconds = 3600      # 60 minutes
staleness_warning_leo_hours = 24
staleness_warning_geo_hours = 72
bstar_discontinuity_threshold = 0.5 # Fractional change
```

### Testing Strategy

| Test | Method | Expected |
|---|---|---|
| Single TLE input | Unit | Returns single TLE unchanged |
| Two TLEs 5 seconds apart (LEO) | Unit | Returns one cluster, one representative |
| Two TLEs 20 minutes apart (LEO) | Unit | Returns two clusters, two representatives |
| RMS-based selection | Unit with mock RMS values | Selects lowest RMS |
| Known manoeuvre in sequence | Integration with historical data | Manoeuvre not hidden by filtering |
| Round-trip: filter → propagate → compare with unfiltered propagation | Regression | Position differences within acceptable bounds |

---

## Item 3: Monte Carlo Simulation for Manoeuvre Outcome Prediction

### Operational Purpose

When SIPC detects a manoeuvre (or a manoeuvre is hypothesised as part of a "what-if"), the critical question is: **where is the target going?** A single deterministic propagation gives one answer, but reality has uncertainty in:

- Delta-V magnitude (thruster performance variation, fuel state uncertainty)
- Delta-V direction (pointing accuracy, misalignment)
- Manoeuvre timing (execution delay, phasing)
- Post-manoeuvre drag and SRP parameters (attitude change after manoeuvre may alter ballistic coefficient)

Monte Carlo simulation samples across these uncertainties and produces a probability distribution of post-manoeuvre states. This transforms the output from "it's going here" to "there's a 90% probability it's heading to one of these orbital regimes, and here's the ranked list."

### Architecture

```
┌─────────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  Manoeuvre           │     │  Sample Generator     │     │  Propagation       │
│  Hypothesis          │────▶│  (Parameter           │────▶│  Engine            │
│  (baseline ΔV,       │     │   Distributions)      │     │  (per-sample)      │
│   direction, epoch)  │     │                       │     │                    │
└─────────────────────┘     └──────────────────────┘     └────────┬───────────┘
                                                                   │
                                                                   ▼
                                                          ┌────────────────────┐
                                                          │  Result Aggregator │
                                                          │  (statistics,      │
                                                          │   percentiles,     │
                                                          │   clustering)      │
                                                          └────────┬───────────┘
                                                                   │
                                                                   ▼
                                                          ┌────────────────────┐
                                                          │  Output Contract   │
                                                          │  (probability      │
                                                          │   clouds, ranked   │
                                                          │   orbits, metrics) │
                                                          └────────────────────┘
```

### Component Design

#### 3.1 Manoeuvre Hypothesis Definition

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class ManoeuvreHypothesis:
    """
    Defines a baseline manoeuvre and its uncertainty envelope.

    All uncertainties are 1-sigma values for Gaussian sampling,
    or bounds for uniform sampling (distribution type is specified).
    """
    # Baseline manoeuvre parameters
    epoch_utc: datetime                    # Nominal manoeuvre epoch
    delta_v_magnitude_km_s: float          # Nominal ΔV magnitude [km/s]
    delta_v_direction_radial: float        # Radial component (R) in RIC frame [km/s]
    delta_v_direction_in_track: float      # In-track component (I) [km/s]
    delta_v_direction_cross_track: float   # Cross-track component (C) [km/s]

    # Pre-manoeuvre state (from TLE propagation or OD solution)
    pre_manoeuvre_state_eci_km: np.ndarray  # [x, y, z, vx, vy, vz] in J2000 ECI [km, km/s]
    pre_manoeuvre_epoch_utc: datetime

    # Uncertainty model
    delta_v_magnitude_1sigma_km_s: float = 0.001    # ΔV magnitude uncertainty
    delta_v_pointing_1sigma_deg: float = 2.0         # Pointing cone half-angle uncertainty
    epoch_1sigma_seconds: float = 30.0               # Timing uncertainty
    bstar_post_manoeuvre_1sigma: float = 0.0001       # Post-manoeuvre drag uncertainty

    # Sampling configuration
    distribution_type: str = "gaussian"  # "gaussian" or "uniform"
    n_samples: int = 5000
    random_seed: int = 42                # Reproducibility


@dataclass
class ManoeuvreType:
    """Pre-configured manoeuvre archetypes with characteristic uncertainties."""
    name: str
    description: str
    typical_delta_v_km_s: float
    delta_v_1sigma_fraction: float      # As fraction of nominal ΔV
    pointing_1sigma_deg: float
    timing_1sigma_seconds: float

# Common manoeuvre archetypes
MANOEUVRE_ARCHETYPES = {
    "station_keeping": ManoeuvreType(
        name="Station Keeping",
        description="GEO east-west or north-south station keeping",
        typical_delta_v_km_s=0.002,
        delta_v_1sigma_fraction=0.10,
        pointing_1sigma_deg=1.0,
        timing_1sigma_seconds=10.0,
    ),
    "orbit_raise": ManoeuvreType(
        name="Orbit Raise",
        description="LEO/MEO altitude change manoeuvre",
        typical_delta_v_km_s=0.050,
        delta_v_1sigma_fraction=0.05,
        pointing_1sigma_deg=2.0,
        timing_1sigma_seconds=30.0,
    ),
    "plane_change": ManoeuvreType(
        name="Plane Change",
        description="Inclination or RAAN adjustment",
        typical_delta_v_km_s=0.100,
        delta_v_1sigma_fraction=0.05,
        pointing_1sigma_deg=3.0,
        timing_1sigma_seconds=60.0,
    ),
    "phasing": ManoeuvreType(
        name="Phasing Manoeuvre",
        description="Along-track repositioning within same orbit",
        typical_delta_v_km_s=0.010,
        delta_v_1sigma_fraction=0.08,
        pointing_1sigma_deg=2.0,
        timing_1sigma_seconds=20.0,
    ),
    "intercept_approach": ManoeuvreType(
        name="Intercept / Approach",
        description="Co-orbital approach towards a target object",
        typical_delta_v_km_s=0.200,
        delta_v_1sigma_fraction=0.03,
        pointing_1sigma_deg=1.5,
        timing_1sigma_seconds=15.0,
    ),
    "evasive": ManoeuvreType(
        name="Evasive Manoeuvre",
        description="Rapid unplanned manoeuvre to avoid threat or conjunction",
        typical_delta_v_km_s=0.030,
        delta_v_1sigma_fraction=0.15,
        pointing_1sigma_deg=5.0,
        timing_1sigma_seconds=120.0,
    ),
}
```

#### 3.2 Sample Generator

The sample generator creates N perturbed manoeuvre instances from the hypothesis. Key design decisions:

- **ΔV perturbation in RIC frame.** Perturb magnitude and direction in the Radial-In track-Crosstrack frame, then transform to ECI for application. This keeps the perturbation physically meaningful (pointing error is a cone around the nominal thrust direction, not a random walk in ECI).
- **Pointing error as a cone.** The pointing uncertainty is modelled as a cone angle. Sample the off-nominal angle from a Rayleigh distribution (for isotropic pointing error), and the clock angle uniformly on [0, 2π].
- **Seeded RNG.** Every run uses a seeded `numpy.random.Generator` for reproducibility.

```python
def generate_samples(
    hypothesis: ManoeuvreHypothesis,
) -> np.ndarray:
    """
    Generate N perturbed ΔV vectors in ECI frame [km/s].

    Returns
    -------
    np.ndarray, shape (N, 7)
        Each row: [delta_vx, delta_vy, delta_vz, epoch_offset_s, bstar_perturbation,
                   dv_magnitude_km_s, cone_angle_deg]
        First three columns are the ECI ΔV vector.
        Additional columns are metadata for downstream analysis.
    """
    rng = np.random.default_rng(hypothesis.random_seed)
    n = hypothesis.n_samples

    # 1. Perturb ΔV magnitude
    if hypothesis.distribution_type == "gaussian":
        dv_magnitudes = rng.normal(
            hypothesis.delta_v_magnitude_km_s,
            hypothesis.delta_v_magnitude_1sigma_km_s,
            size=n
        )
    else:  # uniform
        dv_magnitudes = rng.uniform(
            hypothesis.delta_v_magnitude_km_s - 3 * hypothesis.delta_v_magnitude_1sigma_km_s,
            hypothesis.delta_v_magnitude_km_s + 3 * hypothesis.delta_v_magnitude_1sigma_km_s,
            size=n
        )
    dv_magnitudes = np.abs(dv_magnitudes)  # ΔV magnitude is non-negative

    # 2. Perturb pointing direction (cone model)
    # Cone half-angle from Rayleigh distribution
    sigma_rad = np.radians(hypothesis.delta_v_pointing_1sigma_deg)
    cone_angles = rng.rayleigh(sigma_rad, size=n)
    clock_angles = rng.uniform(0, 2 * np.pi, size=n)

    # 3. Perturb timing
    epoch_offsets_s = rng.normal(0, hypothesis.epoch_1sigma_seconds, size=n)

    # 4. Perturb post-manoeuvre Bstar
    bstar_perturbations = rng.normal(0, hypothesis.bstar_post_manoeuvre_1sigma, size=n)

    # 5. Build perturbed ΔV vectors in RIC, then rotate to ECI
    # (RIC→ECI rotation requires the pre-manoeuvre state — handled by caller)
    # Here we return the RIC-frame perturbed vectors

    # Nominal direction unit vector in RIC
    nominal_ric = np.array([
        hypothesis.delta_v_direction_radial,
        hypothesis.delta_v_direction_in_track,
        hypothesis.delta_v_direction_cross_track,
    ])
    nominal_ric_norm = np.linalg.norm(nominal_ric)
    if nominal_ric_norm < 1e-15:
        raise ValueError("Nominal ΔV direction is zero vector")
    nominal_ric_unit = nominal_ric / nominal_ric_norm

    # Apply cone perturbation to each sample
    # ... (rotation matrix construction using cone_angle and clock_angle)
    # This produces N perturbed unit vectors, each scaled by dv_magnitudes[i]

    # Return structure for downstream processing
    # (Full implementation would include RIC→ECI transform here)
    ...
```

#### 3.3 Propagation Engine

Each sample is: apply the perturbed ΔV to the pre-manoeuvre state at the perturbed epoch, then propagate forward for the prediction horizon.

**Force model fidelity tradeoff for Monte Carlo:**

| Model | Compute Cost (relative) | Position Error at 24h (LEO) | Recommendation |
|---|---|---|---|
| Two-body (Keplerian) | 1x | 10–50 km | Too inaccurate for anything beyond rough screening |
| SGP4 (from fitted TLE) | 2x | 1–5 km (if TLE is fresh) | Not applicable here — we're propagating a modified state, not a TLE |
| J2 secular analytical | 3x | 1–5 km | Good for LEO, fast, acceptable for 24–48h prediction |
| J2 + drag (exponential atmosphere) | 10x | 0.5–2 km | Best tradeoff for LEO Monte Carlo — captures the dominant perturbations |
| Full perturbation (J4 + drag + SRP + 3rd body) | 50–100x | 0.1–0.5 km | Overkill for Monte Carlo — the sampling uncertainty dominates |

**Recommendation:** Use J2 + exponential drag for LEO, J2 + SRP for GEO. The Monte Carlo uncertainty envelope from manoeuvre parameter variation will be much larger than the propagation model error. Save high-fidelity propagation for the "best estimate" deterministic run that you compare the Monte Carlo envelope against.

**Parallelism strategy:**

```python
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import numpy as np

def propagate_single_sample(
    sample_params: dict,
    pre_manoeuvre_state: np.ndarray,
    propagation_config: dict,
    prediction_horizon_hours: float,
) -> dict:
    """
    Propagate a single Monte Carlo sample.

    Returns post-manoeuvre state at prediction horizon, plus trajectory metadata.
    Runs in a worker process — must be self-contained (no shared mutable state).
    """
    # 1. Apply ΔV to pre-manoeuvre state at perturbed epoch
    # 2. Propagate forward using configured force model
    # 3. Return final state + key metrics (semi-major axis, eccentricity, period, etc.)
    ...

def run_monte_carlo(
    hypothesis: ManoeuvreHypothesis,
    prediction_horizon_hours: float = 48.0,
    max_workers: int = 8,
) -> np.ndarray:
    """
    Run full Monte Carlo simulation.

    Returns array of shape (N, M) where M is the output state dimension.
    """
    samples = generate_samples(hypothesis)

    propagate_fn = partial(
        propagate_single_sample,
        pre_manoeuvre_state=hypothesis.pre_manoeuvre_state_eci_km,
        propagation_config={
            "force_model": "j2_drag",
            "rtol": 1e-10,
            "atol": 1e-12,
            "integrator": "DOP853",
        },
        prediction_horizon_hours=prediction_horizon_hours,
    )

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(propagate_fn, samples))

    return np.array(results)
```

**Convergence monitoring:** Don't just run 5,000 samples blindly. Monitor statistical convergence:

```python
def check_convergence(
    results: np.ndarray,
    metric_index: int,  # Which column to check (e.g., semi-major axis)
    window_size: int = 500,
    tolerance_fraction: float = 0.01,
) -> bool:
    """
    Check if the running mean/std have stabilised.

    Returns True if the running statistics over the last `window_size` samples
    differ from the overall statistics by less than `tolerance_fraction`.
    """
    if len(results) < 2 * window_size:
        return False

    overall_mean = np.mean(results[:, metric_index])
    overall_std = np.std(results[:, metric_index])

    recent_mean = np.mean(results[-window_size:, metric_index])
    recent_std = np.std(results[-window_size:, metric_index])

    mean_converged = abs(recent_mean - overall_mean) < tolerance_fraction * abs(overall_mean)
    std_converged = abs(recent_std - overall_std) < tolerance_fraction * overall_std

    return mean_converged and std_converged
```

#### 3.4 Result Aggregation & Output Contract

The raw Monte Carlo output is N state vectors. The consumer (decision engine, visualisation, reporting) needs structured statistical summaries:

```python
@dataclass
class MonteCarloResult:
    """Aggregated Monte Carlo output for a single manoeuvre hypothesis."""

    hypothesis: ManoeuvreHypothesis
    prediction_horizon_hours: float
    n_samples_run: int
    n_samples_converged: int        # Samples where propagation completed successfully
    n_samples_diverged: int         # Re-entry, escape, or numerical failure
    converged: bool                 # Statistical convergence achieved

    # Post-manoeuvre orbital element statistics (at prediction horizon)
    sma_km_mean: float
    sma_km_std: float
    sma_km_percentiles: dict[int, float]   # {5: ..., 25: ..., 50: ..., 75: ..., 95: ...}

    ecc_mean: float
    ecc_std: float
    ecc_percentiles: dict[int, float]

    inc_deg_mean: float
    inc_deg_std: float
    inc_deg_percentiles: dict[int, float]

    raan_deg_mean: float
    raan_deg_std: float

    # Position uncertainty cloud (ECI, at prediction horizon)
    position_cloud_eci_km: np.ndarray      # (N, 3) — for visualisation
    position_covariance_eci_km2: np.ndarray # (3, 3) — for analytical use

    # Derived operational metrics
    altitude_range_km: tuple[float, float]   # (min_alt_5th_pctile, max_alt_95th_pctile)
    period_range_minutes: tuple[float, float]
    regime_probabilities: dict[str, float]   # {"LEO": 0.85, "MEO": 0.10, "GEO": 0.05}

    # Threat-specific metrics (if target object specified)
    closest_approach_km_percentiles: dict[int, float] | None = None
    time_to_closest_approach_hours_percentiles: dict[int, float] | None = None

    # Timing metadata
    wall_time_seconds: float
    samples_per_second: float

    # Reproducibility
    random_seed: int
    force_model_description: str
    library_versions: dict[str, str]
```

**Orbit regime classification:** For each sample's final state, classify into LEO/MEO/GEO/HEO based on semi-major axis and eccentricity. Report the probability distribution across regimes — this is one of the most operationally useful outputs ("80% chance it's heading to a GEO transfer orbit").

**Cluster detection within the cloud:** If the Monte Carlo cloud is multi-modal (e.g., the uncertainty in ΔV direction creates two distinct possible target orbits), detect this using DBSCAN or Gaussian Mixture Models on the final orbital elements. Report each cluster separately with its probability weight.

### Performance Budget

Target: 5,000 samples × 48-hour propagation in under 60 seconds on a single workstation (8 cores).

| Component | Budget |
|---|---|
| Sample generation | < 0.1s (vectorised NumPy, trivial) |
| Propagation (per sample) | ~50ms for J2+drag, 48h, LEO |
| Propagation (5000 samples, 8 cores) | ~31s |
| Aggregation | < 1s (vectorised statistics) |
| **Total** | **~32s** |

If J2+drag at 50ms/sample is too slow, the first optimisation is to use the J2 analytical secular propagation (Brouwer theory) which eliminates numerical integration entirely and drops to ~1ms/sample, giving 5,000 samples in ~0.6s on a single core. The accuracy tradeoff is acceptable for the Monte Carlo envelope — you're not using this for precision targeting, you're using it for probability estimation.

---

## Item 4: Decision Engine / "What-If" Capability

### Operational Purpose

The decision engine answers: **"Given what we think the adversary might do, what should we do?"**

This is not an optimiser (yet). It is a scenario evaluator that takes a set of adversary action hypotheses and a set of friendly response options, evaluates all combinations, and ranks outcomes against operational metrics. The operator makes the decision — the tool presents the ranked options with quantified tradeoffs.

### Architecture: Scenario Tree Evaluation

```
                         ┌─────────────────┐
                         │  Current State   │
                         │  (Target + Own   │
                         │   constellation) │
                         └────────┬────────┘
                                  │
                    ┌─────────────┼──────────────┐
                    ▼             ▼               ▼
            ┌──────────┐  ┌──────────┐   ┌──────────────┐
            │ Adversary │  │ Adversary│   │ Adversary    │
            │ Action A  │  │ Action B │   │ Action C     │
            │ (orbit    │  │ (phasing │   │ (no action / │
            │  raise)   │  │  manvr)  │   │  status quo) │
            └─────┬─────┘  └────┬─────┘   └──────┬───────┘
                  │              │                 │
         ┌───────┼───────┐     ...               ...
         ▼       ▼       ▼
    ┌────────┐┌────────┐┌────────┐
    │Response││Response││Response│
    │   1    ││   2    ││   3    │
    │(sensor ││(repo-  ││(no     │
    │ retask)││sition) ││action) │
    └────┬───┘└────┬───┘└────┬───┘
         │         │         │
         ▼         ▼         ▼
    ┌────────┐┌────────┐┌────────┐
    │Evaluate││Evaluate││Evaluate│
    │Outcome ││Outcome ││Outcome │
    │Metrics ││Metrics ││Metrics │
    └────────┘└────────┘└────────┘
```

The tree has three layers:

1. **Adversary actions** — What might they do? Each action is a `ManoeuvreHypothesis` (from Item 3) or a non-manoeuvre action (jamming, nothing, etc.).
2. **Friendly responses** — What can we do in response to each adversary action? Sensor retasking, orbit adjustment, warning posture change, etc.
3. **Outcome evaluation** — For each (adversary action, friendly response) pair, compute operational metrics and score the outcome.

### Data Model

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

class ActionType(Enum):
    MANOEUVRE = "manoeuvre"
    SENSOR_RETASK = "sensor_retask"
    POSTURE_CHANGE = "posture_change"
    ELECTRONIC_WARFARE = "electronic_warfare"
    NO_ACTION = "no_action"

@dataclass
class AdversaryAction:
    """A hypothesised adversary course of action."""
    id: str
    name: str
    description: str
    action_type: ActionType
    probability_estimate: float    # Analyst's estimated likelihood [0, 1]
    confidence: str                # HIGH / MEDIUM / LOW / SPECULATIVE
    manoeuvre_hypothesis: ManoeuvreHypothesis | None = None  # If action_type == MANOEUVRE

@dataclass
class FriendlyResponse:
    """A possible friendly response to an adversary action."""
    id: str
    name: str
    description: str
    action_type: ActionType
    cost_estimate: str             # Qualitative: LOW / MEDIUM / HIGH / VERY_HIGH
    reversibility: str             # REVERSIBLE / PARTIALLY_REVERSIBLE / IRREVERSIBLE
    time_to_execute_hours: float
    manoeuvre_hypothesis: ManoeuvreHypothesis | None = None

@dataclass
class OutcomeMetrics:
    """Quantified outcome of an (adversary_action, friendly_response) pair."""
    adversary_action_id: str
    friendly_response_id: str

    # Custody metrics
    custody_maintained: bool           # Can we still track the target?
    custody_gap_hours: float           # Maximum gap in custody if partially maintained
    time_to_reacquire_hours: float     # Time to regain custody if lost

    # Threat metrics
    closest_approach_km: float         # Minimum distance to protected asset
    time_to_intercept_hours: float     # How long until adversary reaches engagement range
    threat_geometry_score: float       # 0-1 composite: approach angle, relative velocity, etc.

    # Response effectiveness
    response_delay_hours: float        # Time before friendly response takes effect
    delta_v_cost_km_s: float           # Fuel expenditure for friendly manoeuvre (0 if non-manoeuvre)
    sensor_opportunity_cost: str       # What else are we not observing while retasked?

    # Composite score (weighted combination, weights configurable)
    composite_score: float = 0.0

@dataclass
class Scenario:
    """A complete scenario for evaluation."""
    name: str
    description: str
    current_state_epoch_utc: datetime
    adversary_actions: list[AdversaryAction]
    friendly_responses: list[FriendlyResponse]
    evaluation_horizon_hours: float = 48.0

    # Scoring weights (configurable per operational context)
    weight_custody: float = 0.30
    weight_threat_reduction: float = 0.35
    weight_response_cost: float = 0.15
    weight_response_speed: float = 0.20

@dataclass
class ScenarioResult:
    """Complete evaluation of a scenario."""
    scenario: Scenario
    outcome_matrix: list[OutcomeMetrics]   # len = len(adversary) × len(friendly)
    ranked_responses: list[dict]            # Per adversary action, responses ranked by score
    robust_best_response: str | None        # Response that scores best across ALL adversary actions
    computation_time_seconds: float
```

### The Evaluation Loop

```python
def evaluate_scenario(scenario: Scenario) -> ScenarioResult:
    """
    Evaluate all combinations of adversary actions and friendly responses.

    For each adversary action that involves a manoeuvre, the Monte Carlo engine
    (Item 3) is invoked to generate the adversary's post-manoeuvre state distribution.
    Each friendly response is then evaluated against that distribution.
    """
    outcomes: list[OutcomeMetrics] = []

    for adv_action in scenario.adversary_actions:
        # If adversary manoeuvres, run Monte Carlo to get their probability cloud
        adv_state_distribution = None
        if adv_action.manoeuvre_hypothesis is not None:
            mc_result = run_monte_carlo(
                adv_action.manoeuvre_hypothesis,
                prediction_horizon_hours=scenario.evaluation_horizon_hours,
            )
            adv_state_distribution = mc_result

        for friendly_resp in scenario.friendly_responses:
            metrics = compute_outcome_metrics(
                adv_action=adv_action,
                adv_state_distribution=adv_state_distribution,
                friendly_response=friendly_resp,
                evaluation_horizon=scenario.evaluation_horizon_hours,
                weights={
                    "custody": scenario.weight_custody,
                    "threat_reduction": scenario.weight_threat_reduction,
                    "response_cost": scenario.weight_response_cost,
                    "response_speed": scenario.weight_response_speed,
                },
            )
            outcomes.append(metrics)

    # Rank responses per adversary action
    ranked = rank_responses(outcomes, scenario)

    # Find robust best response (minimax or expected-value across adversary actions)
    robust_best = find_robust_response(ranked, scenario)

    return ScenarioResult(
        scenario=scenario,
        outcome_matrix=outcomes,
        ranked_responses=ranked,
        robust_best_response=robust_best,
        computation_time_seconds=0.0,  # Populated by timing decorator
    )
```

### Robust Response Selection

Two strategies for picking the "best" response when you're uncertain which adversary action will occur:

**Expected Value:** Weight each outcome by the adversary action's estimated probability. Best when you trust your probability estimates.

```python
# E[score(response_j)] = Σ_i P(adversary_action_i) × score(action_i, response_j)
```

**Minimax:** Pick the response that maximises the worst-case outcome across all adversary actions. Best when probability estimates are unreliable and you want to hedge.

```python
# minimax_score(response_j) = min_i score(action_i, response_j)
# best_response = argmax_j minimax_score(response_j)
```

Make the strategy selectable in config. Default to minimax for the SIPC use case — in orbital warfare, you want to hedge against the worst case unless you have strong intelligence on adversary intent.

### Output Format for Operators

The decision engine output should be a ranked table per adversary action, plus a robust recommendation:

```
╔══════════════════════════════════════════════════════════════════════╗
║ SCENARIO: Potential GEO RPO Approach on ASSET-1                     ║
║ Evaluation Horizon: 48 hours                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║ IF ADVERSARY: Orbit Raise to GEO Belt (P=0.60, Confidence: MEDIUM)   ║
║ ┌──────────────────┬───────┬──────────┬───────────┬────────────────┐ ║
║ │ Our Response      │ Score │ Custody  │ Threat ↓  │ Cost           │ ║
║ ├──────────────────┼───────┼──────────┼───────────┼────────────────┤ ║
║ │ Retask Sensor X   │ 0.82  │ MAINTAIN │ MODERATE  │ LOW (opp cost) │ ║
║ │ Reposition Sat Y  │ 0.71  │ MAINTAIN │ LOW       │ HIGH (0.05km/s)│ ║
║ │ No Action          │ 0.35  │ LOST 6h  │ HIGH      │ NONE           │ ║
║ └──────────────────┴───────┴──────────┴───────────┴────────────────┘ ║
║                                                                      ║
║ IF ADVERSARY: Phasing Manoeuvre (P=0.25, Confidence: LOW)            ║
║ ┌──────────────────┬───────┬──────────┬───────────┬────────────────┐ ║
║ │ Our Response      │ Score │ Custody  │ Threat ↓  │ Cost           │ ║
║ ├──────────────────┼───────┼──────────┼───────────┼────────────────┤ ║
║ │ Retask Sensor X   │ 0.78  │ MAINTAIN │ MODERATE  │ LOW            │ ║
║ │ No Action          │ 0.52  │ PARTIAL  │ MODERATE  │ NONE           │ ║
║ │ Reposition Sat Y  │ 0.45  │ MAINTAIN │ LOW       │ HIGH           │ ║
║ └──────────────────┴───────┴──────────┴───────────┴────────────────┘ ║
║                                                                      ║
║ ══ ROBUST RECOMMENDATION (Minimax) ══                                ║
║ ➤ Retask Sensor X — best worst-case across all adversary actions     ║
║ ➤ Scores: min=0.78, mean=0.80, max=0.82                             ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Implementation Phasing

| Phase | Scope | Effort |
|---|---|---|
| Phase 1 | Data model + single adversary action + single friendly response evaluation. No Monte Carlo integration — use deterministic propagation. Validate the scoring framework. | 1 week |
| Phase 2 | Integrate Monte Carlo (Item 3) for adversary action propagation. Evaluate against stochastic outcomes. | 1 week |
| Phase 3 | Full combinatorial evaluation with multiple adversary actions and responses. Ranking and robust selection. | 1 week |
| Phase 4 | Operator-facing output formatting (table, dashboard widget, export to report). Configurable scoring weights. | 1 week |

---

## Item 7: Historical NOTSO Correlation with Manoeuvre Detection

### Operational Purpose

Notices to Space Operators (NOTSOs) are issued by satellite operators (via USSPACECOM or bilaterally) to warn of planned manoeuvres, de-orbits, or unusual activities. Correlating historical NOTSOs with manoeuvres detected in your TLE-based Pattern of Life analysis answers several intelligence questions:

1. **Does this operator notify before manoeuvring?** If historically they always file a NOTSO 24h before manoeuvring, a new NOTSO is a leading indicator.
2. **Does this operator manoeuvre without notification?** If TLE analysis shows manoeuvres with no corresponding NOTSO, this is behaviourally significant.
3. **Are NOTSOs accurate?** Does the predicted manoeuvre window and magnitude in the NOTSO match what actually happened?
4. **Are there patterns in NOTSO timing?** Does the operator consistently notify X hours before execution?
5. **Do NOTSOs reveal anything not visible in TLEs?** A NOTSO might describe a planned attitude manoeuvre (no orbit change) or an electromagnetic test — events invisible to TLE analysis.

### Data Model

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class NOTSOType(Enum):
    MANOEUVRE = "manoeuvre"
    DEORBIT = "deorbit"
    LAUNCH = "launch"
    PROXIMITY_OPS = "proximity_operations"
    TEST = "test"
    OTHER = "other"

@dataclass
class NOTSORecord:
    """Parsed NOTSO message."""
    message_id: str
    norad_id: int                          # Object referenced
    international_designator: str | None
    object_name: str | None
    issuing_entity: str                    # Operator or delegation
    issue_date_utc: datetime               # When the NOTSO was filed
    effective_start_utc: datetime           # Start of activity window
    effective_end_utc: datetime             # End of activity window
    notso_type: NOTSOType
    description: str                        # Free-text description
    predicted_delta_v_km_s: float | None    # If included in NOTSO
    predicted_direction: str | None         # "along-track", "cross-track", etc.
    raw_message: str                        # Original message text for audit

@dataclass
class ManoeuvreDetection:
    """A manoeuvre detected from TLE analysis."""
    norad_id: int
    detection_epoch_utc: datetime           # Estimated manoeuvre epoch
    detection_method: str                   # "element_differencing", "ML", etc.
    estimated_delta_v_km_s: float
    estimated_direction_ric: tuple[float, float, float]  # (R, I, C) components
    confidence: str                         # HIGH / MEDIUM / LOW
    pre_manoeuvre_tle_epoch: datetime
    post_manoeuvre_tle_epoch: datetime

@dataclass
class NOTSOManoeuvreCorrelation:
    """A correlated pair: NOTSO + detected manoeuvre (or unpaired)."""
    notso: NOTSORecord | None
    manoeuvre: ManoeuvreDetection | None
    correlation_type: str                  # "matched", "notso_only", "manoeuvre_only"
    time_offset_hours: float | None        # NOTSO effective time minus manoeuvre epoch
    magnitude_ratio: float | None          # NOTSO predicted ΔV / detected ΔV
    notes: str = ""
```

### Correlation Algorithm

The correlation is a temporal matching problem with fuzzy boundaries. A NOTSO's effective window (start→end) should bracket a detected manoeuvre epoch if they're related.

```python
from datetime import timedelta

def correlate_notsos_with_manoeuvres(
    notsos: list[NOTSORecord],
    manoeuvres: list[ManoeuvreDetection],
    norad_id: int,
    time_tolerance_hours: float = 24.0,
) -> list[NOTSOManoeuvreCorrelation]:
    """
    Correlate NOTSOs with detected manoeuvres for a single object.

    Matching logic:
    1. A NOTSO matches a manoeuvre if the manoeuvre epoch falls within
       [effective_start - tolerance, effective_end + tolerance].
    2. If multiple manoeuvres match a NOTSO, select the closest in time.
    3. If multiple NOTSOs match a manoeuvre, select the closest effective_start.
    4. Unmatched NOTSOs → "notso_only" (NOTSO filed but no manoeuvre detected).
    5. Unmatched manoeuvres → "manoeuvre_only" (manoeuvre detected without NOTSO).

    Parameters
    ----------
    time_tolerance_hours : float
        Allows for manoeuvres slightly outside the NOTSO window (execution
        delays, window extensions). Default 24h is conservative.
    """
    tolerance = timedelta(hours=time_tolerance_hours)
    obj_notsos = [n for n in notsos if n.norad_id == norad_id]
    obj_manoeuvres = [m for m in manoeuvres if m.norad_id == norad_id]

    matched_notsos: set[str] = set()
    matched_manoeuvres: set[datetime] = set()
    correlations: list[NOTSOManoeuvreCorrelation] = []

    # Sort by time for efficient matching
    obj_notsos.sort(key=lambda n: n.effective_start_utc)
    obj_manoeuvres.sort(key=lambda m: m.detection_epoch_utc)

    # Match NOTSOs to manoeuvres
    for notso in obj_notsos:
        window_start = notso.effective_start_utc - tolerance
        window_end = notso.effective_end_utc + tolerance

        candidates = [
            m for m in obj_manoeuvres
            if window_start <= m.detection_epoch_utc <= window_end
            and m.detection_epoch_utc not in matched_manoeuvres
        ]

        if candidates:
            # Select closest manoeuvre to window midpoint
            window_mid = notso.effective_start_utc + (
                notso.effective_end_utc - notso.effective_start_utc
            ) / 2
            best = min(candidates, key=lambda m: abs(
                (m.detection_epoch_utc - window_mid).total_seconds()
            ))

            time_offset = (
                notso.effective_start_utc - best.detection_epoch_utc
            ).total_seconds() / 3600

            mag_ratio = None
            if notso.predicted_delta_v_km_s and best.estimated_delta_v_km_s > 0:
                mag_ratio = notso.predicted_delta_v_km_s / best.estimated_delta_v_km_s

            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=best,
                correlation_type="matched",
                time_offset_hours=time_offset,
                magnitude_ratio=mag_ratio,
            ))
            matched_notsos.add(notso.message_id)
            matched_manoeuvres.add(best.detection_epoch_utc)
        else:
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=None,
                correlation_type="notso_only",
                time_offset_hours=None,
                magnitude_ratio=None,
                notes="NOTSO filed but no manoeuvre detected in TLE analysis",
            ))
            matched_notsos.add(notso.message_id)

    # Find unmatched manoeuvres
    for manoeuvre in obj_manoeuvres:
        if manoeuvre.detection_epoch_utc not in matched_manoeuvres:
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=None,
                manoeuvre=manoeuvre,
                correlation_type="manoeuvre_only",
                time_offset_hours=None,
                magnitude_ratio=None,
                notes="Manoeuvre detected without any associated NOTSO",
            ))

    return correlations
```

### Pattern Extraction

Once you have the correlation dataset, extract behavioural patterns:

```python
@dataclass
class OperatorBehaviourProfile:
    """Extracted patterns from NOTSO-manoeuvre correlations for a single operator/object."""
    norad_id: int
    analysis_period_start: datetime
    analysis_period_end: datetime

    # Notification behaviour
    total_manoeuvres_detected: int
    manoeuvres_with_notso: int
    manoeuvres_without_notso: int
    notification_rate: float                    # manoeuvres_with_notso / total

    # Timing patterns
    mean_notification_lead_time_hours: float    # How far ahead they notify
    std_notification_lead_time_hours: float
    min_notification_lead_time_hours: float
    max_notification_lead_time_hours: float

    # Accuracy patterns
    mean_magnitude_ratio: float                 # Predicted ΔV / Actual ΔV
    std_magnitude_ratio: float
    window_accuracy_rate: float                 # Fraction where manoeuvre fell within NOTSO window

    # NOTSOs without detected manoeuvres
    phantom_notso_count: int                    # NOTSOs filed but no manoeuvre detected
    phantom_notso_types: dict[NOTSOType, int]   # Breakdown by type

    # Behavioural flags
    consistent_notifier: bool       # >90% notification rate
    inconsistent_notifier: bool     # 30-90% notification rate
    stealth_operator: bool          # <30% notification rate
    predictable_timing: bool        # std_lead_time < 6 hours

    def summary(self) -> str:
        """Human-readable behavioural summary for operator briefing."""
        ...
```

### Analytical Questions This Enables

| Question | How to Answer | Operational Value |
|---|---|---|
| "Is this operator transparent?" | notification_rate > 0.9 | Baseline trust level for diplomatic/operational context |
| "Should we expect a manoeuvre soon?" | New NOTSO filed + operator's typical lead time | Early warning — pre-position sensors |
| "Was that manoeuvre planned or reactive?" | Check if NOTSO preceded it | Distinguishes routine ops from responsive behaviour |
| "Are they testing unannounced capabilities?" | manoeuvre_only events, especially unusual ΔV profiles | Intelligence indicator of capability development |
| "Do their NOTSOs accurately predict behaviour?" | magnitude_ratio and window_accuracy_rate | Calibrates how much to trust their future NOTSOs |

### Data Source Considerations

- **NOTSO format:** These are typically semi-structured text messages. You'll need a parser that extracts the key fields (object ID, window, type). Expect variation in format — some operators use structured templates, others use free text.
- **Historical depth:** The value of this analysis increases with historical depth. 6+ months gives you seasonal patterns; 2+ years gives you long-term behavioural baselines.
- **Integration with UDL:** If NOTSOs come through UDL, they'll benefit from the same REAL/SIMULATED/EXERCISE/TEST filtering you're implementing in Item 1.

---

## Item 8: Historical Photometry Analysis

### Operational Purpose

Photometry — the measurement of an object's brightness over time — is a powerful indicator of physical state changes. A satellite's brightness depends on its shape, size, surface materials, orientation (attitude), and the observation geometry (solar phase angle, range, observer position). If you control for the geometric and seasonal factors, residual changes in brightness indicate something physically changed on the spacecraft: attitude adjustment, solar panel deployment/retraction, antenna repositioning, physical damage, or deliberate modification.

For SIPC, this enables characterisation questions: "Has this object's physical configuration changed? When? Can we correlate the change with a manoeuvre or operational event?"

### The Signal Separation Problem

The core challenge is that observed brightness is the product of multiple effects, most of which are not interesting:

```
Observed Magnitude = Intrinsic Brightness
                   + Range Effect (1/r² for reflected sunlight)
                   + Solar Phase Angle Effect (object-sun-observer geometry)
                   + Aspect Angle Effect (which face is toward the observer)
                   + Atmospheric Extinction (airmass correction)
                   + Seasonal Solar Declination Effect
                   + Lunar Contamination (near full moon)
                   + Sensor Calibration Drift
                   + Random Measurement Noise
```

Only the **intrinsic brightness** term reveals physical state changes. Everything else must be modelled and removed.

### Architecture

```
┌──────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│ Raw Photometry│───▶│ Geometric         │───▶│ Baseline Model      │
│ Observations  │    │ Corrections       │    │ (historical fit)    │
│ (time, mag,   │    │ - Range norm      │    │ - Phase function    │
│  filter, site)│    │ - Airmass corr    │    │ - Aspect function   │
└──────────────┘    │ - Solar phase     │    │ - Seasonal terms    │
                     │   angle calc      │    └──────────┬──────────┘
                     └──────────────────┘               │
                                                         ▼
                                               ┌─────────────────────┐
                                               │ Residual Analysis    │
                                               │ - Baseline subtract  │
                                               │ - Change detection   │
                                               │ - Anomaly scoring    │
                                               └──────────┬──────────┘
                                                          │
                                                          ▼
                                               ┌─────────────────────┐
                                               │ Assessment           │
                                               │ - True change?       │
                                               │ - Correlated with    │
                                               │   manoeuvre/event?   │
                                               │ - Confidence level   │
                                               └─────────────────────┘
```

### Component Design

#### 8.1 Geometric Corrections

```python
import numpy as np
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PhotometryObservation:
    """Single photometric measurement."""
    epoch_utc: datetime
    apparent_magnitude: float          # Observed magnitude (lower = brighter)
    magnitude_uncertainty: float       # 1-sigma measurement error
    filter_band: str                   # "V", "R", "B", "Clear", etc.
    observer_lat_deg: float
    observer_lon_deg: float
    observer_alt_km: float
    airmass: float | None              # If not provided, compute from elevation
    elevation_deg: float               # Object elevation above horizon
    range_km: float                    # Observer-to-object distance
    solar_phase_angle_deg: float       # Sun-object-observer angle
    solar_elongation_deg: float        # Sun-observer-object angle
    lunar_phase_fraction: float        # 0=new, 1=full
    lunar_angular_separation_deg: float # Angular distance to moon

@dataclass
class CorrectedObservation:
    """Observation after geometric corrections, ready for baseline modelling."""
    epoch_utc: datetime
    reduced_magnitude: float           # Corrected to standard range (1000 km)
    solar_phase_angle_deg: float       # Retained for phase function fitting
    aspect_angle_deg: float | None     # If attitude/orientation is known
    filter_band: str
    quality_flag: str                  # "good", "lunar_contamination", "low_elevation"
    original: PhotometryObservation


def apply_geometric_corrections(
    obs: PhotometryObservation,
    standard_range_km: float = 1000.0,
) -> CorrectedObservation:
    """
    Reduce observed magnitude to a standard range and correct for atmospheric extinction.

    Range normalisation: m_reduced = m_obs - 5 * log10(range_km / standard_range_km)

    Atmospheric extinction: Uses Rozenberg (1966) airmass model for
    elevations > 5 deg. Observations below 5 deg elevation are flagged
    as unreliable.

    Lunar contamination: Observations within 30 deg of a >75% illuminated
    moon are flagged.
    """
    # Range normalisation
    range_correction = 5.0 * np.log10(obs.range_km / standard_range_km)
    reduced_mag = obs.apparent_magnitude - range_correction

    # Atmospheric extinction (approximate V-band extinction coefficient)
    extinction_coeff = 0.12  # mag/airmass, typical clear site, V-band
    if obs.airmass is not None:
        atmospheric_correction = extinction_coeff * obs.airmass
    elif obs.elevation_deg > 5.0:
        # Compute airmass from elevation (Rozenberg approximation)
        airmass = 1.0 / (
            np.sin(np.radians(obs.elevation_deg))
            + 0.025 * np.exp(-11.0 * np.sin(np.radians(obs.elevation_deg)))
        )
        atmospheric_correction = extinction_coeff * airmass
    else:
        atmospheric_correction = 0.0  # Flag as unreliable instead

    reduced_mag -= atmospheric_correction

    # Quality flagging
    quality = "good"
    if obs.elevation_deg < 5.0:
        quality = "low_elevation"
    elif (obs.lunar_phase_fraction > 0.75
          and obs.lunar_angular_separation_deg < 30.0):
        quality = "lunar_contamination"

    return CorrectedObservation(
        epoch_utc=obs.epoch_utc,
        reduced_magnitude=reduced_mag,
        solar_phase_angle_deg=obs.solar_phase_angle_deg,
        aspect_angle_deg=None,  # Requires attitude knowledge
        filter_band=obs.filter_band,
        quality_flag=quality,
        original=obs,
    )
```

#### 8.2 Baseline Model

The baseline model captures the expected brightness as a function of observing geometry. The primary variable is solar phase angle; secondary effects include seasonal variation (the sun's declination changes the distribution of phase angles accessible from a given site) and long-term calibration drift.

**Phase function fitting:** For most satellites, a low-order polynomial or piecewise linear fit to (phase_angle → reduced_magnitude) captures the dominant behaviour. Specular reflections (glints) create outlier bright points that should be flagged, not fitted.

```python
from scipy.optimize import curve_fit

def phase_function_model(
    phase_angle_deg: np.ndarray,
    a0: float,
    a1: float,
    a2: float,
) -> np.ndarray:
    """
    Quadratic phase function: m = a0 + a1*α + a2*α²

    Parameters
    ----------
    phase_angle_deg : array
        Solar phase angle in degrees [0, 180].
    a0, a1, a2 : float
        Fit coefficients.

    Returns
    -------
    array
        Predicted reduced magnitude at each phase angle.
    """
    alpha = phase_angle_deg
    return a0 + a1 * alpha + a2 * alpha**2


def fit_baseline(
    observations: list[CorrectedObservation],
    min_observations: int = 30,
    outlier_sigma: float = 3.0,
) -> dict:
    """
    Fit a phase function baseline from historical observations.

    Uses iterative sigma-clipping to remove glints and outliers.

    Returns
    -------
    dict with keys:
        'coefficients': (a0, a1, a2) — fit parameters
        'covariance': (3, 3) array — parameter covariance
        'residual_std': float — standard deviation of fit residuals
        'n_observations_used': int
        'n_outliers_removed': int
        'phase_angle_coverage_deg': (min, max) — range of phase angles in data
        'fit_epoch_range': (earliest, latest) — time span of training data
    """
    # Filter to good-quality observations
    good_obs = [o for o in observations if o.quality_flag == "good"]

    if len(good_obs) < min_observations:
        raise ValueError(
            f"Insufficient observations for baseline fit: "
            f"{len(good_obs)} < {min_observations}"
        )

    phases = np.array([o.solar_phase_angle_deg for o in good_obs])
    mags = np.array([o.reduced_magnitude for o in good_obs])

    # Iterative sigma-clipping fit
    mask = np.ones(len(phases), dtype=bool)
    n_removed = 0

    for iteration in range(5):  # Max 5 clipping iterations
        popt, pcov = curve_fit(
            phase_function_model,
            phases[mask],
            mags[mask],
            p0=[7.0, 0.01, 0.0001],  # Initial guess
        )

        residuals = mags - phase_function_model(phases, *popt)
        residual_std = np.std(residuals[mask])

        new_mask = np.abs(residuals) < outlier_sigma * residual_std
        newly_removed = np.sum(mask & ~new_mask)

        if newly_removed == 0:
            break

        mask = new_mask
        n_removed += newly_removed

    return {
        "coefficients": tuple(popt),
        "covariance": pcov,
        "residual_std": residual_std,
        "n_observations_used": int(np.sum(mask)),
        "n_outliers_removed": n_removed,
        "phase_angle_coverage_deg": (float(phases[mask].min()), float(phases[mask].max())),
        "fit_epoch_range": (
            min(o.epoch_utc for o, m in zip(good_obs, mask) if m),
            max(o.epoch_utc for o, m in zip(good_obs, mask) if m),
        ),
    }
```

#### 8.3 Change Detection

With a fitted baseline, compute residuals for new observations and test for statistically significant deviations.

```python
@dataclass
class PhotometryChangeAssessment:
    """Assessment of whether a true brightness change has occurred."""
    object_norad_id: int
    assessment_epoch_utc: datetime
    baseline_epoch_range: tuple[datetime, datetime]

    # Statistical test results
    mean_residual_recent: float         # Mean residual over recent window
    std_residual_recent: float
    mean_residual_baseline: float       # Should be ~0 by definition
    std_residual_baseline: float
    n_recent_observations: int

    # Significance testing
    t_statistic: float                  # Student's t-test statistic
    p_value: float                      # Two-sided p-value
    significant_at_95: bool
    significant_at_99: bool

    # Change characterisation
    magnitude_change: float             # Positive = dimmer, negative = brighter
    change_direction: str               # "brighter", "dimmer", "no_change"
    estimated_change_epoch: datetime | None  # When did the change start?

    # Confidence assessment
    assessment_confidence: str          # HIGH / MEDIUM / LOW
    confounding_factors: list[str]      # Factors that reduce confidence
    correlated_events: list[str]        # Known manoeuvres, NOTSOs, etc. near change epoch

    def summary(self) -> str:
        """Operator-readable assessment."""
        if not self.significant_at_95:
            return (
                f"No statistically significant brightness change detected. "
                f"Mean residual {self.mean_residual_recent:+.2f} mag "
                f"(p={self.p_value:.3f})."
            )
        return (
            f"SIGNIFICANT brightness change detected: {self.magnitude_change:+.2f} mag "
            f"({self.change_direction}). "
            f"Estimated onset: {self.estimated_change_epoch}. "
            f"Confidence: {self.assessment_confidence}. "
            f"p-value: {self.p_value:.4f}."
        )
```

#### 8.4 Visualisation Requirements

Photometry analysis benefits enormously from visual inspection. Build these standard plots:

| Plot | Purpose | Library |
|---|---|---|
| **Phase curve** — reduced magnitude vs solar phase angle, with baseline fit and recent observations highlighted | Confirm baseline quality; visually spot deviations | Matplotlib or Plotly |
| **Light curve** — reduced magnitude vs time, with baseline prediction band (±2σ) | See temporal evolution; identify change onset | Plotly (interactive zoom needed for long time series) |
| **Residual time series** — baseline-subtracted magnitude vs time | Isolate changes from geometry; detect trends | Plotly |
| **Seasonal overlay** — residuals folded by time-of-year (day 1–365) | Detect annual patterns not captured by phase function | Matplotlib |
| **Glint profile** — very bright outliers plotted against phase angle and time | Characterise specular reflection geometry (attitude indicator) | Matplotlib |

### Confounding Factors & Confidence Reduction

An apparent brightness change can be caused by factors other than a physical change on the spacecraft. The assessment must flag these:

| Confounding Factor | Detection | Mitigation |
|---|---|---|
| Sensor calibration drift | Compare photometry of known-stable reference stars observed same night | Require multi-night, multi-site confirmation |
| Atmospheric conditions | Anomalous extinction from clouds, dust, smoke | Check nearby photometric standard star residuals |
| Phase angle coverage gap | Recent data only covers different phase angles than baseline | Flag if phase angle overlap < 50% |
| Attitude-coupled brightness | Normal operational attitude changes cause periodic brightness variation | Build attitude-aware model if attitude data available; otherwise flag as potential confounder |
| Proximity to other objects | Blended photometry from nearby object | Check catalogue for objects within sensor resolution element |

### Integration with Other SIPC Components

- **Manoeuvre correlation (Items 3/4/7):** When a brightness change is detected, query the manoeuvre detection timeline. If a manoeuvre occurred within ±48h of the estimated brightness change onset, flag the correlation. A manoeuvre followed by a brightness change strongly suggests an attitude adjustment or appendage deployment post-manoeuvre.
- **NOTSO correlation (Item 7):** Check if any NOTSO was filed near the brightness change epoch. A NOTSO mentioning "reconfiguration" or "testing" correlated with a brightness change is a strong indicator.
- **Pattern of Life:** The baseline brightness model itself *is* part of the PoL. A stable object suddenly changing brightness is a PoL break — even if you can't determine the cause, it's worth flagging operationally.

---

## Cross-Cutting Dependencies

```
Item 1 (UDL datatype separation)
  ├──▶ Item 2 (TLE filtering) — needs clean data
  │     └──▶ Item 3 (Monte Carlo) — needs filtered TLE sequences for pre-manoeuvre state
  │           └──▶ Item 4 (Decision Engine) — consumes MC outputs
  ├──▶ Item 7 (NOTSO correlation) — needs REAL/EXERCISE separation on NOTSO data
  └──▶ Item 8 (Photometry) — needs clean observation data

Item 2 ──▶ Item 7 (manoeuvre detections feed into NOTSO correlation)
Item 7 ──▶ Item 8 (NOTSO events correlated with brightness changes)
```

Items 7 and 8 are largely independent of each other and can be developed in parallel once Items 1 and 2 are complete. Items 3 and 4 are sequential — the decision engine depends on Monte Carlo being functional.
