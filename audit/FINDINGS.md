# SPECTRE audit: confirmed findings (phase 8.1)

**Source audited:** tree at `a34e273`. **Confirmed:** 296 findings, Blocker 8, High 49, Medium 127, Low 112. Every finding below passed the phase 7 refutation (`audit/REFUTATION.md`), and its severity is the post-refutation one. Each carries its origin ID (slice review, or S00 for orchestrator findings) so it can be traced to the slice reasoning and the refuter's check. UNPROVEN candidates are kept out of this file and listed in the appendix of `audit/REFUTATION.md`.

Evidence fragments are verbatim from the cited lines. A script checked all 317 candidate fragments against the tree before refutation: 317 matched.

## Verdict (phase 8.6)

**Not safe to rely on for operational decisions in its current state. Not yet safe to change at pace. It does about half of what it says it does.**

● **Running it** is mechanically sound. The suite passes, the container contract job is green, the security headers, CSRF binding, session revocation and bcrypt storage hold, and the Lambert core and the ΔV estimator check out against textbook references. But eight Blockers are confirmed, most by execution:
  ■ Seven present numerically wrong output as computed: minimum-time intercepts at 1 % of the Hohmann time (F-S02-01), CW drift at −0.5 times its true value (F-S02-03), a double degree conversion in manoeuvre detection (F-S01-01), a plane change that ignores RAAN (F-S01-02), retrograde Lambert arcs (F-S01-03), the CW initial-velocity frame (F-S02-04), and GEO drift reading hours as days (F-S06-01).
  ■ One defeats the login brute-force control (F-S08-01).
  ■ The repository also commits and ships 500 real notifications under a dissemination marking that needs a handling decision (F-S07-05, `audit/GAPS.md` 1.1).

● **Changing it** is unsafe until CI runs. Three of seven CI jobs on master fail before executing a single check (F-S00-01). Branch coverage is 70.96 %. A mutation sample shows the green suite does not notice session expiry being removed, DELETE losing CSRF protection, or the July 2026 threat-sweep defect being put back (`audit/TESTS.md`).

● **Doing what it says**: 126 of 316 claims are DRIFTED and 94 are PROVEN (`audit/CLAIMS.md`). Of the ten July 2026 priors, eight are still present in whole or part and two are fixed without a gate (`audit/PRIORS-STATUS.md`), including the agreed "modelled estimate" labelling, which was never built.

The fix order is in `audit/REMEDIATION.md`:
1. the Blockers;
2. making CI execute;
3. the 125 single-location quick wins;
4. the structural clusters.

The first structural cluster is identity keyed on username, and the second is heuristic labelling.

## Blocker

```
ID:          F-001   (origin F-S01-01)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:923-926
Evidence:
               result = classify_manoeuvre(
               kep_before.a, kep_before.ecc, _m.degrees(kep_before.inc), _m.degrees(kep_before.raan),
               kep_after.a, kep_after.ecc, _m.degrees(kep_after.inc), _m.degrees(kep_after.raan),
Issue:       KeplerianElements angles are already degrees (propagator.py:56-57), so manoeuvre_detect_intercept multiplies inclination and RAAN by 57.3 before classify_manoeuvre, the exact defect the comment at maneuvers.py:611 says was fixed; the static guard at tests/unit/test_orbital_units_and_degeneracies.py:125 skips any line without the literal `math.degrees(`, so the `import math as _m` alias hides it.
Impact:      Worked case: LEO at 7.67 km/s with a real 0.1 deg inclination trim. classify_manoeuvre (tactical.py:824) computes 2·7.67·sin(5.73°/2) = 0.767 km/s instead of 2·7.67·sin(0.05°) = 0.0134 km/s, 57 times too high. The 0.05 deg plane-change threshold (tactical.py:836) effectively drops to 0.00087 deg, so TLE noise is classified as a plane change. j2_raan_rate gets a 57x inclination. This is reachable from the operator UI via InterceptMethod.MANOEUVRE_DETECT (spectre/web/routes/maneuver.py:1310).
Fix:         Pass kep_before.inc, kep_before.raan, kep_after.inc and kep_after.raan unconverted. Delete the local `import math as _m` at maneuvers.py:850 and :918.
Gate:        Widen the guard regex to `\b\w+\.degrees\(` (and drop the `"math.degrees(" not in line` prefilter), plus a numeric test pinning manoeuvre_detect_intercept's estimated ΔV for a synthesised 0.1 deg trim to 2v·sin(Δi/2) within 1 per cent.
Verdict:     CONFIRMED
```

```
ID:          F-002   (origin F-S01-02)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:616-623
Evidence:
               inc_diff = abs(kep_blue.inc - kep_red.inc)
Issue:       The plane-change angle uses the inclination difference only and ignores RAAN, but the angle between two orbit planes is cos θ = cos i1 cos i2 + sin i1 sin i2 cos ΔΩ (Vallado, Fundamentals of Astrodynamics and Applications, section 6.4, combined inclination and node change; Curtis section 6.10). The docstring at :589 promises to "align red satellite with blue orbital plane".
Impact:      Worked case: two 53 deg LEO planes 10 deg apart in RAAN, as in a Walker shell. The true θ is acos(0.36217 + 0.63783·0.98481) = 7.98 deg, about 1.06 km/s at 7.6 km/s. The code returns inc_diff = 0 and a ΔV of zero, so it reports a free plane alignment between planes that are 8 deg apart.
Fix:         Compute θ from the angle between the two angular momentum unit vectors, θ = acos(ĥ_red · ĥ_blue), and pass θ to plane_change. Place the burn at the line of intersection, ĥ_red × ĥ_blue.
Gate:        Unit test with equal inclinations and ΔΩ = 10 deg, asserting ΔV = 2v·sin(θ/2) within 1 per cent.
Verdict:     CONFIRMED
```

```
ID:          F-003   (origin F-S01-03)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  inference
Location:    spectre/astro/lambert.py:95
Evidence:
               long_way = (cross_z < 0) if prograde else (cross_z >= 0)
Issue:       "Prograde" means positive h_z (Curtis Algorithm 5.2 convention). lambert_intercept and intercept_envelope_intercept always use the default prograde=True, so for any retrograde orbit (inclination above 90 deg, which includes every sun-synchronous orbit) the forward short arc has cross_z < 0 and the solver selects the 2π − Δθ arc. That arc counter-rotates against the satellite's own motion. The docstring at :60 also wrongly equates prograde with "short-way".
Impact:      Derivation: with Δθ' = 2π − Δθ, sin Δθ' < 0, so A < 0 and g < 0, and the transfer angular momentum r1 × v1 = (r1 × r2)/g points opposite to the satellite's h. Each burn is then about twice the circular speed, roughly 15 km/s in LEO. For SSO pairs, lambert_intercept reports absurd costs and the envelope sweep raises "No intercept within budget", so a threat-relevant SSO pairing reads as unreachable.
Fix:         In lambert_intercept and the envelope sweep, pass prograde = (np.cross(sv_red.r, sv_red.v)[2] >= 0), or better, change solve_lambert to choose the arc whose normal agrees with r1 × v1_initial whenever v1_initial is supplied.
Gate:        Lambert round-trip case for a 98 deg inclined pair asserting departure ΔV below 1 km/s for a 10 deg in-track hop, and a test that the transfer angular momentum agrees in sign with the departure orbit.
Verdict:     CONFIRMED
```

```
ID:          F-004   (origin F-S02-01)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:2003-2009
Evidence:
               lo, hi = tof_h * 0.01, tof_h  # search between 1% and 100% of Hohmann TOF
               a_est = (mu * (mid / math.pi) ** 2) ** (1.0 / 3.0)
               a_est = max(a_est, max(r1, r2))  # can't be smaller than larger orbit
Issue:       For every trial TOF in the search window the raw a_est is at most a_h = (r1+r2)/2, which is at most max(r1, r2), so the clamp makes a_est the constant max(r1, r2), dv_est does not depend on TOF, and the bisection always collapses to 1% of the Hohmann time whenever the constant dv_est is inside budget. Worked by hand: r1 = 7,000 km, r2 = 8,000 km, budget 1 km/s gives Hohmann 0.487 km/s in 3,232 s, but the routine returns min_tof 32.3 s at 0.458 km/s, faster than Hohmann and cheaper than Hohmann. The arrival term |v2 - v_arr| is also a scalar speed difference that ignores flight-path angle, so it reads 0 at r2.
Impact:      min_time` runs in every threat sweep (spectre/web/routes/threat.py:632) and the worst course of action is the least-warning entry (threat.py:772-775), so a co-orbital GEO pair is reported as interceptable in about 7 minutes for near-zero ΔV and that fabricated threat leads the operator's assessment.
Fix:         Delete the analytic routine or replace it with a Lambert TOF sweep (as `intercept_envelope_intercept` already does); if kept, solve the transfer ellipse from the actual transfer angle and compute ΔV as vector differences.
Gate:        A test asserting min_tof_s >= the Lambert minimum for a fixed LEO pair and that delta_v_km_s >= Hohmann ΔV whenever min_tof_s < Hohmann TOF.
Verdict:     CONFIRMED
```

```
ID:          F-005   (origin F-S02-03)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1557-1558
Evidence:
               drift_indicator = dvy0 + 2.0 * n * dx0
               secular_drift_per_orbit = 3.0 * math.pi * drift_indicator / n  # km per orbit
Issue:       From the CW solution (Curtis eq. 7.53; the repository's own cw_geometry.py:19) the secular along-track term is -3t(ẏ0 + 2n x0), so the drift per orbit is -6π·indicator/n; the code returns +3π·indicator/n, half the magnitude and the wrong sign. By hand, x0 = 1 km, ẏ0 = 0: truth -37.70 km/orbit (also asserted at tests/unit/test_cw_geometry.py:189-191), code +18.85 km/orbit.
Impact:      The stability score and the is_bounded test (threshold 0.1 km/orbit) are taken from a value that is wrong by a factor of -0.5, and the operator sees "Stable relative motion" or the drift direction reversed.
Fix:         secular_drift_per_orbit = -6.0 * math.pi * drift_indicator / n.
Gate:        Test comparing relative_motion_stability drift with `_cw_propagate(state, n, T).y - y0` for a non-bounded state, rel 1e-9.
Verdict:     CONFIRMED
```

```
ID:          F-006   (origin F-S02-04)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:1289-1303 (outside slice; sole caller of relative_motion_stability)
Evidence:
               dv = sv_red.v - sv_blue.v
               dvy0 = float(np.dot(dv, v_hat))
Issue:       The CW initial velocity is the inertial relative velocity projected onto the axes with no ω×r correction, unlike cw_geometry.py:296-299, so the drift indicator computed becomes ẏ_rot + 3n·x instead of ẏ_rot + 2n·x. By hand, a truly bounded NMC state (indicator 0) with x = 1 km is reported as drifting 3π ≈ 9.4 km/orbit before F-S02-03 is applied.
Impact:      Every bounded relative orbit with a radial offset is scored unstable; combined with F-S02-03 the reported drift for two circular co-orbiting objects is +4.5π·Δr instead of -3π·Δr.
Fix:         Reuse cw_geometry._initial_hill_state to build the CW state.
Gate:        Test that stability_intercept on a constructed NMC pair returns score 100.
Verdict:     CONFIRMED
```

```
ID:          F-007   (origin F-S06-01)
Lens:        L11 numerical and scientific correctness
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1278-1279
Evidence:
               if coast_s > _SECONDS_PER_HOUR:
               return coast_s / _SECONDS_PER_HOUR
Issue:       _geo_drift_days` returns the coast time in HOURS and maneuver.py:1374 passes it as `drift_time_days`, which the solver reads as days (`timedelta(days=result.drift_time_days)`, spectre/astro/maneuvers.py geo_drift_intercept docstring "Desired drift duration (days)").
Impact:      Hand check: Coast 48 h gives coast_s 172800, the helper returns 48.0, and the solver plans a 48-day drift, 24 times too long. For a fixed longitude gap the drift rate, hence the semi-major-axis offset and the delta-V, scales with 1/T (inference from Δλ = rate × T), so the GEO relocation row reports roughly 1/24 of the true cost and an arrival 46 days late, as a computed result, with nothing on screen to show it.
Fix:         Return `coast_s / 86400.0` (or add a dedicated drift-days field); name the constant `_SECONDS_PER_DAY`.
Gate:        Unit test: `_geo_drift_days(48 * 3600) == 2.0`; an integration test that the GEO_DRIFT arrival epoch equals start plus the requested days.
Verdict:     CONFIRMED
```

```
ID:          F-008   (origin F-S08-01)
Lens:        L3 security
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/login.py:132-141
Evidence:
               matched = await run_in_threadpool(verify_password, password, hashed)
               if user is None or not matched:
Issue:       The password is verified before either limiter is consulted, and the limiters are consulted only on failure, so an account that has exhausted its budget still accepts a correct password with 302; the 429 is just a renamed 401.
Impact:      Online password guessing is bounded only by bcrypt throughput in the threadpool (inference: of the order of 100 guesses a second per pod), and the guessing loop learns the answer the moment it lands, against a public, CSRF-exempt endpoint; the comment at login.py:54-55 claims the opposite.
Fix:         Call both `is_allowed` checks (or a read-only "is blocked" check) before `run_in_threadpool(verify_password, ...)` and return 429 without verifying when either budget is exhausted; keep charging only on failure.
Gate:        Integration test: exhaust the username tier with 10 wrong passwords, then post the correct password and assert 429 and no `spectre_session` cookie.
Verdict:     CONFIRMED
```

## High

```
ID:          F-009   (origin F-S00-01)
Lens:        L10 Build, config and deploy
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    .github/workflows/ci.yml:31-33
Evidence:
               run: pip install -e ".[dev]"
               run: ruff check spectre/ tests/
Issue:       Three of seven CI jobs (Lint and Type Check, Tests, Quality Gate) fail with exit 127, "command not found", on master, because the install step names a `dev` extra that pyproject.toml does not define, so no tool is installed.
Impact:      The README's security-tooling table and the merge commit's "ruff, mypy clean" describe gates that have not executed in CI on master; any regression merges unchecked by lint, type check, tests or the changed-code quality gate.
Fix:         Install the hash-locked sets the repo already maintains (`pip install --require-hashes -r requirements.txt` then `-r requirements-dev.txt`, after resolving the tomli conflict, F-S00-08) and `pip install --no-deps -e .`; or declare the `dev` extra.
Gate:        A CI step that runs `ruff --version && mypy --version && pytest --version` before the gated steps, and branch protection on master requiring all seven jobs.
Verdict:     CONFIRMED
```

```
ID:          F-010   (origin F-S01-04)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  inference
Location:    spectre/astro/lambert.py:279-288
Evidence:
               z_hi = _Z_PARABOLIC_LIMIT - 1e-6
               f_hi = residual(z_hi)
               if not math.isfinite(f_hi) or f_hi < 0.0:
Issue:       The module docstring (:14-16) says multi-revolution transfers are "rejected explicitly". In fact the time of flight tends to infinity as z approaches 4π², so the residual at z_hi is positive for any realistic TOF. The guard never fires, and the solver silently returns the single-revolution arc for TOFs longer than an orbital period.
Impact:      Worked case: the hand estimate at z_hi gives C ≈ 8e-17 and χ³S ≈ 1e29, against sqrt(mu)·tof ≈ 5e7 for 24 h. For GEO with a 30 deg lead and a 24 h TOF, the solver returns a 30 deg arc flown in 24 h on a highly eccentric ellipse costing km/s, when the 1-revolution solution is a m/s phasing drift. intercept_envelope_intercept defaults to 172,800 s (maneuvers.py:1160), two GEO periods, so most of its sweep is inflated or marked infeasible.
Fix:         Compute the minimum-energy period (or the TOF at the single-revolution/multi-revolution boundary). Raise LambertConvergenceError when tof exceeds one revolution of the candidate transfer, or implement multi-revolution branches (Izzo 2015).
Gate:        Test: GEO r1 and r2 30 deg apart with a 24 h TOF must raise LambertConvergenceError (or return the multi-revolution solution below 50 m/s).
Verdict:     CONFIRMED
```

```
ID:          F-011   (origin F-S01-05)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:200-202
Evidence:
               arrival_epoch=t_arrival,
               miss_distance_km=0.0,
               transfer_result=result,
Issue:       hohmann_intercept departs immediately with no phasing or wait for the correct phase angle. It uses only the radii, never checks where blue is at arrival, and hardcodes miss_distance_km=0.0 (:201).
Impact:      The operator sees a two-burn "intercept" with zero miss when, for an arbitrary phase, red arrives up to a full orbit diameter away from blue. spectre/web/routes/maneuver.py:1306 also maps InterceptMethod.RENDEZVOUS to this function.
Fix:         Either compute the wait time from the Hohmann lead angle, π(1 − ((r1 + r2)/(2 r2))^1.5) (Curtis section 6.? and Vallado Algorithm 44, numbers TBC), and delay departure accordingly, or propagate blue to t_arrival and report the actual miss, the norm of r_red_arr − r_blue_arr.
Gate:        Test that asserts miss_distance_km equals the propagated separation at arrival.
Verdict:     CONFIRMED
```

```
ID:          F-012   (origin F-S01-06)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  inference
Location:    spectre/astro/maneuvers.py:251-256
Evidence:
               sv_red_mid = red_orbit.propagate(t_mid)
               burn2 = _make_burn(2, t_mid, v_hat * result.delta_v_2, sv_red_mid)
Issue:       The bi-elliptic burn 2 at apoapsis reuses the departure velocity direction, which half an ellipse later is antiparallel to the actual velocity. It is decomposed into VNB against red's unmanoeuvred orbit at t_mid, not against the transfer ellipse. Burn 3 (:256) is pointed along blue's velocity, prograde, but circularising at the perigee of ellipse 2 for r2 > r1 needs a retrograde burn, because v_t2_p exceeds sqrt(mu/r2).
Impact:      Per-burn vectors and the dv_prograde, dv_normal and dv_radial breakdowns exported to the plan (spectre/web/routes/plan.py:193-218) have the wrong sign on burns 2 and 3 of a standard raising transfer. The total ΔV magnitude is correct.
Fix:         Propagate the transfer ellipse with a Kepler propagator to obtain the state at rb and r2, and sign each burn from v_after − v_before at that state.
Gate:        Test: for r1 < r2, assert burn 2 dv_prograde > 0 and burn 3 dv_prograde < 0.
Verdict:     CONFIRMED
```

```
ID:          F-013   (origin F-S01-07)
Lens:        L11 numerical and scientific correctness
Severity:    High   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:184-192
Evidence:
               # Departure burn is along velocity direction (prograde).
               v_hat = sv_red.v / sv_red.v_mag
               dv1_vec = v_hat * result.delta_v_1
Issue:       transfers.hohmann returns unsigned magnitudes (abs at transfers.py:54-55), so for a lowering transfer (r2 < r1) both burns are emitted prograde when both must be retrograde.
Impact:      The plan export shows positive prograde ΔV for a descent. An operator following the breakdown would raise the orbit instead of lowering it.
Fix:         Sign each burn by sign(r2 − r1), or have hohmann return signed ΔV.
Gate:        Test: hohmann_intercept with blue below red asserts burns[0].dv_prograde < 0.
Verdict:     CONFIRMED
```

```
ID:          F-014   (origin F-S01-09)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:1068-1074
Evidence:
               blue_orbit = TLEOrbit(blue_tle)
Issue:       evasion_intercept never reads red_tle. The "optimal" evasion and its resulting_miss_km come from blue's radius and generic parameters only, not from the threat's relative geometry, which contradicts the docstring at :1054.
Impact:      The operator is shown a miss distance against an incoming threat that was never modelled, so a computed-looking number has no threat input.
Fix:         Propagate red, compute the relative state at TCA, and size or direct the burn against it, or relabel the method as a generic, threat-independent estimate in the payload and template.
Gate:        Test that two different red TLEs produce different evasion outputs.
Verdict:     CONFIRMED
```

```
ID:          F-015   (origin F-S01-10)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:659-666
Evidence:
               dv1_vec = v_hat * cpc.delta_v_1 * 0.8 + n_hat * cpc.delta_v_1 * 0.6
               dv1_vec = dv1_vec / float(np.linalg.norm(dv1_vec)) * cpc.delta_v_1
Issue:       The combined altitude and plane change gives burn 1 a fixed, uncalibrated 36.9 deg out-of-plane tilt (0.8/0.6) and burn 2 none. combined_altitude_plane_change (tactical.py:401-405) puts the whole plane change on burn 2 when raising and makes burn 1 "prograde only".
Impact:      Burn vectors contradict the ΔV that was priced. The exported direction breakdown is an invented split presented as computed.
Fix:         Derive each burn vector from the cosine-rule geometry actually used: burn 1 along v_hat when raising, and burn 2 composed from v_t_a and v2 rotated by Δi.
Gate:        Test asserting burn 1 dv_normal = 0 for r2 > r1.
Verdict:     CONFIRMED
```

```
ID:          F-016   (origin F-S01-12)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/constants.py:78-84
Evidence:
               if perigee_alt < _LEO_MAX_ALT and apogee_alt > _MEO_MAX_ALT:
               # High apogee + low perigee — GTO or HEO depending on eccentricity
               return "GTO" if apogee_alt > _MEO_MAX_ALT and eccentricity > 0.5 else "HEO"
Issue:       Hand cases: Molniya (a = 26,562 km, e = 0.74) has perigee altitude 528 km and apogee altitude 39,840 km, and e > 0.5, so it returns "GTO". Tundra (a = 42,164 km, e = 0.27) has perigee altitude 24,402 km and e < 0.3, so it falls through to "MEO" at :83-84. The docstring at :66 says the function distinguishes these regimes.
Impact:      regimes_compatible("MEO", "GEO") is False, and the threat sweep and manoeuvre routes gate on it (spectre/web/routes/threat.py:964, :1221; spectre/web/routes/maneuver.py:845, :1094). A Tundra-orbit object is therefore dropped from screening against GEO assets.
Fix:         Classify HEO by eccentricity and apogee above GEO (for example e > 0.25 with apogee above 35,786 km) before the MEO fallback, and reserve GTO for apogee near GEO altitude.
Gate:        Parametrised test with Molniya, Tundra, GTO, GEO, MEO and LEO reference element sets.
Verdict:     CONFIRMED
```

```
ID:          F-017   (origin F-S02-06)
Lens:        L4 contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:986-987 (outside slice; consumer of NMCResult)
Evidence:
               # Radial impulse for in-plane ellipse + normal for cross-track
               dv_vec = b_hat * nmc.radial_amplitude_km * float(np.sqrt(mu / r_ref**3))
Issue:       tactical.py:959-973 records that a radial burn of n·A_x is the defective establishing condition and replaces it with an along-track burn of 2n·A_x from a radial offset, but the wrapper still builds the radial burn and reports total_delta_v from the along-track figure, so the burn shown and the cost shown disagree by 2x and in axis. NMCResult exposes no burn axis, so the contract cannot carry the fix.
Impact:      The operator is shown the burn that tests/unit/test_tactical_validation.py:124-144 proves returns to the target every orbit, labelled with a positive safety margin (miss_distance_km = safety_margin_km at maneuvers.py:998).
Fix:         Add burn-axis fields to NMCResult and build dv_vec as v_hat * delta_v_establish from a state already displaced radially by A_x; refuse when the current relative state is not that offset.
Gate:        Integration test that flies the wrapper's burn through `_cw_propagate` and asserts min range equals the reported margin.
Verdict:     CONFIRMED
```

```
ID:          F-018   (origin F-S02-07)
Lens:        L11 numerical and scientific correctness (computed-versus-modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1324-1358; spectre/web/routes/maneuver.py:597-599
Evidence:
               closing_score = min(1.0, abs(range_rate_km_s) / 1.0)  # normalise to 1 km/s
               score += 0.3 * closing_score
               f"Intent assessment indicates {int(miss)}% probability of intercept "
Issue:       likelihood` is an additive score of uncited weights (0.3, 0.25, 0.15, 0.1) and thresholds (100 km, 1,000 km, 5 km, 200 km, 0.05 degrees), yet the operator template states it as a percentage probability of intercept intent and the result notes say "Computed via spectre.astro ... solver" (maneuver.py:1486).
Impact:      An uncalibrated heuristic is presented to a decision-maker as a probability of hostile intent.
Fix:         Rename to `indicator_score`, show it as "heuristic score (uncalibrated)" in the template, and cite or calibrate the weights.
Gate:        Template test that the intent panel text contains "heuristic" and never "probability".
Verdict:     CONFIRMED
```

```
ID:          F-019   (origin F-S02-08)
Lens:        L11 numerical and scientific correctness (computed-versus-modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1052-1064; spectre/web/routes/maneuver.py:435
Evidence:
               if altitude_km < 2000:  # LEO — dense tracking
               k = 0.5  # per m/s
               {"label": "Detection Probability", "value": _score_band(miss / 100.0)},
Issue:       Detection "probability" is 1 - exp(-k·ΔV) with hand-set k (0.5, 0.2, 0.1), detection times (6, 24, 48 h), type modifiers (1.3, 0.7) and composite weights (0.4, 0.3, 0.3), with no source despite the docstring's SSN claim (claim 20); the GEO branch starts at exactly 35,786 km, so a GEO object at 35,785 km is scored with the MEO constants.
Impact:      A tuned score is labelled "Detection Probability" for the operator.
Fix:         Label as a heuristic score, cite or remove the SSN attribution, and use a regime band around GEO rather than a hard edge.
Gate:        Template test for the heuristic label; unit test at 35,780 km and 35,790 km giving the same regime.
Verdict:     CONFIRMED
```

```
ID:          F-020   (origin F-S02-09)
Lens:        L11 numerical and scientific correctness (computed-versus-modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1611, 1647-1724; spectre/web/routes/maneuver.py:470
Evidence:
               probabilities: dict[str, float]    # classification → probability
               if 35000 < altitude_km < 37000:
               geo_score += 0.4
Issue:       The "probabilities" are independent additive scores of uncited constants that are not normalised (they can sum above 1), and the max is shown to the operator as "Fingerprint Confidence" in percent; the < 0.3 fallback silently sets confidence to the constant 0.1.
Impact:      Behavioural attribution such as "asat_test" is presented with a percentage confidence that has no statistical meaning.
Fix:         Rename to scores, show as uncalibrated, and source each profile constant or remove it.
Gate:        Test that the field is not named probabilities and the template carries the heuristic label.
Verdict:     CONFIRMED
```

```
ID:          F-021   (origin F-S02-10)
Lens:        L11 numerical and scientific correctness (computed-versus-modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:853-873; spectre/web/routes/maneuver.py:484
Evidence:
               if total_dv < 0.001:
               mtype = "station_keeping"
               confidence = 0.3
Issue:       Classification confidence is one of six fixed constants (0.3, 0.85, 0.85, 0.7, 0.75, 0.6) chosen per branch, with uncited thresholds (1 km, 5 km, 0.01 and 0.05 degrees, 0.001 eccentricity), and it reaches the operator as "Detection Confidence" in percent via miss_distance_km (maneuvers.py:940).
Impact:      A lookup constant reads as a computed detection confidence; with F-S02-02 it reads 85% on noise.
Fix:         Report the branch label and the thresholds crossed instead of a percentage, or derive confidence from TLE covariance.
Gate:        Template test for the heuristic label.
Verdict:     CONFIRMED
```

```
ID:          F-022   (origin F-S02-11)
Lens:        L11 numerical and scientific correctness (computed-versus-modelled)
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/tactical.py:1846-1847, 1899-1913
Evidence:
               available space surveillance statistics and radiation belt models.
               elif 5000 < altitude_km <= 12000:
               radiation = "extreme"  # slot/outer belt
Issue:       No statistic or belt model (for example AE8/AP8) is cited or used; the bands are hand-set, and the 5,000 to 12,000 km band, which spans the slot region between the belts, is labelled the most severe while the outer-belt heart near GPS altitude (about 20,200 km) is split between "high" and "moderate".
Impact:      "Operational Risk N/100" (maneuver.py:477) presents an uncited composite (weights 0.4, 0.3, 0.2, 0.1) as a computed assessment, with radiation ordering that a belt model would likely contradict.
Fix:         Cite the source per band or label the output as indicative; check bands against AE8/AP8 or AE9/AP9.
Gate:        Docstring-to-source review; template heuristic label.
Verdict:     CONFIRMED
```

```
ID:          F-023   (origin F-S02-13)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:812, 828-829
Evidence:
               draan = abs(raan2_deg - raan1_deg)
               expected_j2_raan = abs(j2_raan_rate(a1, ecc1, inc1_deg, mu) * dt_s / 86400.0)
               raan_residual = max(0.0, draan - expected_j2_raan)
Issue:       Both observed and predicted RAAN changes are reduced to magnitudes before subtraction, so a manoeuvre that moves the node against the J2 drift is cancelled. By hand, J2 predicts -5 degrees over a day and the object moves +5 degrees: the residual is 0 although the manoeuvre-induced change is 10 degrees.
Impact:      Node-changing manoeuvres opposite to natural precession go undetected.
Fix:         Subtract signed values and wrap: residual = wrap180((raan2 - raan1) - rate·dt).
Gate:        Unit test with the opposite-sign case asserting raan_change is detected.
Verdict:     CONFIRMED
```

```
ID:          F-024   (origin F-S02-15)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:508-527
Evidence:
               delta_a = -50.0 if inc_chaser_deg < 90.0 else 50.0  # km, heuristic step
               v_transfer = math.sqrt(mu * (2.0 / a_chaser - 1.0 / a_transfer))
               accel_dv = abs(v_transfer - v_old)
Issue:       The step is a fixed 50 km in a direction chosen by inclination alone, not by the sign of the RAAN gap, so in half the cases it slows convergence or forces the long way round (the result field says "double convergence rate", claim 10); accel_delta_v is the first Hohmann burn only. By hand, a = 7,000 km to 6,950 km: code 13.5 m/s, a full two-burn change about 27 m/s.
Impact:      J2 drift plans recommend the wrong altitude direction and understate the cost by about half.
Fix:         Choose the sign of Δa from the sign of the required differential rate, solve for the Δa that meets a target time, and cost both burns.
Gate:        Unit tests for both signs of delta_raan asserting accel_convergence_days < convergence_time_days, and ΔV against the two-burn Hohmann closed form.
Verdict:     CONFIRMED
```

```
ID:          F-025   (origin F-S02-22)
Lens:        L4 contracts and data
Severity:    High   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:86, 105; spectre/astro/maneuvers.py:311
Evidence:
               period_phase = period_target * revolutions_to_close / n_revolutions
               v_chaser = math.sqrt(mu / r_chaser)
               result = phasing_orbit(r_red, r_blue, phase_deg, n_revolutions, mu)
Issue:       The closure uses the target period while the burns and return are at r_chaser, so the method is only a rendezvous when r_chaser = r_target, yet nothing checks this and the wrapper always passes two different SGP4 radii.
Impact:      For chaser and target at different altitudes the plan ends with a radial miss equal to the altitude gap while the UI shows "0.0 km" miss (maneuver.py:427).
Fix:         Raise when |r_chaser - r_target| exceeds a stated tolerance, or add the Hohmann leg.
Gate:        Unit test that unequal radii beyond tolerance raise.
Verdict:     CONFIRMED
```

```
ID:          F-026   (origin F-S03-01)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:881-886
Evidence:
               last_dv = manoeuvres[-1].delta_v_km_s if (
               z = (last_dv - dv_stats.mean) / dv_stats.std
               if z > _STATUS_ANOMALOUS_SIGMA:
Issue:       The latest ΔV is scored against a mean and sample std that already include it (dv_vals at line 983 holds every confirmed manoeuvre, and line 992 builds dv_stats from it). By Samuelson's inequality one member of a sample of n can sit at most (n-1)/sqrt(n) sample std from the mean, so ANOMALOUS (z > 3) cannot happen until n >= 11 and CAUTION (z > 2) cannot happen until n >= 6.
Impact:      The status rendered at spectre/web/templates/partials/pol_results.html:87 reads NORMAL for an object whose latest burn is 100 times its only previous one. Hand check: ΔVs [1, 100] m/s give mean 50.5, s 70.0, z 0.71, so NORMAL. Fewer than two confirmed manoeuvres gives dv_stats None and also NORMAL. The ladder test at tests/unit/test_pol_status_ladder.py:62-63 uses n=10 with z up to 4, which a real history cannot produce.
Fix:         Score the latest manoeuvre against stats built from the earlier manoeuvres only (leave-one-out), and require a stated minimum prior n. Below that n, set the status to INSUFFICIENT rather than NORMAL.
Gate:        A unit test that builds a real history from 2 to 12 manoeuvres where the last one is 100 times the rest, and asserts ANOMALOUS from the first n that the rule allows.
Verdict:     CONFIRMED
```

```
ID:          F-027   (origin F-S03-02)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  High
Epistemics:  fact (code); inference (operational impact)
Location:    spectre/astro/notso.py:454-457
Evidence:
               candidates = [
               m for m in obj_manoeuvres
               if window_start <= m.epoch <= window_end
Issue:       NOTSO matching, the midpoint tie-break, lead time and window accuracy all use Manoeuvre.epoch, which spectre/astro/pattern_of_life.py:213-214 documents as "the after-element-set epoch, which can be wrong by the whole gap". The measured Manoeuvre.burn_epoch is ignored.
Impact:      Pairs may be up to 30 days apart (_MAX_GAP_DAYS) and the tolerance is 24 h. A declared burn whose bracketing element set arrives more than a day later is reported as "notso_only", and the same burn is counted under "Silent" in red (spectre/web/templates/partials/notso_results.html:61). The operator is blamed for a burn it did notify, and lead times are biased by the gap.
Fix:         Correlate on m.burn_epoch, and widen the match window to the before/after bracket [tle_before.epoch, tle_after.epoch] when burn_epoch is ambiguous.
Gate:        A test with a manoeuvre whose burn_epoch sits inside the NOTSO window and whose epoch is 3 days later, asserting "matched".
Verdict:     CONFIRMED
```

```
ID:          F-028   (origin F-S03-06)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/tle_preprocessing.py:246-254
Evidence:
               is_multi = len(reps) > 1
               reduced_cache[satno] = reps[0]
Issue:       "First cluster" is the lowest DBSCAN label (tle_clustering/clustering.py:139 sorts the labels). DBSCAN numbers clusters in scan order, so reps[0] belongs to the cluster holding the earliest input record, not the freshest or the post-manoeuvre one. The "rare" claim at line 9 is also doubtful. With raan_tolerance_deg 0.05 (spectre/config/constants.py:54), eps 1 and no propagation to a common epoch, a LEO object regressing about 5.0 deg/day covers 0.05 deg in about 14 min (hand check: ISS a=6778 km, i=51.6 deg gives -5.00 deg/day). So sets a few hours apart are mostly separate clusters or noise.
Impact:      The threat sweep cache (spectre/web/routes/threat.py:1177) can be overwritten with the oldest TLE in the 24 h fetch window, or with the pre-burn orbit of an object that has just manoeuvred.
Fix:         Choose the representative of the cluster with the latest member epoch, and surface multi_cluster per object. Compare RAAN after propagating to a common epoch, with wrap-around (out-of-slice fix in tle_clustering).
Gate:        An integration test with two genuine clusters (pre-burn older, post-burn newer) asserting the post-burn representative is written. Fix the vacuous test at tests/integration/test_tle_clustering_pipeline.py:251.
Verdict:     CONFIRMED
```

```
ID:          F-029   (origin F-S04-01)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:449-451
Evidence:
               t_span_s = horizon_hours * 3600.0 + epoch_offset_s
               if t_span_s <= 0:
               t_span_s = 60.0
Issue:       The burn-timing perturbation is applied to the end of the propagation span rather than to the burn instant: every sample still burns at t = 0 from the same pre-state, and each is then evaluated at a different final epoch, while the `pre_epoch` argument (monte_carlo.py:424, vulture 100% unused) that would anchor a timing shift is never read.
Impact:      The position cloud and altitude percentiles at the "horizon" mix states at different times; with the default 30 s sigma in LEO the along-track spread from evaluation-time scatter alone is about 7.6 km/s × 30 s ≈ 228 km per sigma, which dominates `position_3sigma_km` shown to the operator as a physical uncertainty (inference, from v·δt).
Fix:         Propagate the pre-state by `epoch_offset_s` (or back) before adding ΔV, then integrate to the fixed horizon `horizon_hours * 3600` measured from `pre_epoch`; delete the unused parameter only if timing is modelled elsewhere.
Gate:        Unit test: with zero ΔV dispersion and zero pointing error, a non-zero `epoch_1sigma_seconds` must give a position cloud far smaller than v·σ_t; vulture at 100% confidence in CI.
Verdict:     CONFIRMED
```

```
ID:          F-030   (origin F-S04-02)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:670-672
Evidence:
               delta_v_radial=0.0,
               delta_v_in_track=dv,     # Assume in-track by default
               delta_v_cross_track=0.0,
Issue:       Every hypothesis built from a detection puts the whole ΔV in-track, even when the archetype is `plane_change` (reachable via spectre/domain/pol_assessment.py:253) and the detection's own breakdown has already split the ΔV into along-track, radial and cross-track channels; the `tle_record` parameter (vulture 100% unused) is also ignored in favour of `manoeuvre.tle_before`.
Impact:      A detected 13 m/s plane change is simulated as a 13 m/s orbit raise: the panel shows an SMA spread and regime probabilities for a manoeuvre that did not happen and an inclination spread near zero, with nothing on the panel saying the direction was assumed.
Fix:         Take the RIC direction from `manoeuvre.breakdown.components` (along_track to I, radial to R, cross_track to C) when present; fall back to in-track only when no breakdown exists, and label the panel "direction assumed in-track". Remove or use `tle_record`.
Gate:        Unit test for `hypothesis_from_tle_record` (lines 654-667 currently uncovered per audit/tools-raw/pytest.txt:64) asserting a cross-track breakdown yields a cross-track hypothesis.
Verdict:     CONFIRMED
```

```
ID:          F-031   (origin F-S04-03)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/monte_carlo.py:446
Evidence:
               bc_m2_kg = max(5.0, 1.0 / (2.0 * max(abs(bstar_eff), 1e-8) * _R_E * 1e3 * 2.461e-5))
Issue:       The B* to ballistic-coefficient conversion multiplies by the Earth radius in metres (6.378e6) where the standard relation uses ρ0 = 0.15696615 kg/m²/ER, i.e. Cd·A/m = 12.741621·B* (Vallado, Fundamentals of Astrodynamics, SGP4 drag term); the code gives BC = 31.9 kg/m² for B* = 1e-4 against the standard 784.8 kg/m², so drag is about 24.6 times too strong (hand computed). The constant is unsourced and appears nowhere else in the repository.
Impact:      Below about 450 km the drag-induced SMA decay and along-track drift over 48 h are overstated by more than an order of magnitude, biasing the SMA percentiles low and contradicting the module claim that ΔV dispersion dominates force-model error.
Fix:         Use `bc_m2_kg = 1.0 / (12.741621 * abs(bstar_eff))` with the source cited; add a named constant.
Gate:        Unit test: an ISS-like B* (3e-4) must produce Cd·A/m between 0.002 and 0.01 m²/kg; a 48 h decay at 400 km must match an independent density times B estimate within 20%.
Verdict:     CONFIRMED
```

```
ID:          F-032   (origin F-S04-04)
Lens:        L11 numerical and scientific correctness (computed versus modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/dv_estimation.py:323-326; spectre/web/templates/partials/pol_manoeuvre_detail.html:282-283
Evidence:
               #: False when the robust statistics could not produce a usable floor and
               #: the absolute floor stood in. Nothing downstream should present an
               #: unmeasured floor as a measurement.
Issue:       floor_is_measured` is never read by the route or template, and the drill-down always says "Detection floor for this object ... measured from {{ noise_samples }} consecutive element set pairs" even when the 0.1 m/s absolute fallback stood in (fewer than 4 samples, or the implausible-ceiling path at :910-920).
Impact:      The operator is told a REJECT verdict rests on a floor measured from the object's own history when it rests on a fixed constant, which is exactly the misrepresentation the module's own docstring forbids.
Fix:         Pass `floor_is_measured` and `noise.method` into `_breakdown_view` and render "absolute floor (not measured)" when false; `noise_method` is already computed at spectre/web/routes/pol.py:475 but never rendered.
Gate:        Template test rendering the drill-down with `floor_is_measured=False` that asserts the word "measured" does not appear.
Verdict:     CONFIRMED
```

```
ID:          F-033   (origin F-S04-05)
Lens:        L11 numerical and scientific correctness (computed versus modelled)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:629-635; spectre/web/templates/partials/photometry_results.html:92
Evidence:
               # Confidence: composite based on p-value and sample sizes
               if sig99:
               confidence = 0.99
Issue:       The "confidence" shown to the operator as a percentage is 0.99, 0.95 or 1 − p, which is not a probability that a brightness change occurred, and sample sizes are not used despite the comment.
Impact:      A p of 0.3 is displayed as "Confidence: 70.0%" of a change, presenting a misread p-value with the authority of a calibrated probability on a panel used to corroborate manoeuvre detections.
Fix:         Remove the field or rename it and show the p-value and the sample sizes only; if a composite is wanted, define and calibrate it and label it heuristic in the template.
Gate:        Template test that the photometry panel contains no "Confidence" percentage derived from p; docstring and comment checked in review.
Verdict:     CONFIRMED
```

```
ID:          F-034   (origin F-S05-02)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:194-209, :234
Evidence:
               if adversary.action_type == ActionType.NO_ACTION:
               base_ca_km = 5000.0   # no approach threat
               elif adversary.action_type == ActionType.MANOEUVRE:
Issue:       Closest approach (200, 3,000, 5,000 or 10,000 km scaled by 1 + 5 x cost), time to closest approach (horizon x 0.4), custody and every normaliser (50,000 km, 0.1 km/s) are untraced constants, OutcomeMetrics carries no modelled flag, and the template prints them as physical quantities ("{{ "%.0f" | format(om.closest_approach_km) }}km ·" at decision_results.html:92) under a "Robust Recommendation" banner, with only a small footer reading "Phase 1 · deterministic analytic model".
Impact:      An operator reads "600km" and a custody tick as computed geometry when no orbit was propagated (the route never supplies red_tle, spectre/web/routes/decision.py:171), and acts on a recommendation that is a weighted lookup table.
Fix:         Add a `modelled: bool` and `basis: str` to OutcomeMetrics, label every CA and custody cell "modelled", replace the banner wording with "Heuristic ranking", and document each constant's origin or mark it uncalibrated.
Gate:        Template test asserting the "modelled" label renders whenever OutcomeMetrics.modelled is true.
Verdict:     CONFIRMED
```

```
ID:          F-035   (origin F-S05-03)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:186, :250
Evidence:
               custody_gap_hours = scenario.horizon_hours * adversary.confidence * (1.0 - friendly.reversibility)
               norm_custody  = 0.0 if custody_maintained else min(custody_gap_hours / scenario.horizon_hours, 1.0)
Issue:       The custody-loss penalty, the largest weight (0.35), is scaled by the friendly response's reversibility, so a NO_ACTION response with reversibility 1.0 loses custody at zero cost and becomes the minimax "robust" choice against an adversary manoeuvre.
Impact:      Hand evaluation of the fixture at tests/unit/test_decision.py:184-192 (default weights, 72 h): worst-case scores R1 manoeuvre 0.3253, R2 sensor retask 0.2673, R3 no action 0.2573, so minimax recommends doing nothing while the matrix shows custody lost; the test only asserts the result is a FriendlyResponse.
Fix:         Make custody loss a function of the adversary action and detection capability, not friendly reversibility; keep reversibility only in its own term.
Gate:        Test asserting that a custody-losing cell scores strictly worse than a custody-maintaining cell with otherwise equal inputs, and pinning the minimax pick for the fixture.
Verdict:     CONFIRMED
```

```
ID:          F-036   (origin F-S05-09)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/pol_assessment.py:110-123, :599-616
Evidence:
               _W_GEO = {"dv": 0.20, "lon": 0.30, "drift": 0.25, "regularity": 0.10, "budget": 0.15}
               _W_OTHER = {"dv": 0.30, "lon": 0.15, "drift": 0.10, "regularity": 0.20, "budget": 0.25}
Issue:       The anomaly score and its risk ladder (75/55/35/15) rest on uncited weights and normalisers (9 x ceiling at :599, 60 deg at :604, 1.5 deg/day at :610, CV / 2 at :616), contrary to the module claim at :11 that every threshold is cited; the result is shown as "/100 anomaly score" under a CRITICAL/HIGH risk banner (pol_results.html:31-39) with no modelled label, AnomalyAssessment.basis is never rendered, and the budget tooltip still says "Annual ΔV vs 200 m/s/yr reference ceiling" (pol_results.html:174), the exact defect the code comment at :620-621 says was removed.
Impact:      A tuned heuristic drives the headline risk word an operator briefs from, with the authority of the cited budgets beside it and a tooltip that misstates its denominator.
Fix:         Label the score "heuristic anomaly index (uncalibrated)", render anomaly.basis, correct the tooltip to the regime multiple, and either cite or mark each weight and normaliser as tuned.
Gate:        Template test asserting anomaly.basis renders; grep gate rejecting "200 m/s/yr" in templates.
Verdict:     CONFIRMED
```

```
ID:          F-037   (origin F-S06-02)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1285-1287
Evidence:
               if coast_s > 0:
               return coast_s / _SECONDS_PER_HOUR
               return 0.5
Issue:       The evasion solver's fuel budget in km/s is derived from the panel's coast time in hours, and the operator's `max_dv_m_s` never reaches EVASION (maneuver.py:1389-1397), the same class of defect the docstring at 1433-1438 says was fixed for MIN_TIME.
Impact:      The form default (coast 1.0 h, operator.html:467) gives a 1.0 km/s (1,000 m/s) evasion budget against a 500 m/s operator budget; 10 h gives 10 km/s. The evasion row presents a burn the operator excluded.
Fix:         Pass `fuel_budget_km_s=to_km_s(a.max_dv_m_s)` and keep coast as coast.
Gate:        Integration test in the style of test_all_intercepts_ranking.py:104 asserting the EVASION row changes with `max_dv_m_s` and not with `coast_hours`.
Verdict:     CONFIRMED
```

```
ID:          F-038   (origin F-S06-03)
Lens:        L3 security
Severity:    High
Confidence:  High
Epistemics:  fact (mechanism); inference (exploitability via UDL-sourced names)
Location:    spectre/web/templates/partials/threat_sweep.html:361
Evidence:
               onclick="event.stopPropagation(); loadInEngine('{{ assessment.red_name }}', '{{ child.entry.target.target_name }}', '{{ child.entry.burn_epoch.strftime('%Y-%m-%dT%H:%M') }}', '{{ child.entry.method }}')"
Issue:       Object names are interpolated into a JavaScript string inside an HTML event attribute; autoescape turns `'` into `&#39;`, which the browser decodes back to `'` before the handler is compiled, so a name containing `');…//` executes. Same sink at threat_sweep_row.html:54 and all_intercepts_result.html:136.
Impact:      Target names come from HRR objects (UDL notifications or HRR_List.json, TB3/TB5) and from the free-text `manual_name` (threat.py:240). CSP permits inline script (`"script-src 'self' 'unsafe-inline' 'unsafe-eval'; "`, app.py:272), so a crafted name runs in an authenticated operator's session and can read the CSRF token from the DOM and drive any route.
Fix:         Pass values through `data-*` attributes and read them in the handler, or emit `{{ value | tojson }}` (which escapes for JS) rather than quoting by hand.
Gate:        Template test rendering a target named `x');alert(1);//` and asserting no unescaped `'` reaches an `on*` attribute; a lint grep failing on `on[a-z]+="[^"]*'\{\{`.
Verdict:     CONFIRMED
```

```
ID:          F-039   (origin F-S06-04)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/threat_sweep.html:193-195
Evidence:
               <option value="">All</option>
               <option value="REAL">REAL</option>
               <option value="SIMULATED">SIMULATED</option>
Issue:       The bundled watchlist's element sets are tagged `"tleDataMode": "SYNTHETIC"` (spectre/data/hrr_default.json), but the sweep results carry provenance only in a hidden `data-dm` attribute (line 233), the filter offers no SYNTHETIC option, and neither the sweep nor the screen result shows any synthetic warning.
Impact:      On a fresh instance every sweep and screen verdict ("MOST DANGEROUS COURSE OF ACTION", warning time, delta-V) rests on generated orbits and is presented exactly as if tracked; threat.py:446-449 states this is the failure to avoid.
Fix:         Render a per-row provenance badge and a result-level banner when any target, actor or the asset is non-REAL; add SYNTHETIC to the filter.
Gate:        Template test rendering a group with `data_mode="SYNTHETIC"` and asserting visible text "SYNTHETIC" in threat_sweep.html and threat_screen.html.
Verdict:     CONFIRMED
```

```
ID:          F-040   (origin F-S06-06)
Lens:        L5 resource lifecycle and concurrency
Severity:    High
Confidence:  High
Epistemics:  fact (mechanism); inference (duration)
Location:    spectre/web/routes/maneuver.py:755-757
Evidence:
               tle = _find_tle(state, red_sat.strip())
               if tle:
               raw = find_orbital_events(tle, sc_start, sc_stop)
Issue:       find_orbital_events` runs on the event loop over the whole scenario window at 30 s steps with no early exit (spectre/astro/events.py: loop over `n_steps`, `_add_event` only skips appends), and the window is bounded only by `stop > start` (operator.py:303).
Impact:      One operator setting a ten-year scenario window and opening the events panel triggers about 10.5 million SGP4 steps twice on the single event loop, freezing every operator's session, health probes included, for minutes.
Fix:         Cap the window (the sweep already uses 24 h), stop scanning once every type reaches `max_per_type`, and run it in an executor.
Gate:        Validation test on /scenario/time rejecting windows beyond the cap; a test asserting `orbital_events` awaits an executor.
Verdict:     CONFIRMED
```

```
ID:          F-041   (origin F-S06-07)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  Medium
Epistemics:  inference (calibration status of the astro scores is TBC in the astro slice)
Location:    spectre/web/routes/maneuver.py:596-598
Evidence:
               InterceptMethod.INTENT_PREDICT:
               lambda result, dv, miss, tof_label, arrival: (
               f"Intent assessment indicates {int(miss)}% probability of intercept "
Issue:       Heuristic 0-100 scores are presented as probabilities and assessments ("Intercept Likelihood", "High confidence intercept intent" at 438-450; "high probability of SSN detection and attribution" at 227-228 from fixed delta-V thresholds), and the sweep labels any Lambert solution "Close-Proximity Operation" (threat.py:795); no template marks any of them as heuristic.
Impact:      An operator briefing "73 % probability of intercept intent" is quoting a tuned score as a calibrated probability.
Fix:         Label these as heuristic scores in the payload and template ("score, not a probability"), state their basis, and drop "probability" and "confidence" wording unless a calibration exists.
Gate:        Template test asserting the words "heuristic" or "score" accompany every assessment-method figure; a grep test forbidding "probability" in `_METHOD_SUMMARY_BUILDERS`.
Verdict:     CONFIRMED
```

```
ID:          F-042   (origin F-S06-08)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1258-1259
Evidence:
               @router.post("/sweep", response_model=None)
               async def threat_sweep(
Issue:       The sweep handler, refine, fetch-targets, add-manual-tle and red-orbit-info routes are never exercised by any test; threat.py coverage is 48 %.
Impact:      Every finding in this slice on the sweep path (F-S06-05, 09, 10, 11, 12, 13, 14, 25) sits on code no test has run, so regressions ship silently.
Fix:         Add integration tests through `client.post("/plan/threat/sweep")` with a seeded state, covering manual targets, truncation, regime skip and the UDL-connected path with a stubbed fetch.
Gate:        Per-file coverage floor for spectre/web/routes/threat.py in CI.
Verdict:     CONFIRMED
```

```
ID:          F-043   (origin F-S06-27)
Lens:        L1 correctness and edge cases
Severity:    High   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/templates/partials/sweep_target_config.html:106
Evidence:
               onclick="document.getElementById('ts-manual-name').value=''; document.getElementById('ts-manual-tle').value='';"
Issue:       The inline `onclick` that clears the name and TLE inputs is registered at parse time, before htmx's own click listener, so the fields are likely empty when htmx collects `hx-include` values.
Impact:      Every "Add TLE" may post an empty name and return "Target name is required.", making manual targets unusable. TBC with a browser test.
Fix:         Clear the fields in an `hx-on::after-request` handler.
Gate:        Browser test that adds a manual TLE and asserts it appears in the list.
Verdict:     CONFIRMED
```

```
ID:          F-044   (origin F-S07-01)
Lens:        L3 Security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/planning_state.py:55-57
Evidence:
               # UDL credentials — held in memory for this session only, never persisted.
               udl_username: str | None = None
               udl_password: str | None = None
Issue:       The UDL password is held in plaintext on a SessionState inside the process-global `_store` keyed by SPECTRE username (planning_state.py:113), so its real scope is the process and the user name, not the session: every concurrent browser session of that user drives UDL with it, and it outlives cookie expiry and server-side session revocation because the only clearing sites are SPECTRE logout (login.py:212) and UDL logout (udl.py:384-385).
Impact:      An operator who closes the browser without pressing logout leaves a live UDL credential in memory until the process restarts, and any later session for the same SPECTRE account (another terminal, a stolen cookie inside its 8-hour validity) gets UDL access without the UDL password.
Fix:         Key UDL credentials on the server-side session token, not the username, and clear them when that token expires or is revoked; better still, exchange the Basic credential once for a UDL token and hold only that, with an idle timeout.
Gate:        Integration test: log in twice as one user, connect UDL in session A, assert session B sees no UDL connection; expire A and assert the credential is gone.
Verdict:     CONFIRMED
```

```
ID:          F-045   (origin F-S07-02)
Lens:        L3 Security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:282-297
Evidence:
               udl_user: Annotated[str, Form()] = "",
               udl_pass: Annotated[str, Form()] = "",
               satno, udl_user.strip(), udl_pass.strip(), "REAL",
Issue:       POST /pol/analyse accepts UDL credentials directly in the form (request scope, not stored) and carries no rate-limit dependency, so it is an unthrottled UDL credential oracle that sidesteps the 5-per-minute `udl_auth_rate_limit` on /udl/login (rate_limit.py:120), and each call fires two UDL requests of up to 5,000 elsets with a 120 s timeout.
Impact:      Any logged-in SPECTRE account can brute-force or spray UDL passwords through SPECTRE's egress address, getting the UDL account (or SPECTRE's address) locked out, and can tie up the server with long UDL pulls.
Fix:         Add `Depends(udl_auth_rate_limit)` when `pol_source == "udl_direct"` and `Depends(udl_data_rate_limit)` otherwise, or remove the direct-credential path and require /udl/login.
Gate:        Route-inventory test asserting every handler that calls httpx against _UDL_BASE declares one of the udl_* rate-limit dependencies.
Verdict:     CONFIRMED
```

```
ID:          F-046   (origin F-S07-03)
Lens:        L4 Contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.py:121-123
Evidence:
               existing_ids: set[str] = {
               str(r.get("msgId") or r.get("messageId") or "")
               for r in self._data["records"]
Issue:       The cache reads `msgId`, top-level `satNo` (notso_cache.py:149) and `msgText` (pol.py:922), but the 500 real UDL TACREP_NOTSO records in the committed file carry `id`, `msgBody` and `msgBody.SatIds` and none of those three keys (counted: 0/0/0 of 500), so deduplication never fires, `get_for_satno` returns an empty list for every object, and the cache path of /pol/notso-correlate always answers "No NOTSOs in local cache".
Impact:      Correlation from the cache is dead code against live data, and every re-sync of an overlapping window appends duplicates, so counts and correlations are inflated. The unit tests stay green because their fixtures (test_notso_cache.py:54-55) use the invented shape.
Fix:         Key deduplication on `id`; index satellite numbers from `msgBody.SatIds`; build the parse text from `msgBody` fields; rebuild the test fixtures from a redacted real record.
Gate:        Contract test that loads one redacted real record shape and asserts `append` twice adds 1 and `get_for_satno(<SatIds[0]>)` returns it.
Verdict:     CONFIRMED
```

```
ID:          F-047   (origin F-S07-05)
Lens:        L10 Build, config and deploy
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.json:14-15
Evidence:
               "source": "JCO",
               "classificationMarking": "U//DS-JCO-NOTIF",
Issue:       The repository commits 500 REAL-mode JCO TACREP_NOTSO notifications pulled from UDL (metadata last_sync 2026-04-07, createdAt 2024-01-02 to 2025-11-13, origNetwork OPS1, every record marked U//DS-JCO-NOTIF and naming 92 commercial providers). The file ships in the image through `COPY spectre/ /app/spectre/` (Dockerfile:77; .dockerignore `data/` matches only the root). It is also served to every logged-in SPECTRE operator whether or not they hold a UDL account.
Impact:      Data carrying a UDL dissemination-control marking is redistributed through git history and every container image to people outside the UDL access decision. By contrast the operator's own HRR_List.json is deliberately ignored as "their operational product, not ours to commit" (test_hrr_bootstrap.py:122).
Fix:         Remove the file from the tree and history after a human ruling on the marking, ship an empty cache, and gitignore spectre/data/notso_cache.json.
Gate:        CI check that fails when any tracked JSON contains a `classificationMarking` key, or when notso_cache.json is tracked.
Verdict:     CONFIRMED
```

```
ID:          F-048   (origin F-S08-02)
Lens:        L3 security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/auth.py:59, spectre/web/auth.py:102, spectre/web/routes/admin.py:144
Evidence:
               return str(_serializer().dumps({"sub": username, "gen": int(generation)}))
               return generation < (user.session_generation or 0)
               new_user = User(username=username, hashed_password=hash_password(password), role=role)
Issue:       The token binds only the username and a generation counter, and a recreated account restarts at generation 0 (models.py:53-58), so any unexpired token from a deleted account with the same name authenticates as the new account.
Impact:      An admin deletes a compromised or departed "alice" and recreates "alice" (possibly as admin) within 8 hours; every captured token of the old account is accepted, with the new account's role.
Fix:         Put the immutable user id (or a per-account random nonce set at creation) in the payload and require it to match the loaded row; alternatively never reuse a generation by seeding new rows from a global monotonic value.
Gate:        Integration test: log in as X, admin deletes X and recreates X, replay the old cookie, assert 302 to /login.
Verdict:     CONFIRMED
```

```
ID:          F-049   (origin F-S09-01)
Lens:        L3 security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:378-504
Evidence:
               cr = result.scalar_one_or_none()
               if cr is None:
               return HTMLResponse('<p class="error-msg">Attempt record not found.</p>', status_code=404)
Issue:       training_scenario_submit never checks `cr.completed_at is None`, so the same result_id can be resubmitted indefinitely and each POST re-awards scenario_completed, challenge_passed and challenge_passed_first_try (first_try stays True) and increments scenarios_passed and challenges_passed.
Impact:      One passing attempt replayed about 16 times (500 points per replay) reaches Level 6 Instructor; training records used to judge operator competence are falsifiable by any logged-in user with a browser console or curl.
Fix:         Reject (409) when `cr.completed_at is not None`, inside the same transaction; better, update with `WHERE completed_at IS NULL` and check the row count so concurrent replays also fail.
Gate:        Integration test that submits the same result_id twice and asserts the second response is 409 and progress.total_points is unchanged.
Verdict:     CONFIRMED
```

```
ID:          F-050   (origin F-S09-05)
Lens:        L1 correctness and edge cases
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/templates/partials/training_scenario_active.html:65-189
Evidence:
               <form hx-post="/training/scenario/{{ scenario.id }}/reset"
               hx-target="#scenario-detail"
               hx-swap="innerHTML"
Issue:       The Reset form (opened at :171) is nested inside the submit form (opened at :65); the HTML parser ignores a nested `<form>` start tag and its `</form>` at :180 closes the outer form, so the Reset button becomes a submit button of the scoring form.
Impact:      An operator who clicks "Reset" ("cancelled with no side effects") instead posts to /submit and has the attempt scored, earning or losing a first-try record they never chose; the reset route itself is unreachable from the UI.
Fix:         Move the Reset form outside the submit form, or make Reset a `type="button"` with `hx-post`, `hx-vals` carrying result_id and no enclosing form.
Gate:        Extend tests/unit/test_template_markup_is_well_formed.py to fail on a `<form` opened while another `<form` is open; add a browser or html5lib parse test of this partial asserting two separate form elements.
Verdict:     CONFIRMED
```

```
ID:          F-051   (origin F-S09-06)
Lens:        L4 contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:230-242
Evidence:
               state = get_session_state(username)
               for obj in scenario.objects:
               if obj.side == "blue":
Issue:       Starting any scenario appends synthetic BLUE-xx and RED-xx objects to the operator's live operational SessionState, with no training marker on BlueAsset or RedTrack (domain/models.py:24-26) and nothing removes them on /training/leave, while training.html:42-43, tutorials.yaml:17, training/__init__.py:7 and training/models.py:7 all state the opposite.
Impact:      After "Return to Operations" the operational Blue and Red lists, intercept engine and threat sweep include fictitious satellites indistinguishable from real ones; the Console tab also frames the full operational console (training.html:290) with live UDL access under a banner that says no operational systems are affected.
Fix:         Give training its own SessionState keyed by `f"training:{username}"` and point the embedded console at it, or tag injected objects and purge them in training_leave; correct the four docstrings and the banner.
Gate:        Integration test: start a scenario, POST /training/leave, GET / and assert no scenario object name appears in the blue or red list; extend TestDataIsolation to scan spectre/web/routes/training.py imports.
Verdict:     CONFIRMED
```

```
ID:          F-052   (origin F-S09-07)
Lens:        L4 contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/training/config/scenarios.yaml:821-823
Evidence:
               scoring:
               passing_score: 300
               optimal_score: 460
Issue:       planner_05_leo_phasing_campaign objectives total 15+60+80+55+50 = 260 points (:803-819) against a passing score of 300, so it cannot be passed honestly; optimal_score also exceeds the achievable maximum in five scenarios (analyst_gauntlet 500 vs 350, operator_timed_full_cycle 600 vs 500, planner_04 360 vs 260, planner_05 460 vs 260, planner_challenge_theatre_defence 650 vs 550).
Impact:      A Level 4 scenario is a guaranteed fail; in the other four the debrief's "Excellent performance" band (training_debrief.html:106, 95% of optimal) is unreachable, so the feedback mis-grades perfect work.
Fix:         Set planner_05 passing_score at or below 260 and every optimal_score to the objective sum, or add the missing objectives.
Gate:        Unit test over load_scenarios(): passing_score <= sum(objective points) == optimal_score for every scenario.
Verdict:     CONFIRMED
```

```
ID:          F-053   (origin F-S09-08)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/training/config/scenarios.yaml:36-76
Evidence:
               Read the RAAN field — for a GEO satellite this equals the sub-satellite longitude in degrees East.
               answer: "45.0"
               tolerance: 0.5
Issue:       RAAN is an inertial angle; sub-satellite longitude for a near-circular, near-equatorial orbit is Ω + ω + M − GMST, which for BLUE-01 (Ω 45°, ω 90°, M 0°, epoch 25166.0 = 2025-06-15 00:00 UTC, GMST 263.53° by the IAU 1982 expression in Vallado, Fundamentals of Astrodynamics, eq. 3-45) is 231.5°E (128.5°W), not 45°E; the same scenario also calls a north-south burn a longitude-keeping manoeuvre (:37), when north-south control holds inclination.
Impact:      The first scored Cadet exercise trains operators that RAAN is longitude and scores the wrong answer as correct, a misconception that transfers directly into misreading real GEO element sets.
Fix:         Change the objective to read RAAN as RAAN, or compute longitude in the Assets panel and ask for that; rewrite the briefing as east-west station-keeping.
Gate:        Content test that, for every objective whose description mentions longitude, recomputes longitude from the scenario TLE with SGP4 and GMST and compares to the answer within the tolerance.
Verdict:     CONFIRMED
```

```
ID:          F-054   (origin F-S09-11)
Lens:        L11 numerical and scientific correctness
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    tle_clustering/parser.py:80-82; spectre/config/constants.py:52-57
Evidence:
               inclination_deg = math.degrees(sat.inclo)
               raan_deg = math.degrees(sat.nodeo)
               eccentricity = sat.ecco
Issue:       Elements are compared at each TLE's own epoch with no propagation to a common epoch, while the fetch window is 24 h (constants.py:57); J2 nodal regression for an ISS-like orbit (n 15.5 rev/day, i 51.6°, a ≈ 6778 km) is dΩ/dt = −1.5 n J2 (Re/p)² cos i ≈ −4.98°/day, so 0.05° of RAAN corresponds to about 14 minutes of epoch separation.
Impact:      For LEO, any two provider TLEs more than about 15 minutes apart in epoch are never neighbours, so the "dozens of TLEs per day" the README describes cluster into many groups or all-noise, and the sweep raises false elevated-uncertainty warnings; the README rationale at :411 is only valid for same-pass fits.
Fix:         Propagate every TLE with SGP4 to a common reference epoch (for example the latest epoch in the group) and extract osculating or re-fitted mean elements there before clustering, or add an epoch-aware RAAN correction using the secular J2 rate.
Gate:        Unit test with two ISS TLEs six hours apart from the same orbit (generated by propagating one set) asserting a single cluster.
Verdict:     CONFIRMED
```

```
ID:          F-055   (origin F-S10-03)
Lens:        L11 numerical and scientific correctness (frame claim)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    README.md:466-467
Evidence:
               All times are UTC. Distances in km, speeds in km/s, angles in degrees.
               Coordinate frame: ICRF/J2000.
Issue:       The README declares ICRF/J2000 as the coordinate frame, but SGP4 states are documented as TEME (spectre/astro/propagator.py:33-34) and no TEME-to-J2000/GCRF conversion exists anywhere in spectre/; the code's own audit note (docs/ORBITAL-CALCULATION-AUDIT.md "Frames are conflated") says the difference is tens of kilometres at GEO; the same README line says speeds are km/s while `InterceptResult` and `BurnResult` carry m/s (spectre/domain/models.py:326, 347).
Impact:      Any position exported or compared against an external J2000/GCRF ephemeris (for example a UDL state vector) is wrong by tens of kilometres at GEO while the documentation tells the operator it is J2000.
Fix:         State "TEME (SGP4 native); not converted to J2000/GCRF" in README.md and every template that shows positions, and correct the units line to m/s for delta-V; or implement the TEME-to-GCRF rotation and test it against Vallado's published TEME/GCRF example.
Gate:        A docs test that fails on "J2000" or "ICRF" in README.md while grep for a TEME-to-GCRF transform in spectre/astro returns nothing.
Verdict:     CONFIRMED
```

```
ID:          F-056   (origin F-S10-04)
Lens:        L3 security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    README.md:44-46
Evidence:
               $env:SECRET_KEY      = "change-me-to-a-long-random-string"
               $env:SPECTRE_ADMIN_USER = "admin"
               $env:SPECTRE_ADMIN_PASS = "change-me"
Issue:       The quick-start (and the Docker quick-start at README.md:74-76) tells operators to set a published 34-character signing key that the fail-closed guard accepts, because `_PLACEHOLDER_SECRETS` (spectre/config/settings.py:40-46) lists "change-me-to-a-random-string" but not this README variant, and the length floor is 16 (settings.py:49).
Impact:      A copy-pasted deployment boots green with a signing key printed in the public README, so anyone can forge `itsdangerous` session and CSRF tokens and log in as `admin`.
Fix:         Replace both README values with the generation command already in .env.example:10, and add the README literal to `_PLACEHOLDER_SECRETS` (or reject any key containing "change-me").
Gate:        Unit test in tests/unit/test_config_settings.py parametrised over every SECRET_KEY literal found in README.md and .env.example, asserting each is refused.
Verdict:     CONFIRMED
```

```
ID:          F-057   (origin F-S10-05)
Lens:        L8 clarity and comments (security policy claims)
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    docs/SECURITY.md:109
Evidence:
               - **Pinned Actions.** All third-party GitHub Actions are pinned by full commit SHA, not by mutable tag.
Issue:       docs/SECURITY.md is a generic policy template asserting controls the repository does not have: SHA-pinned Actions (CI pins tags, ci.yml:23, 24, 57, 181), an SBOM in the release pipeline (line 90; none in CI), CodeQL (line 143; none), release signing (line 120; none), `hypothesis` property tests (line 94; no test imports it), `mypy --strict` and container scanning in CI as described, a `main` branch (line 101; the repo uses `master`), a CONTRIBUTING.md (line 219; absent), "does not expose network services by default" (line 205; it is a web server on 0.0.0.0:8080), and a placeholder contact (line 36).
Impact:      An assessor or customer relying on the referenced UK NCSC/SSCoP alignment is given false assurance on supply-chain and build-integrity controls.
Fix:         Rewrite docs/SECURITY.md to state only controls that exist, each with the file and line that implements it, and list the absent ones as open items with owners.
Gate:        A docs test that, for each control row, requires a cited path that exists (for example the CI step name), failing on claims with no implementing artefact.
Verdict:     CONFIRMED
```

## Medium

```
ID:          F-058   (origin F-S00-02)
Lens:        L2 Error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:681-682
Evidence:
               except Exception as exc:  # noqa: BLE001
               notes.setdefault(name, _refusal_reason(exc))
Issue:       The July 2026 fix that records why each sweep method failed has no regression gate: replacing line 682 with `pass` leaves the full suite green.
Impact:      The silent-drop defect the July audit found can return unnoticed, biasing the sweep against the fastest, most-refused approaches.
Fix:         Add a unit test that drives `_sweep_all_methods` with a solver that raises and asserts the refusal reason appears in `refusals` and then in the rendered `method_refusals`.
Gate:        That test; and enable ruff BLE001 (F-S00-13) so a new bare broad handler needs a justified, live suppression.
Verdict:     CONFIRMED
```

```
ID:          F-059   (origin F-S00-03)
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/login.py:171
Evidence:
               secure=get_settings().session_cookie_secure,  # HTTPS only unless explicitly opted out
Issue:       The Secure cookie flag is correct but ungated at the call site: tests pin only the resolver default, and the integration suite runs with the opt-out, so no test ever sees a real Set-Cookie header carrying Secure.
Impact:      A regression to `secure=False` (the defect the July audit found) would ship with the suite green; the session cookie would then travel over plain HTTP.
Fix:         Add a test that sets SPECTRE_COOKIE_SECURE unset for one client and asserts `secure` in the Set-Cookie header of POST /login.
Gate:        That test.
Verdict:     CONFIRMED
```

```
ID:          F-060   (origin F-S00-04)
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/csrf.py:24
Evidence:
               _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
Issue:       Nothing pins CSRF protection on DELETE: adding "DELETE" to the safe-method set leaves all 242 CSRF, auth and integration tests green, yet three state-changing routes use DELETE.
Impact:      A regression would expose `DELETE /admin/users/{user_id}`, `/assets/blue/{name}` and `/assets/red/{name}` to cross-site request forgery with no test failing.
Fix:         Add an integration test that issues each DELETE route without a CSRF token and asserts 403.
Gate:        That test.
Verdict:     CONFIRMED
```

```
ID:          F-061   (origin F-S00-05)
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/auth.py:195
Evidence:
               if user is None or _session_revoked(user, generation):
Issue:       The claim at auth.py:192-194 that a revoked session reads as anonymous on `GET /` is untested: removing the revocation check from `optional_login` leaves the suite green.
Impact:      A regression would greet a signed-out operator by name, and render the console, on the public root page from a captured cookie.
Fix:         Add a test that logs in, logs out, replays the old cookie on GET / and asserts the login page is served.
Gate:        That test.
Verdict:     CONFIRMED
```

```
ID:          F-062   (origin F-S00-06)
Lens:        L10 Build, config and deploy
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.py:47
Evidence:
               _CACHE_PATH = Path(__file__).parent / "notso_cache.json"
Issue:       The NOTSO cache is written inside the installed package (`/app/spectre/data/` in the image), not the validated data directory, so it bypasses SPECTRE_DATA_DIR and STORAGE_MOUNT_PATH.
Impact:      Every NOTSO sync is lost on restart or redeploy, and on a read-only root filesystem the sync fails outright; the committed file (F-S07-05) is what operators see after every restart.
Fix:         Resolve the path from `get_settings().data_dir`, seeding from the bundled file on first run if that is wanted at all.
Gate:        A unit test asserting `get_notso_cache()._path` lies under the configured data directory.
Verdict:     CONFIRMED
```

```
ID:          F-063   (origin F-S00-08)
Lens:        L10 Build, config and deploy
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    requirements.txt:1370
Evidence:
               tomli==2.5.0 \
Issue:       The two hash-locked files pin different tomli versions (requirements-dev.txt:1025 pins 2.4.1), so they cannot be installed together.
Impact:      No reproducible single environment exists for a developer or CI to run runtime and tooling together; the obvious fix for F-S00-01 fails until this is resolved.
Fix:         Compile requirements-dev.txt with `-c requirements.txt` (constraint) so shared pins agree.
Gate:        A CI step `uv pip install --dry-run --require-hashes -r requirements.txt -r requirements-dev.txt`.
Verdict:     CONFIRMED
```

```
ID:          F-064   (origin F-S00-09)
Lens:        L8 Clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    README.md:49-72
Evidence:
               spectre-serve
               -p 8000:8000 \
Issue:       The README quick start runs a console script that no install creates and maps port 8000, while the app listens on 8080 (settings.py:36, Dockerfile:185); it also states Python 3.14 as the minimum (README.md:28) against 3.12 everywhere else.
Impact:      A deployer following the README gets "command not found" or a container that answers nothing on the mapped port.
Fix:         Replace with `python -m spectre.web._entrypoint`, map `-p 8080:8080`, state Python 3.12.
Gate:        A docs test that greps README for `spectre-serve` and `8000:` and fails.
Verdict:     CONFIRMED
```

```
ID:          F-065   (origin F-S00-12)
Lens:        L7 Design and structure
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    pyproject.toml:84
Evidence:
               select = ["E", "F", "I", "UP", "B", "SIM"]
Issue:       52 `noqa` suppressions name rules the project does not select (15 BLE001, 22 S603, 7 PLR0913/PLR0917, 4 PLC0415 and others), so they suppress nothing, and broad `except Exception` handlers are checked by no CI lint.
Impact:      The suppressions read as reviewed exceptions while 32 further broad handlers in product code go unflagged (house rule set, TOOLS.md 1c); silent-failure defects like P3 have no static gate.
Fix:         Add "BLE" (and RUF100 to catch dead directives) to the CI ruff selection.
Gate:        CI ruff with BLE and RUF100 selected.
Verdict:     CONFIRMED
```

```
ID:          F-066   (origin F-S00-14)
Lens:        L1 Correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_hrr_preload.py:79-82
Evidence:
               def test_non_dict_entries_are_discarded(self, hrr_dir: Path) -> None:
               app_module._load_hrr_from_disk()  # must not raise
Issue:       Seven tests assert only that no exception was raised, and 26 assert only `isinstance` or `is not None`; this one is named for discarding entries and checks nothing about what was kept.
Impact:      These tests pass whatever the code computes; the trivial selector tests are why the mislabelled Maximin selector (F-S05-01) survived.
Fix:         Assert the resulting state (here: the default HRR store is unchanged or empty); replace type-only assertions with value assertions.
Gate:        A meta-test (AST) failing on any test function with no assertion, mirroring the audit script.
Verdict:     CONFIRMED
```

```
ID:          F-067   (origin F-S01-11)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:625-632
Evidence:
               # Single burn at optimal location, in the normal direction
               h = np.cross(sv_red.r, sv_red.v)
Issue:       The burn is placed at t_departure (:630, :632), not at the node or apoapsis that plane_change reports as optimal. A normal impulse at an arbitrary argument of latitude changes RAAN as well as inclination. The direction is always +h regardless of the sign of the inclination change. plane_change is also given the current radius, while its docstring expects the SMA when ecc > 0.
Impact:      The burn epoch and direction in the plan do not produce the stated plane change.
Fix:         Find the next node crossing (events.find_orbital_events) or apoapsis, burn there, and sign the normal component by the sign of Δi at that node.
Gate:        Test asserting the burn epoch coincides with a node crossing.
Verdict:     CONFIRMED
```

```
ID:          F-068   (origin F-S01-13)
Lens:        L8 clarity and comments
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/lambert.py:53
Evidence:
               """Solve Lambert's problem using Izzo's algorithm.
Issue:       The public function's docstring still credits Izzo, which the module docstring at :11 explicitly retracts. The implementation is Curtis Algorithm 5.2 solved by bisection.
Impact:      Readers of help(solve_lambert) or generated API docs are told the solver is robust and multi-revolution capable, which is the false claim the module docstring says it removed.
Fix:         Replace the line with "Solve the single-revolution Lambert problem (Curtis Algorithm 5.2, bisection on F(z))".
Gate:        A docstring test or grep rule forbidding `Izzo` outside the history paragraph.
Verdict:     CONFIRMED
```

```
ID:          F-069   (origin F-S01-19)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/events.py:60-63
Evidence:
               try:
               orbit = TLEOrbit(tle)
               except (ValueError, Exception):
Issue:       find_orbital_events has cognitive complexity 30 against a cap of 15 (audit/tools-raw/cogcx_run.txt:7). It also swallows every exception, including programming errors, and returns [], which callers cannot tell apart from "no events".
Impact:      A broken TLE parser or a regression reads as an empty event list.
Fix:         Catch ValueError only. Split the detection into _apsis_crossing and _node_crossing helpers.
Gate:        Cognitive-complexity CI gate (scripts/cognitive_complexity.py --max 15); ruff BLE001.
Verdict:     CONFIRMED
```

```
ID:          F-070   (origin F-S01-21)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_astro.py:42-46
Evidence:
               assert 2.3 < result.delta_v_1 < 2.6
               assert 1.3 < result.delta_v_2 < 1.6
               assert 3.7 < result.total_delta_v < 4.1
Issue:       Tests pin only Lambert to an independent reference. Hohmann uses bands of about 6 per cent. Bi-elliptic (:55-66) asserts only > 0. SGP4 propagation (:111-119) checks only an altitude band. Events check only a type count. lambert_intercept and hohmann_intercept (:194-233) assert shape only. test_coplanar_short_arc (:72-88) is a 15 per cent shape check of the kind tests/unit/test_lambert_validation.py:5-10 condemns. The "independent" reference propagator (test_lambert_validation.py:39-53) imports the solver's own Stumpff functions.
Impact:      A sign or units regression in Hohmann, bi-elliptic, SGP4 frame handling or event timing passes CI.
Fix:         Pin Hohmann to Vallado Example 6-1 (191.344 km to 35,781.349 km; ΔV 3.935224 km/s, TOF 5.256713 h) at 1e-5. Pin bi-elliptic to Vallado Example 6-2 (3.904057 km/s). Pin SGP4 to the Vallado 2006 SGP4-VER case 00005 at t = 0 (TEME r = 7022.465, −1400.083, 0.040 km) at 1 m. Inline Stumpff series in the reference propagator.
Gate:        These tests.
Verdict:     CONFIRMED
```

```
ID:          F-071   (origin F-S02-05)
Lens:        L11 numerical and scientific correctness
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1560-1563
Evidence:
               # x(t) = (4-3cos(nt))*dx0 + sin(nt)*dvx0/n + 2*(1-cos(nt))*dvy0/n
               # Maximum occurs at specific nt values; estimate from initial conditions
               A_x = math.sqrt(dx0**2 + (dvx0 / n)**2) if n > 0 else abs(dx0)
Issue:       From the quoted solution the oscillating amplitude is sqrt((3x0 + 2ẏ0/n)² + (ẋ0/n)²) about an offset 4x0 + 2ẏ0/n; the code ignores ẏ0 and the factor 3. By hand x0 = 0, ẏ0 = v gives a true maximum radial excursion of 4v/n; the code returns 0.
Impact:      radial_amplitude_km (documented as "max radial oscillation") and the notes string understate radial excursion for any state with along-track velocity.
Fix:         Compute offset and amplitude from the closed form and report max |x|.
Gate:        Test against max |x| sampled from `_cw_propagate` over one period, rel 1e-6.
Verdict:     CONFIRMED
```

```
ID:          F-072   (origin F-S02-12)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:940; spectre/web/routes/maneuver.py:1485-1486
Evidence:
               miss_distance_km=result.confidence * 100.0,  # encode confidence as "miss" for display
               intercept_range_km=sol.miss_distance_km,
               notes=f"Computed via spectre.astro {sol.method} solver",
Issue:       Seven slice outputs (confidence, observability, likelihood, stability, fingerprint confidence, risk score, feasible count) travel to the web layer in a field typed and named as a distance in km, and every result is stamped "Computed via ... solver"; the physics-versus-heuristic distinction made in tactical.py does not survive the boundary.
Impact:      Any consumer that sorts, plots or thresholds intercept_range_km as a range mixes scores with kilometres.
Fix:         Add typed `score` and `score_kind` fields to InterceptSolution and InterceptResult and a `provenance` of "physics" or "heuristic".
Gate:        Type check that miss_distance_km is only written by physics methods.
Verdict:     CONFIRMED
```

```
ID:          F-073   (origin F-S02-14)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/tactical.py:830
Evidence:
               dv_raan = 2.0 * v1 * math.sin(math.radians(raan_residual) / 2.0) if raan_residual > 0.01 else 0.0
Issue:       The angle between two planes differing only in RAAN is θ with cos θ = cos²i + sin²i·cos ΔΩ (spherical trigonometry, Vallado chapter 6 RAAN-change algorithm, TBC exact algorithm number), roughly sin i·ΔΩ for small ΔΩ; the code uses ΔΩ directly, overstating cost by 1/sin i (1.28x at 51.6 degrees, unbounded towards equatorial).
Impact:      estimated_delta_v overstated for RAAN manoeuvres, badly so for low inclination.
Fix:         Compute θ from the formula above and cost 2v·sin(θ/2).
Gate:        Unit test at i = 51.6 degrees, ΔΩ = 1 degree against the closed form, rel 1e-6.
Verdict:     CONFIRMED
```

```
ID:          F-074   (origin F-S02-16)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:347-357
Evidence:
               v_node = math.sqrt(mu / r)
               a = r if ecc == 0.0 else r  # r is SMA when ecc > 0
               if dv_apogee <= dv_node:
Issue:       For ecc > 0, `r` is the semi-major axis, so v_node is the circular speed at a, not the speed at the node or at periapsis as the comment claims; the conditional expression is a no-op; for a circular orbit the tie resolves to "apogee", a point that does not exist, and the apogee option is only valid if apogee lies on the line of nodes, which is never checked.
Impact:      Wrong node ΔV for eccentric orbits and a misleading optimal_location.
Fix:         Take argument of perigee and true anomaly at the nodes, compute speed there by vis-viva, and report "node" for circular orbits.
Gate:        Unit test on an eccentric orbit against Curtis eq. 6.20 at the actual node radius.
Verdict:     CONFIRMED
```

```
ID:          F-075   (origin F-S02-17)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:381-385
Evidence:
               The plane change is split across both burns using the cosine rule,
               which is more efficient than performing them separately.
               Strategy: perform all inclination change at the slower burn point
Issue:       The docstring says the change is split across both burns, then says it is all done at one burn, and the code (401-409) does the latter; the optimal split (Vallado, combined plane change, small fraction at the first burn) is not implemented.
Impact:      Readers trust an optimality the code does not deliver; ΔV slightly above optimum.
Fix:         Correct the docstring or implement the optimal split by one-dimensional minimisation.
Gate:        Unit test that the split result is no more than the all-at-apogee result.
Verdict:     CONFIRMED
```

```
ID:          F-076   (origin F-S02-19)
Lens:        L7 design and structure
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1194-1216
Evidence:
               _dv_combined = desired_miss_km / total_eff * len(weights)
               ("prograde" if dv_prograde >= 0 else "retrograde",
Issue:       The combined-burn value is computed and discarded, so the docstring claim "Evaluates combined multi-axis burns" is false; dv_prograde is built from an abs() coefficient (1176) and is never negative, so "retrograde" is unreachable; radial and normal strategies have identical cost by construction.
Impact:      Operators are told evasion considers combined and retrograde burns; it does not.
Fix:         Remove the dead block and branch, or implement a combined allocation.
Gate:        Ruff F841-style check on underscore-prefixed assigned values; unit test that a retrograde strategy can be produced.
Verdict:     CONFIRMED
```

```
ID:          F-077   (origin F-S02-20)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:2161-2165
Evidence:
               if time_per_hop_s is None:
               time_per_hop_s = T_orbit / 2.0
               # Single normal burn per hop exploiting SHM quarter-period reach: Δv_n = n·d
Issue:       z(t) = (ż0/n) sin(nt) reaches d at T/4 and returns to 0 at T/2, so with the default T/2 cadence each hop ends where it started, and out-of-plane offsets do not accumulate as total_advance_km = n_hops·d claims; holding d also needs a stop burn not costed.
Impact:      H-bar hop sequences report an advance and arrival time that the dynamics do not produce.
Fix:         Model each hop as burn, T/4 coast and stop, cost 2n·d per hop for a sustained offset or document a single oscillation.
Gate:        Test flying the hop through `_cw_propagate` and asserting z at time_per_hop_s equals hop_distance_km.
Verdict:     CONFIRMED
```

```
ID:          F-078   (origin F-S02-23)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1793-1800
Evidence:
               elif best.strategy == "radial":
               # Radial burn causes oscillating displacement
               formation_displacement = best.delta_v / n  # max radial excursion
Issue:       A radial impulse also drives along-track excursion up to 4Δv/n at half a period, so the slot displacement is understated by up to 4x; the r_threat argument is never read.
Impact:      maintains_formation can read True when the asset leaves its slot.
Fix:         Use the maximum CW displacement norm over one period; remove or use r_threat.
Gate:        Test against max range from `_cw_propagate`.
Verdict:     CONFIRMED
```

```
ID:          F-079   (origin F-S02-25)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1135, 791, 1617, 1839, 1293
Evidence:
               def optimal_evasion(
Issue:       Five functions exceed cognitive complexity 15 (audit/tools-raw/cogcx_run.txt: optimal_evasion 51, classify_manoeuvre 31, fingerprint_manoeuvre 31, orbital_terrain 26, assess_intercept_intent 22).
Impact:      Branch-heavy heuristics where F-S02-10, F-S02-13 and F-S02-19 already hide.
Fix:         Move thresholds and weights into named, sourced tables and evaluate them in data-driven loops.
Gate:        Cognitive-complexity check at 15 in CI.
Verdict:     CONFIRMED
```

```
ID:          F-080   (origin F-S02-26)
Lens:        L11 numerical and scientific correctness (tests)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_tactical.py:402, 463, 611-612
Evidence:
               assert cheapest_long <= cheapest_short or True  # noqa: SIM222
               assert r.feasible_count >= 0  # envelope may still reject fast transfers
               if slow.is_feasible and fast.is_feasible:
Issue:       Two assertions are tautologies and the min-time monotonicity test is conditional, so none of them can fail; the last would also pass on F-S02-01 because both budgets collapse to the same 1% TOF.
Impact:      Evasion, envelope and min-time behaviour is unguarded while appearing tested.
Fix:         Replace with reference values (Lambert minimum TOF, envelope count) and unconditional asserts.
Gate:        Ruff PT and SIM rules without noqa; reject `or True` in review.
Verdict:     CONFIRMED
```

```
ID:          F-081   (origin F-S02-27)
Lens:        L11 numerical and scientific correctness (tests)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_tactical.py:122-128
Evidence:
               """Combined with zero along-track should match pure radial."""
               assert abs(combined.delta_v_radial - pure.delta_v_radial) < 0.01
Issue:       Worked by hand at r = 6,878 km, t = 1,800 s: the pure radial burn is +6.06 m/s and the combined Δvx with zero along-track target is -2.21 m/s (with Δvy +2.68 m/s); the 10 m/s tolerance exceeds both values, so the test passes on opposite signs and the premise is false (pure radial leaves y = -15.4 km).
Impact:      cw_combined is unverified despite a passing test.
Fix:         Assert x(t) and y(t) from `_cw_propagate` of the returned burn equal the targets, abs 1e-9 km.
Gate:        Property test across random t for both solvers.
Verdict:     CONFIRMED
```

```
ID:          F-082   (origin F-S02-28)
Lens:        L11 numerical and scientific correctness (tests)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_tactical.py:81-110, 208-232, 379-408, 481-502, 592-612
Evidence:
               assert result.total_delta_v > 0
               assert abs(r.along_track_drift_km_per_orbit) > 1.0
Issue:       Pinned to an independent reference: phasing, NMC, GEO drift, graveyard, J2 (test_tactical_validation.py) and `_cw_propagate` (test_cw_geometry.py:156-201). Only exercised for sign or shape: CW radial, along-track and combined, plane change, combined plane change, j2_drift_plan, collision_avoidance, optimal_evasion, relative_motion_stability (the magnitude-only check at line 497 misses the sign error in F-S02-03), min_time, formation, and the rotating-frame velocity in `_initial_hill_state` (test_cw_geometry.py:321-326); vbar and hbar hops have no test.
Impact:      Every defect in F-S02-01, -03, -05, -13, -15, -16 and -20 passes the current suite.
Fix:         Add closed-form or fly-the-answer tests per solver, as test_tactical_validation.py does.
Gate:        Coverage-of-reference checklist per public solver in tactical.py.
Verdict:     CONFIRMED
```

```
ID:          F-083   (origin F-S03-03)
Lens:        L2 error handling and failure modes
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:729-731
Evidence:
               providers, and a malformed pair must drop out rather than stop the parse.
               """
               rec = _satrec_to_record(f"{l1}\n{l2}")
Issue:       The docstring says a malformed pair drops out, but there is no try. _parse_tle_epoch raises ValueError at line 331 (`yy = int(epoch_str[:2])`) on a corrupt epoch field, and line 365 divides by a zero mean motion. Either error propagates out of parse_tle_history.
Impact:      One bad element set in a UDL history, admitted by _tle_line_pairs because it only checks the "1 "/"2 " prefix and the line 1 length, ends the whole parse. The route returns "Analysis error" (spectre/web/routes/pol.py:359-361) instead of a history short one set.
Fix:         Wrap _satrec_to_record in _record_from_pair, catching ValueError and ZeroDivisionError. Count the drops on the result and show the count, as rejected_below_floor is shown.
Gate:        A unit test that puts one corrupt-epoch pair among two good ones and asserts two records come back plus a dropped count of 1.
Verdict:     CONFIRMED
```

```
ID:          F-084   (origin F-S03-04)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:86-89
Evidence:
               # the estimator stopped degrading with the gap; detections beyond
               # ``_LONG_GAP_WARN_DAYS`` are kept but flagged as possibly several burns.
               _LONG_GAP_WARN_DAYS = 10.0  # days
Issue:       The constant is never read, so no detection from a 10 to 30 day gap is flagged as possibly several burns.
Impact:      Several burns inside one long gap are shown as one manoeuvre with HIGH confidence and enter the cumulative ΔV and interval statistics. The operator sees only the raw gap figure (spectre/web/templates/partials/pol_results.html:702).
Fix:         Add a breakdown warning, or a Manoeuvre flag rendered in the table, when gap_days > _LONG_GAP_WARN_DAYS. Cap confidence at MODERATE for such pairs if that is the intent.
Gate:        A unit test that asserts the flag is present on a 15-day-gap detection; a vulture or ruff unused-constant check in CI.
Verdict:     CONFIRMED
```

```
ID:          F-085   (origin F-S03-05)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact (mechanism); inference (frequency)
Location:    spectre/astro/tle_filter.py:120-125
Evidence:
               gap = tle.epoch - clusters[-1].tles[-1].epoch
               if gap >= min_spacing:
               clusters.append(TLECluster(tles=[tle]))
Issue:       Clusters chain off the last member, not the first, so a run of element sets each under 15 min apart grows into one unbounded cluster. A single representative is then chosen from what can span a burn. This is the same chaining defect that spectre/astro/pattern_of_life.py:505-514 records fixing in the merge.
Impact:      During a dense tracking campaign around a burn, the pre-burn and post-burn sets collapse into one representative, which can hide the manoeuvre the module docstring (spectre/astro/tle_filter.py:13-14) says it protects. Only clusters of 10 or more raise a flag.
Fix:         Bound each cluster by its span from the anchor (first member), not by the gap to the last member.
Gate:        A unit test with 12 sets 10 min apart and a semi-major axis step at set 6, asserting that more than one representative survives.
Verdict:     CONFIRMED
```

```
ID:          F-086   (origin F-S03-07)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:390-392
Evidence:
               dv = _extract_delta_v(
               fields.get("PREDICTED DV") or fields.get("DELTA-V") or text
               )
Issue:       A dedicated field's value has its key already stripped by partition (line 327), so "PREDICTED DV: 1.5 m/s" passes "1.5 m/s". Pattern 1 (line 255) needs a "delta-v" or "dv" prefix and pattern 2 (line 256) needs a trailing "burn" or "manoeuvre", so neither matches. Because the field is truthy, the full text is never tried.
Impact:      Every NOTSO that carries ΔV in a dedicated field gets predicted_delta_v_km_s None, and magnitude_ratio and the "ΔV ratio" display disappear without notice. The only passing test (tests/unit/test_notso.py:201-203) carries ΔV inside DESCRIPTION.
Fix:         Add a bare-value pattern `^\s*([0-9.]+)\s*(m/s|km/s)` tried on field values, and fall back to the text when the field does not parse.
Gate:        Unit tests for "PREDICTED DV: 1.5 m/s" and "DELTA-V: 0.005 km/s" asserting 0.0015 and 0.005 km/s.
Verdict:     CONFIRMED
```

```
ID:          F-087   (origin F-S03-08)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:360-377
Evidence:
               issue_dt  = _parse_dt(issue_raw) or _extract_datetime(text) or datetime.now(UTC)
               start_dt = _parse_dt(start_raw) or _extract_datetime(text) or issue_dt
               end_dt = start_dt + timedelta(hours=24.0)
Issue:       Missing or unparseable dates are replaced silently. The issue date becomes the wall clock, the window start becomes the first datetime anywhere in the text (usually the issue date), and the end becomes start plus 24 h. Nothing on NOTSORecord records that a field was inferred. _parse_dt also rejects fractional seconds and numeric offsets, which pushes real values onto these fallbacks.
Impact:      A NOTSO whose window field uses an unsupported format is correlated against a fabricated window and reported as "notso_only" or mismatched, with nothing shown to the operator. Wall-clock issue dates also make repeated parses non-deterministic.
Fix:         Record per-field provenance (parsed, inferred, defaulted) on NOTSORecord and render it. Return None or flag the record instead of using now(). Support fractional seconds and offsets via datetime.fromisoformat.
Gate:        Unit tests asserting the inferred flags for a message with no window, and that "2025-03-14T12:00:00.123Z" parses.
Verdict:     CONFIRMED
```

```
ID:          F-088   (origin F-S03-09)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  inference (traced by hand through the regex)
Location:    spectre/astro/notso.py:280-285
Evidence:
               sub = re.split(r"(?:MESSAGE\s*ID|MSGID)\s*:", msg, flags=re.IGNORECASE)
               expanded.append(sub[0])
               expanded.append("MSGID: " + s)
Issue:       Any MSGID that is not the first line splits one message in two. The fields above it (often SATNO) form one fragment with a generated ID and no window. The fields below it (window, type, ΔV) form a second fragment that usually has no SATNO and is dropped at line 350 without a log.
Impact:      Header-first NOTSO layouts produce a record with a fabricated window (F-S03-08) and lose the real one. tests/unit/test_notso.py:159-163 asserts only `>= 2` and uses MSGID-first text.
Fix:         Split only on a MSGID that starts a line and is preceded by a separator or the start of the text, or treat MSGID as a field rather than a separator.
Gate:        A unit test with "SATNO: 43689\nMSGID: X\nEFFECTIVE START: ..." asserting one record with the stated window.
Verdict:     CONFIRMED
```

```
ID:          F-089   (origin F-S03-10)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:301-350
Evidence:
               Parsed records.  Unparseable messages are skipped with a log warning.
               except Exception as exc:
               return None  # Can't correlate without NORAD ID
Issue:       Messages without a NORAD ID are dropped with no log, contradicting the docstring. Messages that raise are logged only to the server log. The pasted-text route warns only when zero records parse (spectre/web/routes/pol.py:1028-1032).
Impact:      An operator pasting five NOTSOs where two drop sees a profile built on three with no indication. Undercounted notices then read as a lower notification rate.
Fix:         Return parsed records and a list of rejects with reasons. Render "n of m messages parsed" in notso_results.html.
Gate:        A route test asserting that the dropped count is shown when one of two messages lacks a SATNO.
Verdict:     CONFIRMED
```

```
ID:          F-090   (origin F-S03-11)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/notso.py:238-242
Evidence:
               r"(?:SATNO|SAT\s*NO|NORAD\s*ID|NORAD|CATALOG\s*NO|CATNO)[:\s#]+(\d{4,6})",
               r"(?:OBJECT|OBJ)[:\s]+\d+[^\d].*?(\d{5})",
               r"\b(\d{5})\b",   # Fallback: any 5-digit number
Issue:       When no labelled ID exists, the object is taken from the first 5-digit number anywhere in the message, which may be another object, a quantity or a reference. Pattern 2 takes an arbitrary later 5-digit run.
Impact:      A NOTSO is attributed to the wrong satellite. It then silently fails the satno filter at spectre/astro/notso.py:437, or, worse, matches a different object's manoeuvres. The override at spectre/web/routes/pol.py:951-952 never fires, because the parser returns a wrong number rather than 0.
Fix:         Drop the bare 5-digit fallback, or mark such IDs as inferred and require operator confirmation.
Gate:        A unit test asserting that "close approach with 43013" without a SATNO yields no record or an inferred flag.
Verdict:     CONFIRMED
```

```
ID:          F-091   (origin F-S03-12)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:467-469
Evidence:
               offset_h = (
               (notso.effective_start_utc - best.epoch).total_seconds() / 3600.0
               )
Issue:       This is rendered as "Lead time" (spectre/web/templates/partials/notso_results.html:77) and "Mean notification lead time" (line 158), but it is the window-start offset from the after-set epoch. It ignores issue_date_utc, and its sign is negative when the notice precedes the burn.
Impact:      A notice issued three days ahead, with a window opening two hours before the burn, reads "Lead time: -2.0h". predictable_timing (std < 6 h, line 677, no source) then grades window placement, not notification behaviour.
Fix:         Define lead time as burn_epoch minus issue_date_utc (positive is ahead), keep the window offset as a separate, named field, and cite or label the 6 h threshold as tuned.
Gate:        A unit test asserting a positive lead time for a notice issued before the burn.
Verdict:     CONFIRMED
```

```
ID:          F-092   (origin F-S03-13)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:430-458
Evidence:
               3. Multiple NOTSO candidates → select closest effective_start.
               for notso in obj_notsos:
Issue:       Matching is greedy in effective_start order. The earliest NOTSO claims a manoeuvre even when a later NOTSO's window is closer, which contradicts rule 3.
Impact:      With overlapping NOTSOs, one NOTSO is mismatched and the other reported as having no detection, which distorts window accuracy and lead time.
Fix:         Build all NOTSO-manoeuvre pairs within tolerance, sort by distance, and assign greedily by smallest distance, or solve the assignment.
Gate:        A unit test with two overlapping NOTSOs and two manoeuvres where start-order greed mis-assigns.
Verdict:     CONFIRMED
```

```
ID:          F-093   (origin F-S03-14)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  Medium
Epistemics:  inference (hand calculation)
Location:    spectre/astro/pattern_of_life.py:385-386
Evidence:
               # Drift rate: positive = east
               geo_drift = 360.0 * (n_revday - _EARTH_ROT)
Issue:       Longitude drift is the rate of mean longitude (RAAN + argp + M) minus Earth rotation. The code uses the Kozai mean motion alone (approximately the rate of M) and omits the secular RAAN and argp rates. At i=0 these add 1.5·n·J2·(R/a)² = 1.5 x 1.08263e-3 x 0.02288 = 3.72e-5 of n, about 0.0134 deg/day at GEO (lunisolar terms excluded).
Impact:      A truly stationary GEO object reads about 0.013 deg/day West. That is 27% of _DRIFT_STATIONARY, and enough to flip the "→E/←W/—SK" stat card, which switches at 0.005 deg/day (F-S03-22).
Fix:         Add the J2 rates (or SGP4's nodedot and argpdot, as spectre/astro/dv_estimation.py:444-459 does) to n before subtracting Earth rotation, or difference successive geo_longitude_deg values.
Gate:        A unit test on a published station-kept GEO TLE asserting |drift| < 0.005 deg/day.
Verdict:     CONFIRMED
```

```
ID:          F-094   (origin F-S03-15)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:988-1000
Evidence:
               (sorted_m[j].epoch - sorted_m[j - 1].epoch).total_seconds() / 86400.0
               next_unc = round(interval_stats.std * 2.0, 1)
Issue:       The "Next Predicted ± X d (2σ)" card (spectre/web/templates/partials/pol_results.html:317) uses 2 x sample std from as few as 3 intervals, which implies about 95% coverage. With 3 intervals the Student t 95% factor is 4.30, not 2. The intervals use after-set epochs rather than burn_epoch.
Impact:      The window is presented with Gaussian authority it does not have, and it is biased by catalogue cadence.
Fix:         Use burn_epoch for intervals, use t-quantiles for small n (or label the band "±2 sample std, uncalibrated"), and suppress the prediction below a cited n.
Gate:        A unit test asserting that the uncertainty scales with the t-quantile for n=3.
Verdict:     CONFIRMED
```

```
ID:          F-095   (origin F-S03-16)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:6-13
Evidence:
               - Estimates ΔV between successive TLEs (propagation-difference method)
               - Scores the object on an anomaly scale vs GEO-SK baseline
               - Estimates propellant budget and remaining operational life
Issue:       The module docstring advertises a method that was replaced (lines 431-434) and three functions that lines 122-134 and tests/unit/test_pattern_of_life.py:384-390 say were moved out.
Impact:      A reader trusts the module for judgements it no longer makes, and for a ΔV method it no longer uses.
Fix:         Rewrite the header to list what the module measures, and point to spectre.domain.pol_assessment for the rest.
Gate:        Docstring review in the PR checklist.
Verdict:     CONFIRMED
```

```
ID:          F-096   (origin F-S03-29)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:648
Evidence:
               def _compute_drift_phases(records: list[TLERecord]) -> list[DriftPhase]:
Issue:       Cognitive complexity is 19, above the cap of 15 (audit/tools-raw/cogcx_run.txt:17).
Impact:      Harder to verify the wrap and threshold logic (F-S03-21).
Fix:         Lift _flush and the run-length grouping to module level.
Gate:        The cogcx gate in CI.
Verdict:     CONFIRMED
```

```
ID:          F-097   (origin F-S03-30)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:319
Evidence:
               def _parse_single_notso(text: str, index: int = 0) -> NOTSORecord | None:
Issue:       Cognitive complexity is 23 (audit/tools-raw/cogcx_run.txt:12) and radon rates it F (48) (audit/tools-raw/radon_cc_all.txt:391).
Impact:      The fallback chains behind F-S03-07 and F-S03-08 are hard to audit.
Fix:         Make one table-driven field lookup per attribute, with explicit provenance.
Gate:        The cogcx gate in CI.
Verdict:     CONFIRMED
```

```
ID:          F-098   (origin F-S03-32)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tle_preprocessing.py:106
Evidence:
               def cluster_and_reduce_tle_cache(
Issue:       Cognitive complexity is 23, above the cap (audit/tools-raw/cogcx_run.txt:13).
Impact:      This is where the counter inconsistencies in F-S03-28 live.
Fix:         Extract a per-object function returning (entry | None, ObjectClusteringSummary).
Gate:        The cogcx gate in CI.
Verdict:     CONFIRMED
```

```
ID:          F-099   (origin F-S03-34)
Lens:        L11 numerical and scientific correctness (tests)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_pattern_of_life.py:138-152
Evidence:
               gst = _gst_deg(epoch)
               assert 0.0 <= gst < 360.0
               assert epoch.year == 2026
Issue:       No routine in this file is pinned to an independent reference. GMST is checked by range, the J2 rates by sign and type (lines 300-309), the TLE epoch by year (the test's own comment gives the expected 1 March 12:00), and analyse_pattern_of_life by type (lines 352-358). No detection is pinned to a known reference burn.
Impact:      A wrong constant or a sign error in any of these passes. A prior argp sign error of exactly this kind is recorded at spectre/astro/dv_estimation.py:426-429.
Fix:         Pin GMST to Meeus 12.4 or Vallado Example 3-5 (1e-4 deg), the RAAN rate to -5.00 deg/day for a=6778 km, i=51.6 deg (1%), the epoch to 2026-03-01T12:00Z exactly, and one synthetic burn of known ΔV to a stated tolerance.
Gate:        These tests in CI.
Verdict:     CONFIRMED
```

```
ID:          F-100   (origin F-S04-07)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:281; spectre/astro/photometry.py:585
Evidence:
               usable = [c for c in corrected if c.quality_flag in ("ok", "lunar")]
               baseline = fit_baseline(corrected, sigma_clip_threshold=sigma_clip)
Issue:       The phase-function baseline is fitted to every usable observation, including the recent window that is then tested against it, so a real brightness change is partly absorbed into a0, a1 and a2 (fully so when phase angle trends with time), and the residuals are not independent of the fit; the dataclass docstring says the baseline is fitted "over a quiet period".
Impact:      Reduced power: genuine changes are under-reported or reported with a biased Δmag; the t-test also ignores the 3 fitted parameters and serial correlation between same-night observations, so p-values are not what they claim (inference).
Fix:         Fit the baseline only on epochs before `recent_cutoff` (the baseline window), then evaluate residuals of the recent window against that fit; document the independence assumption.
Gate:        Test with a step change of 0.3 mag in the recent window that asserts the recovered Δmag is within 0.05 mag of 0.3.
Verdict:     CONFIRMED
```

```
ID:          F-101   (origin F-S04-08)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:382-384
Evidence:
               num   = (var_a / na + var_b / nb) ** 2
               denom = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
               df    = num / denom if denom > 1e-15 else 1.0
Issue:       The Welch-Satterthwaite guard is an absolute threshold on a dimensional quantity (mag⁴), so for precise or large samples the degrees of freedom collapse to 1 (a Cauchy tail); for example σ = 0.05 mag with n = 3000 per group gives denom ≈ 2.3e-16 (hand computed).
Impact:      Large well-sampled datasets get grossly inflated p-values and a real change is reported "NOT SIGNIFICANT".
Fix:         Guard on `denom == 0.0` (or relative to `num`) and fall back to `na + nb - 2`.
Gate:        Unit test comparing p against scipy.stats.ttest_ind(equal_var=False) for n = 3000, σ = 0.05 within 1e-4.
Verdict:     CONFIRMED
```

```
ID:          F-102   (origin F-S04-09)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:262-266
Evidence:
               # Covariance: residual variance × (X^T X)^{-1}  (approximated from diagonal)
               res_var   = sum(r * r for r in residuals) / max(n - 3, 1)
               cov = [[res_var / max(A[i][i], 1e-12) if i == j else 0.0 for j in range(3)] for i in range(3)]
Issue:       The code uses 1/diag(XᵀX), not diag((XᵀX)⁻¹); with phase columns 1, x, x² over tens of degrees the columns are strongly correlated and this understates the coefficient variances by orders of magnitude (inference), so the stored "covariance" is not a covariance.
Impact:      Latent: any future consumer of `PhotometryBaseline.covariance` gets a falsely tight uncertainty; today it is stored only.
Fix:         Invert XᵀX (or use QR on a centred, scaled phase) and store the full matrix, or delete the field.
Gate:        Unit test against numpy.linalg.inv on a known design matrix.
Verdict:     CONFIRMED
```

```
ID:          F-103   (origin F-S04-11)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:502-503; spectre/astro/monte_carlo.py:559
Evidence:
               mean_ok = abs(recent_mean - overall_mean) < tolerance_fraction * max(abs(overall_mean), 1e-6)
               std_ok  = (overall_std < 1e-9) or abs(recent_std - overall_std) < tolerance_fraction * overall_std
Issue:       The mean test uses 1% of the absolute SMA (about 69 km in LEO), so it always passes; the std test demands 1% agreement where the sampling error of a 200-sample std is about 5%, so it almost always fails; and "recent" is the last 200 results in `as_completed` order, which is thread-scheduling dependent, so the flag is not reproducible under a fixed seed.
Impact:      The panel's "converged" or "not converged (increase samples)" label is effectively random and does not track Monte Carlo precision; with fewer than 400 samples it is always "not converged".
Fix:         Sort results by sample index before aggregation; replace with a standard-error criterion on the percentiles (for example bootstrap half-width under a stated km tolerance).
Gate:        Test that two runs with the same seed and different `max_workers` return identical `converged`.
Verdict:     CONFIRMED
```

```
ID:          F-104   (origin F-S04-12)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/pol_mc_results.html:75-77
Evidence:
               <td style="text-align:right; padding:0.1rem 0.3rem">{{ mc.period_range_minutes[0] | round(1) }}</td>
               <td style="text-align:right; padding:0.1rem 0.3rem; font-weight:700; color:var(--text-primary)">—</td>
               <td style="text-align:right; padding:0.1rem 0.3rem">{{ mc.period_range_minutes[1] | round(1) }}</td>
Issue:       The period row shows the minimum and maximum under columns headed "5th %ile" and "95th %ile" (lines 55 and 57), and the panel carries no statement that the force model and dispersions are archetype assumptions rather than measurements beyond the footer "J2 + exponential drag · RIC perturbation model".
Impact:      The operator reads extremes as percentile bounds; modelled dispersion envelopes are presented with the same visual weight as measured figures.
Fix:         Compute period P5 and P95 or relabel the row "min / max"; add a line naming the archetype, its assumed sigmas and the in-track direction assumption.
Gate:        Template snapshot test for the MC partial.
Verdict:     CONFIRMED
```

```
ID:          F-105   (origin F-S04-13)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/monte_carlo.py:63-69
Evidence:
               (200,  2.530e-10, 29.740),
               (300,  1.950e-11, 37.105),
               (400,  3.614e-12, 45.546),
Issue:       The density table is uncited, and its scale heights look like Vallado's exponential atmosphere (Fundamentals of Astrodynamics, Table 8-4) shifted by one band (29.740 is the 180 km entry, 37.105 the 200 km entry, 53.628 the 300 km entry) with base densities that do not match the published rows; the resulting density at 550 km is 2.22e-13 kg/m³ (hand computed) against about 3.2e-13 from the published table, and at 700 km 1.04e-14 against about 3.6e-14.
Impact:      Combined with F-S04-03 the drag force is not the model the docstring implies; individually a 30% to 250% density error.
Fix:         Transcribe Table 8-4 exactly with the source cited, or call an existing density model.
Gate:        Unit test pinning density at 3 altitudes to the cited table within 1%.
Verdict:     CONFIRMED
```

```
ID:          F-106   (origin F-S04-15)
Lens:        L11 numerical and scientific correctness (test validity)
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    tests/unit/test_dv_estimation.py:123-132
Evidence:
               def _burn(tle: str, d_alt_km: float = 0.0, d_inc_deg: float = 0.0,
               d_ecc: float = 0.0) -> str:
               """Apply an impulse to an element set, at its own epoch."""
Issue:       The synthetic "impulse" changes mean motion, eccentricity or inclination while keeping mean anomaly and argument of perigee, which produces a concentric orbit Δa away (a two-burn end state), not the single-impulse state that shares the burn point; the swept estimator is therefore never tested on the geometry its docstring describes, and the module's "better than 0.1%" claim is pinned only to 1% (test :297).
Impact:      The headline estimator's accuracy on real single-burn pairs is unverified; also the fixture and the code share the Kozai-SMA convention (pattern_of_life.py:363-365), so a convention error would cancel.
Fix:         Add fixtures built from an SGP4 state at the burn plus a Δv vector, refitted to mean elements, and pin both estimators with stated tolerances; correct the 0.1% claim or test it.
Gate:        The new fixture tests in CI.
Verdict:     CONFIRMED
```

```
ID:          F-107   (origin F-S04-22)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:664; spectre/astro/photometry.py:208; spectre/astro/photometry.py:271
Evidence:
               def parse_photometry_csv(
               def _fit_least_squares_quadratic(
               def fit_baseline(
Issue:       Cognitive complexity 27, 19 and 19, above the cap of 15 (audit/tools-raw/cogcx_run.txt:8, :18, :19); the hand-rolled normal-equation solver on unscaled degree powers is also poorly conditioned (sx4 is of order n·1e8).
Impact:      Hard to verify; precision loss in the fit.
Fix:         Replace the solver with numpy.linalg.lstsq on centred, scaled phase; split the parser's column lookup into a header map built once.
Gate:        Cognitive-complexity gate in CI.
Verdict:     CONFIRMED
```

```
ID:          F-108   (origin F-S04-23)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:491-492
Evidence:
               if not baseline_residuals or not recent_residuals:
               return 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
Issue:       An empty baseline or recent window returns p = 1.0 with zero statistics, which `assess_photometry` reports as "No significant brightness change detected" with no confounder recorded.
Impact:      The operator cannot tell "no data in the window" from "data shows no change".
Fix:         Return a sentinel or raise, and add a confounding factor naming the empty window and its counts.
Gate:        Test that an empty recent window yields a confounding-factor entry.
Verdict:     CONFIRMED
```

```
ID:          F-109   (origin F-S04-26)
Lens:        L11 numerical and scientific correctness (tests)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_monte_carlo.py:145-147; tests/unit/test_photometry.py:105-111
Evidence:
               # With only 400 samples and window=200, result may vary — just test no crash
               result = check_convergence(vals, window_size=200)
               assert isinstance(result, bool)
Issue:       Monte Carlo and photometry tests check shape, ordering and bounds only: no test pins the J2 ODE to the analytic node rate, the drag term to an independent decay, the Welch p-value to a reference (for example scipy or a table value such as t = 2.228, df = 10, p = 0.05), or `hypothesis_from_tle_record` at all; the convergence test asserts only the return type.
Impact:      F-S04-01, -02, -03, -08 and -11 all pass the current suite.
Fix:         Add reference-pinned tests: RAAN drift over 48 h against −1.5·n·J2·(R/p)²·cos i within 1%; Welch p within 1e-5 of scipy.stats; incomplete Beta against tabulated values.
Gate:        Coverage of monte_carlo.py:654-667 and reference tests in CI.
Verdict:     CONFIRMED
```

```
ID:          F-110   (origin F-S05-01)
Lens:        L11 numerical and scientific correctness
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:335-338
Evidence:
               else:  # MAXIMIN — maximise best-case score (here: minimise min score)
               for j in range(n_friendly):
               scores[j] = min(outcome_matrix[i][j].composite_score for i in range(n_adversary))
Issue:       The selector labelled MAXIMIN (and documented at decision.py:49 as "maximise worst-case benefit") actually picks the response with the lowest best-case cost, which is minimin, the most optimistic rule, not maximin.
Impact:      With cost columns A (0.9, 0.1) and B (0.5, 0.5), true maximin over benefit picks B (worst case 0.5) while this code picks A (best case 0.1, worst case 0.9); an operator choosing "Maximin" for a conservative answer gets the riskiest one, badged "Robust Recommendation" at decision_results.html:13.
Fix:         Rename the strategy to OPTIMISTIC or MINIMIN and relabel the option at decision_panel.html:140, or, if maximin is wanted, note that maximin over benefit equals minimax over cost and remove the duplicate; correct the enum comment and docstring at :49 and :305.
Gate:        Unit test with a hand-built 2x2 matrix asserting the exact response chosen by each of the three selectors.
Verdict:     CONFIRMED
```

```
ID:          F-111   (origin F-S05-04)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:228-232
Evidence:
               if sep > 0:
               # Scale analytic CA by ratio of actual/typical separation
               ca_km = min(ca_km, sep * friendly.reversibility + base_ca_km * (1.0 - friendly.reversibility))
Issue:       The bandit B110 `except Exception: pass` at :231-232 swallows TLE parse, SGP4 and programming errors with no log and no flag on the result, so the caller cannot tell refined from analytic output; the refinement itself is a single-instant separation (not a closest approach) blended by friendly reversibility, and can only lower CA.
Impact:      A malformed TLE or a code regression in TLEOrbit silently reverts every cell to the lookup table; today the block is dead in production because the route passes red_tle = None, and coverage shows it never runs (pytest.txt:80, lines 214-232).
Fix:         Catch only ValueError and RuntimeError, log at warning with the pair id, set `basis="analytic"` or `"tle"` on OutcomeMetrics, and either compute a true minimum separation over the horizon or delete the block.
Gate:        Ruff S110 and BLE001 enabled in CI for spectre/domain; unit test with a bad TLE asserting the basis field reads "analytic".
Verdict:     CONFIRMED
```

```
ID:          F-112   (origin F-S05-05)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:250-254
Evidence:
               norm_custody  = 0.0 if custody_maintained else min(custody_gap_hours / scenario.horizon_hours, 1.0)
               norm_ca       = 1.0 - min(ca_km / 50_000.0, 1.0)   # high CA = low score (good)
               norm_dv       = min(dv_km_s / 0.1, 1.0)
Issue:       No validation of horizon_hours, probability, confidence, cost or reversibility: horizon 0 raises ZeroDivisionError at :253, reversibility above 1 makes norm_rev and custody gap negative, negative probabilities pass the `total_p <= 0` guard at :326 only when the sum is non-positive, and the HTML min/max attributes (decision_panel.html:34, :93, :95) are client-side only.
Impact:      Out-of-range form values yield negative or meaningless composite scores that still rank and recommend; horizon 0 surfaces as "Evaluation error: float division by zero".
Fix:         Validate in Scenario/AdversaryAction/FriendlyResponse `__post_init__` (ranges [0, 1], horizon > 0) and reject at the route.
Gate:        Parametrised unit tests for each out-of-range field expecting ValueError.
Verdict:     CONFIRMED
```

```
ID:          F-113   (origin F-S05-06)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:164-171
Evidence:
               requires TLE strings.  When both ``blue_tle`` and ``red_tle`` are supplied,
               closest-approach estimation uses the TLE epoch separation as a proxy.
Issue:       The docstring misstates three rules (custody also lost for POSTURE_CHANGE, gap also scaled by adversary confidence, TLE refinement uses propagated position not epoch separation), and the module docstring at :3-4 claims SGP4 propagation drives the evaluation.
Impact:      A reviewer or operator reading the docstring trusts a physics basis and a custody rule that the code does not implement.
Fix:         Rewrite the module and function docstrings to describe the lookup model as implemented and state that it is uncalibrated.
Gate:        Doc review checklist; a test per documented rule (claims 7 to 10).
Verdict:     CONFIRMED
```

```
ID:          F-114   (origin F-S05-07)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/scenario.py:40; spectre/domain/decision.py:155
Evidence:
               def plan(
               def compute_outcome_metrics(
Issue:       Cognitive complexity 27 for ScenarioPlanner.plan and 20 for compute_outcome_metrics, both above the cap of 15 (audit/tools-raw/cogcx_run.txt:9, :16); ruff also reports C901, PLR0912 and PLR0915 on compute_outcome_metrics (ruff_house.txt:328-330).
Impact:      The nested window state machine and the five-part scoring are where F-S05-03 and F-S05-08 hide; branch coverage is 64 per cent for scenario.py.
Fix:         Split plan into a per-pair `_scan_pair` generator and split compute_outcome_metrics into `_custody`, `_closest_approach`, `_composite`.
Gate:        scripts/cognitive_complexity.py --max 15 as a blocking CI step.
Verdict:     CONFIRMED
```

```
ID:          F-115   (origin F-S05-08)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/domain/scenario.py:22-24, :81-90
Evidence:
               _ACCESS_RANGE_KM = 500.0
               # Propagation step for access search.
               _STEP_S = 60.0
Issue:       A fixed 60 s step against a 500 km threshold can skip a fast encounter entirely (a 400 km miss at 10 km/s relative speed is inside 500 km for a 600 km chord, about 60 s) and min_range_km is the sampled minimum with no refinement, so it overstates the true closest approach; a failed propagation step (:86-88) neither closes nor ends the window, and the horizon is a hard-coded 24 h (:63).
Impact:      Missed or understated close approaches in any caller; currently latent because ScenarioPlanner has no production caller, and the range path is untested (coverage misses 90-106).
Fix:         Adaptive step bounded by threshold / relative speed, golden-section refinement of each window minimum, close the window on propagation error, take the horizon from RunConfig.
Gate:        Unit test with two TLEs of known TCA and miss distance (for example a crossing pair whose TCA is computed independently) asserting min_range_km within 1 km.
Verdict:     CONFIRMED
```

```
ID:          F-116   (origin F-S05-10)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/pol_assessment.py:176-179
Evidence:
               #: Upper edge of the GEO protected region, km of altitude. A raise that ends
               #: above it is disposal, not relocation, and the two look identical in the
               _GEO_PROTECTED_MAX_ALT_KM: float = 36186.0
Issue:       36,186 km is GEO plus 400 km, copied from the regime band edge at spectre/astro/constants.py:23 ("GEO upper bound + 400 km"); the IADC Space Debris Mitigation Guidelines define the GEO protected region as GEO altitude plus or minus 200 km, so the upper edge is 35,986 km.
Impact:      A standard 300 km graveyard raise ends near 36,086 km and is labelled "relocation" rather than "graveyard disposal"; the guarding test at tests/unit/test_pol_assessment.py:89 passes only because its "300 km" fixture sets the end altitude to 36,486 km, 700 km above GEO.
Fix:         Define the protected region once from _GEO_BAND_ALT plus 200 km with an IADC citation, and correct the test fixtures to alt_after = 35,786 plus delta_alt.
Gate:        Test asserting a 300 km raise from 35,786 km classifies as "graveyard disposal" and a 150 km raise does not.
Verdict:     CONFIRMED
```

```
ID:          F-117   (origin F-S05-11)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/pol_assessment.py:1058-1059, :601-604, :897-901
Evidence:
               lons = [r.geo_longitude_deg for r in records if r.geo_longitude_deg is not None]
               lon_range = (max(lons) - min(lons)) if len(lons) > 1 else 0.0
Issue:       Longitudes arrive in (-180, 180] (spectre/astro/pattern_of_life.py:383) but range and predictions are computed without wrap-around, so an object holding a slot near 180 deg reads a span near 360 deg and predicted longitudes can leave the valid interval.
Impact:      A station-kept object at the antimeridian is called a "GEO belt roamer", gets full longitude-coverage anomaly score and an inflated risk level.
Fix:         Compute the minimal circular span of the longitude set and wrap predictions into (-180, 180].
Gate:        Unit test with longitudes 179.9 and -179.9 asserting a span of 0.2 deg.
Verdict:     CONFIRMED
```

```
ID:          F-118   (origin F-S05-12)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/domain/pol_assessment.py:474
Evidence:
               remaining = max(0.0, platform.discretionary_max_m_s - since_reset_m_s)
Issue:       Discretionary remaining subtracts every confirmed manoeuvre, including routine station-keeping, from the discretionary reserve that the platform basis (manoeuvre_calibration.py:407-410) defines as what is left after station-keeping commitments.
Impact:      A healthy chemical GEO comsat observed for about four years at 48 m/s/yr reads 0 m/s discretionary remaining; if this field is ever wired into CapabilityEvidence it triggers the incapacity override at threat_assessment.py:260-264 and the threat verdict drops to MINIMAL; today threat.py:702-705 passes only intel and status, so the effect is confined to the PoL narrative at :519-523.
Fix:         Subtract only manoeuvres classified as not routine (v.is_routine is False) from the discretionary reserve.
Gate:        Test: GEO object with 5 years of 1.8 m/s fortnightly burns keeps its full discretionary reserve.
Verdict:     CONFIRMED
```

```
ID:          F-119   (origin F-S05-13)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/manoeuvre_calibration.py:171-174
Evidence:
               An unrecognised method falls back to RENDEZVOUS, the most permissive band,
               so a new solver is never accidentally scored as more alarming than it is.
               """
Issue:       RENDEZVOUS is not the most permissive band: in GEO PLANE_CHANGE is 50/160 m/s against RENDEZVOUS 25/120, and in LEO PHASING is 50/200 against 30/150.
Impact:      An unmapped GEO method costing 130 m/s reads AGGRESSIVE where the plane-change band would give ANNOYANCE, the opposite of the promise; the test at tests/unit/test_manoeuvre_calibration.py:178-179 pins only the mapping, so this passes.
Fix:         Either fall back to `_DEFAULT_BAND` (75/300) for unknown methods, or reword the claim.
Gate:        Test asserting the fallback band's annoyance_max is the maximum across kinds for each regime.
Verdict:     CONFIRMED
```

```
ID:          F-120   (origin F-S05-15)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/threat_assessment.py:277-283, :322-324
Evidence:
               if self.anomaly_score is not None:
               if self.anomaly_score >= _ANOMALY_HIGH:
               candidates.append(Band.CRITICAL)
Issue:       Any anomaly score (even 0) yields at least MEDIUM and any propellant figure yields at least MEDIUM, and `max(candidates)` lets that override an assessed LOW; the cut-offs 60 and 80 (:141-142), 0.5 share and 50 per cent are uncited and disagree with the PoL ladder that calls 55 HIGH (pol_assessment.py:120).
Impact:      An object assessed LOW with a quiet anomaly score of 5 is graded MEDIUM capability; the same score reads HIGH in the PoL panel and MEDIUM in the threat verdict between 55 and 60. Latent while threat.py:702-705 passes only intel fields.
Fix:         Map the anomaly score through the shared _RISK_LADDER, let a low score contribute LOW or nothing, and document each cut-off as tuned.
Gate:        Test asserting LOW intel plus anomaly 5 does not exceed LOW, and that PoL and threat use one ladder.
Verdict:     CONFIRMED
```

```
ID:          F-121   (origin F-S05-17)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:118-130; spectre/domain/threat_assessment.py:327-350; spectre/domain/pol_assessment.py:738-754
Evidence:
               @dataclass
               class ScenarioResult:
               """Evaluated scenario with ranked responses and a robust recommendation."""
Issue:       No domain output carries the code version (spectre/__init__.py:3 `__version__ = "0.5.24"`), a calibration-table version, or the identity of its inputs (TLE epochs, element set numbers, a hash); RunConfig (models.py:425-441) carries operator and run_id but is used only by the unused ScenarioPlanner.
Impact:      A verdict or recommendation cannot be reproduced or traced to the element sets and code that produced it after the session ends.
Fix:         Add a frozen Provenance dataclass (code version, calibration source version, input TLE epochs and hashes, computed_at) to ScenarioResult, ThreatAssessment and PolAssessment.
Gate:        Test asserting every top-level result has a populated provenance field.
Verdict:     CONFIRMED
```

```
ID:          F-122   (origin F-S05-18)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_decision.py:194-207
Evidence:
               def test_minimax_returns_a_friendly_response(self):
               s, om = self._two_adversary_scenario()
               robust = find_robust_response(s, om, SelectorStrategy.MINIMAX)
Issue:       All three selector tests assert only isinstance, no composite score is pinned to a hand value, the TLE path and the EV zero-probability branch (:327) are never run, and test_mc_integration_stub_does_not_crash (:297-304) asserts only that an attribute is absent.
Impact:      F-S05-01 and F-S05-03 pass the suite; any change to weights or selector maths goes unnoticed.
Fix:         Pin composite scores for the fixture (for example a1/r1 = 0.325333 by hand) and the exact pick per selector.
Gate:        Coverage gate on spectre/domain/decision.py branches; mutation test on find_robust_response.
Verdict:     CONFIRMED
```

```
ID:          F-123   (origin F-S06-05)
Lens:        L2 error handling and failure modes
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1789-1790
Evidence:
               except Exception:
               return entry
Issue:       A failed Lambert refine silently returns the original Hohmann entry; the handler then writes it back and logs "Refined #N … Lambert dV=…" (threat.py:1798-1801) with the Hohmann figure, and the row re-renders with no error.
Impact:      The operator asks for a refinement, sees no change and no reason, and the session log records a Lambert result that was never computed: a false audit record.
Fix:         Return the reason and render it in the row's `error` slot; log the failure, not a success.
Gate:        Route test with a solver that raises, asserting the fragment shows the reason and the log does not contain "Lambert dV".
Verdict:     CONFIRMED
```

```
ID:          F-124   (origin F-S06-09)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/threat.py:1102
Evidence:
               satno = str(satno_from_tle(tle)) if tle else ""
Issue:       satno_from_tle` returns `int | None` (intel.py:33), so an unparseable number becomes the string "None"; `_needs_live_tle("None")` is true, and with UDL connected `int(t.target_satno)` at 1139 raises ValueError inside `asyncio.gather` without `return_exceptions`, so the whole sweep returns HTTP 500. `red_satno` at 1297 has the same "None" defect.
Impact:      A manual target whose line 1 is Alpha-5 or otherwise non-numeric kills the sweep for that operator while connected to UDL; when not connected, "None" is shown as its NORAD number. TBC whether `TLEOrbit` accepts such a TLE (check with an Alpha-5 element set).
Fix:         satno = satno_from_tle(tle); satno_str = str(satno) if satno is not None else ""`; skip manual targets in `_fetch_missing_target_tles`; use `return_exceptions=True` and record each failure.
Gate:        Unit test of `_append_manual_targets` with an unparseable line 1 asserting `target_satno == ""`.
Verdict:     CONFIRMED
```

```
ID:          F-125   (origin F-S06-10)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:679-681
Evidence:
               notes.setdefault(name, f"exceeds the {budget:g} m/s budget")
               # BLE001: one refusal is recorded and the sweep continues.
               except Exception as exc:  # noqa: BLE001
Issue:       One `method_refusals` dict is shared across every target, epoch (threat.py:1206, 1233) and actor (1468, 1477) and keyed by method name with `setdefault`, so only the first reason survives, it names no target or epoch, and a method that refused once is listed under "N method(s) produced no solution" (threat_sweep.html:169) even when it produced solutions shown in the table.
Impact:      The operator cannot tell which target or actor a refusal belongs to, and the panel contradicts the results beside it; the stated purpose (threat.py:645-654) is only partly met.
Fix:         Key refusals by `(target, method)` with epoch and reason, and drop a method from the "no solution" list when it produced any entry for that target.
Gate:        Unit test: two targets, one refusing Lambert and one solving it, asserting both facts are visible.
Verdict:     CONFIRMED
```

```
ID:          F-126   (origin F-S06-11)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1313-1315
Evidence:
               _MAX_SWEEP_TARGETS = 100
               if len(targets) > _MAX_SWEEP_TARGETS:
               targets = targets[:_MAX_SWEEP_TARGETS]
Issue:       Manual targets are appended after the HRR list (1298-1304), so truncation drops them first, and the cap counts regime-incompatible HRR objects that are later skipped (`_build_target_list` is not regime-filtered although the dropdown counts are, threat.py:300 versus 476).
Impact:      With "All HRR" over 100 objects, every target the operator explicitly pasted is silently excluded; the message (1316) does not name them, and slots can be consumed by targets that are then skipped as regime mismatches.
Fix:         Put manual targets first, filter by regime before capping, and list the names dropped.
Gate:        Unit test with 101 HRR objects and one manual target asserting the manual target is swept.
Verdict:     CONFIRMED
```

```
ID:          F-127   (origin F-S06-13)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1770-1772
Evidence:
               red_tle = _find_tle(state, state.last_threat_assessment.red_name)
               if entry.target.target_source == "blue":
               target_tle = _find_tle(state, entry.target.target_name)
Issue:       Refine ignores the manual red override used by the sweep, looks manual targets up in `hrr_tle_cache` by satno instead of their pasted TLE, and `_sol_to_entry` at 1791-1792 drops the regime so posture falls to `_DEFAULT_BAND`; the "blue" branch is dead (only "hrr" and "manual" are ever assigned, threat.py:487, 1106, 1684).
Impact:      A refined row can be computed for a different red orbit or a different target element set, or fail with "TLE not found", and its posture label is read against the wrong band.
Fix:         Store the red TLE, target TLE and regime on the assessment or entry and reuse them; delete the dead branch.
Gate:        Route test: sweep with a manual red TLE and a manual target, refine, assert the same element sets and regime are used.
Verdict:     CONFIRMED
```

```
ID:          F-128   (origin F-S06-14)
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/threat.py:1795-1797
Evidence:
               refined = await loop.run_in_executor(None, _refine)
               state.last_threat_assessment.entries[entry_index] = refined
Issue:       entry_index` is validated against one assessment (1757) and written after an `await` into whatever `state.last_threat_assessment` is then; state is shared by every browser session of the username, so a sweep finishing in another tab in between gets a foreign entry spliced in or raises IndexError. `entry_index` has no lower bound (1740), so -1 refines and overwrites the last entry.
Impact:      Corrupted assessment rows under concurrent use by one account; HTTP 500 on a shorter replacement.
Fix:         Capture the assessment object before the await and write to it, add `ge=0`, and compare identity before writing.
Gate:        Unit test replacing `last_threat_assessment` during the executor call.
Verdict:     CONFIRMED
```

```
ID:          F-129   (origin F-S06-16)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:792-794
Evidence:
               number_of_burns: Annotated[int, Form()] = 1,
               target_distance_m: Annotated[float, Form()] = 0.0,
               minimize_delta_v: Annotated[bool, Form()] = True,
Issue:       number_of_burns` and `minimize_delta_v` are accepted and never read (vulture), and the operator form offers both as live controls labelled "Optimal only" (operator.html:475-487) while posting to `/apply-all-intercepts`, which does not even declare them; no "Optimal" method exists.
Impact:      The operator sets burns or unticks "Minimise ΔV" and the result is identical, with no indication the input was ignored.
Fix:         Remove both controls and parameters until implemented, or disable them with "not yet implemented".
Gate:        Test that every named input in the intercept form maps to a parameter the target route reads.
Verdict:     CONFIRMED
```

```
ID:          F-130   (origin F-S06-17)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:410-427
Evidence:
               InterceptMethod.HOHMANN:
               {"label": _LABEL_MISS_DISTANCE, "value": "0.0 km (coplanar)"},
Issue:       Hohmann and bi-elliptic report a hardcoded "0.0 km (coplanar)" and phasing "0.0 km" (427) whatever the solver's `miss_distance_km`, while the stat card on the same panel prints the computed `result.intercept_range_km` (intercept_result.html:137).
Impact:      For non-coplanar pairs the panel shows two different miss distances, one asserted and one computed, and asserts coplanarity it never checked.
Fix:         Use `miss` for every method and drop the literal.
Gate:        Unit test on `_method_insights` with a non-zero `intercept_range_km` for HOHMANN.
Verdict:     CONFIRMED
```

```
ID:          F-131   (origin F-S06-18)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1169
Evidence:
               "miss_km": round(r.intercept_range_km, 2),
Issue:       Assessment methods carry a 0-100 score in `intercept_range_km` (spectre/astro/maneuvers.py: "miss_distance_km field encodes the observability score"), and the trade-space JSON, its tooltip (`'Miss: ' + pt.miss.toFixed(1) + ' km'`, operator.html:1058) and the clipboard text (intercept_result.html:175) label it km unconditionally.
Impact:      A score of 73 is copied or plotted as a 73 km miss distance.
Fix:         Carry scores in their own field; branch on method type in trade-space and clipboard output.
Gate:        Test that `trade_space_data` emits no `miss_km` for ASSESSMENT methods.
Verdict:     CONFIRMED
```

```
ID:          F-132   (origin F-S06-20)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1260-1262
Evidence:
               if coast_s > _SECONDS_PER_HOUR:
               return max(1, int(coast_s / _SECONDS_PER_HOUR))
               return default
Issue:       The "Pre-burn coast duration in hours" field (operator.html:466) is silently reused as phasing revolutions and V-bar and H-bar hop counts, while those solvers are given no coast (1344, 1352; phasing gets none at 1326-1329).
Impact:      Setting coast to 6 h asks for six revolutions or six hops and applies no coast; the operator has no way to know.
Fix:         Separate revolution and hop fields, or document the overloading on the form and in the result.
Gate:        Integration test asserting that changing coast hours moves the burn epoch for every method.
Verdict:     CONFIRMED
```

```
ID:          F-133   (origin F-S06-22)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:834-836
Evidence:
               effective_dm = intercept_data_mode.strip().upper() or state.udl_data_mode or "REAL"
               if intercept_data_mode.strip():
               red_tle, blue_tle = await _refetch_tles(red_tle, blue_tle, effective_dm, state)
Issue:       The "Data Mode" provenance badge (intercept_result.html:10, all_intercepts_result.html:12) shows the requested mode, defaulting to "REAL", while `_refetch_tles` silently keeps the original element sets on no credentials, no satno or a failed fetch (1216-1232).
Impact:      A result computed from operator-pasted or non-REAL element sets carries a "Data Mode: REAL" badge.
Fix:         Return the actual mode per side from `_refetch_tles` and badge that, with "unverified" when no fetch happened.
Gate:        Test with no UDL credentials asserting the badge does not read REAL.
Verdict:     CONFIRMED
```

```
ID:          F-134   (origin F-S06-24)
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:265-266
Evidence:
               state.manual_sweep_tles = [e for e in state.manual_sweep_tles if e["name"] != name]
               state.manual_sweep_tles.append({"name": name, "tle": tle, "confidence": confidence})
Issue:       Manual targets have no cap on count, name length, TLE size or confidence value, and `intercept_history` grows by one per apply-intercept call (maneuver.py:886) until cleared; both live in the process-global state dict that survives session expiry.
Impact:      Unbounded memory growth per username, and every manual entry is carried into every sweep; free-text confidence values are rendered as badges.
Fix:         Cap count and sizes, validate confidence against the five options, and bound the history.
Gate:        Route tests for oversize name, oversize TLE and the count cap.
Verdict:     CONFIRMED
```

```
ID:          F-135   (origin F-S06-25)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1434-1436
Evidence:
               if got:
               tle, mode = got
               state.hrr_tle_cache[actor.actor_satno] = tle  # type: ignore[attr-defined]
Issue:       A failed actor fetch in the screen has no else branch, so the actor is screened on its synthetic or stale element set with no note, unlike the sweep which records the failure (1147-1148).
Impact:      The operator is told an actor was assessed, with no sign it rests on a bootstrap orbit after a failed refresh.
Fix:         Record the failure in `notes` and tag the verdict with the element set's data mode.
Gate:        Screen route test with a failing fetch stub asserting a note.
Verdict:     CONFIRMED
```

```
ID:          F-136   (origin F-S06-26)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:208-210
Evidence:
               def _objects_for_group(
               state: object, side: str, rank: int, regime: str | None = None,
               ) -> list[dict[str, Any]]:
Issue:       Cognitive complexity 17 against the cap of 15 (audit/tools-raw/cogcx_run.txt:20); it duplicates the filter loop in `_hrr_group_counts` (176-205).
Impact:      Two copies of the side, rank and regime rules that must be kept in step by hand.
Fix:         One predicate `_matches(obj, side, rank, regime)` used by both.
Gate:        scripts/cognitive_complexity.py --max 15` in CI.
Verdict:     CONFIRMED
```

```
ID:          F-137   (origin F-S06-28)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_threat_sweep.py:309-310
Evidence:
               entries.sort(key=lambda e: e.delta_v_m_s)
               assert entries[0].delta_v_m_s == 0.5
Issue:       test_entry_sorting` tests Python's `list.sort`, not application code; `test_group_entries` says "sorts by best delta-V" while asserting warning-time order; `test_sweep_all_methods` checks only `delta_v_m_s > 0` with no reference value; `test_delta_v_is_shown_in_whole_metres_per_second` passes on "401.200"; the screen route tests clear the whole shared `hrr_tle_cache` (test_threat_screen_route.py:121, 141), wiping the bootstrap cache for later tests.
Impact:      Tests that cannot fail, or fail for the wrong reason, give false assurance on the ranking and unit paths.
Fix:         Delete the tautological test, pin `_sweep_all_methods` to a reference Hohmann case with a tolerance, assert no decimals, restore the cache rather than clearing it.
Gate:        Mutation testing on threat.py ranking functions.
Verdict:     CONFIRMED
```

```
ID:          F-138   (origin F-S07-07)
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:472-474
Evidence:
               mask = (
               df.apply(lambda col: col.astype(str).str.lower().str.contains(qlo, na=False))
               .any(axis=1)
Issue:       The operator's search string goes to pandas `str.contains`, whose default is `regex=True`, and runs synchronously on the event loop across every column of datasets with tens of thousands of rows.
Impact:      q=(` raises re.error and returns a 500, and a catastrophic-backtracking pattern stalls the single worker, freezing every operator's console. The path is untested (pytest.txt:110 misses 463-500).
Fix:         Pass `regex=False`, cap `q` length, and run `_page_data` in the executor.
Gate:        Unit test calling `_page_data` with `q="("` and `q="(a+)+$"` on a cached frame, asserting no exception and a bounded run time.
Verdict:     CONFIRMED
```

```
ID:          F-139   (origin F-S07-08)
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:609-611
Evidence:
               _CACHE.clear()
               _CACHE_FETCH_TIME = None
               await _load_all()
Issue:       Any logged-in operator can clear the cache shared by every operator and start 28 downloads, with no role check and no rate limit. The clear runs before the `_FETCHING` guard (gcat.py:383-385), so a second refresh during a first wipes what is loading and returns an empty panel. `_FETCHING` is reset without try/finally (gcat.py:421), and on-demand loads (gcat.py:563-568) have no single-flight, so N concurrent first views download the same dataset N times.
Impact:      One operator can repeatedly blank GCAT for everyone and hammer a third-party personal site from SPECTRE's address. A cancelled refresh leaves `_FETCHING` True and blocks refresh until the process restarts.
Fix:         Restrict refresh to admin, rate-limit it, check `_FETCHING` before clearing, swap in the new cache atomically, use try/finally, and put a per-key lock on the on-demand path.
Gate:        Async test running two concurrent refreshes, asserting the cache ends full and `_FETCHING` ends False.
Verdict:     CONFIRMED
```

```
ID:          F-140   (origin F-S07-11)
Lens:        L2 Error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:541-543
Evidence:
               line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
               line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
               return name, f"{line1}\n{line2}", line1
Issue:       In latest mode, when no record carries a parsable line 1, `_select_latest_elset` falls back to `records[0]` (udl.py:517), `_extract_tle_fields` does not check for empty lines, and fetch_tle renders `error: None` with `tle` set to "\n" and a "TLE loaded" success line. Diagnostics read a `tle1` key (udl.py:478) that extraction ignores.
Impact:      The operator is told a TLE loaded when the form holds nothing usable, and the failure surfaces later and somewhere else.
Fix:         Return an error from fetch_tle when line1 or line2 is empty, and read the same key set in diagnostics and extraction.
Gate:        Unit test: a record with only `tle1`/`tle2` keys yields a non-None error.
Verdict:     CONFIRMED
```

```
ID:          F-141   (origin F-S07-13)
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.py:93-94
Evidence:
               with open(self._path, "w", encoding="utf-8") as fh:
               json.dump(self._data, fh, indent=2, ensure_ascii=False)
Issue:       Every sync page truncates and rewrites the whole (8.6 MB) JSON file in place, synchronously on the event loop, with no temp-file-and-rename. A crash mid-write leaves a corrupt file that `_load` silently replaces with an empty cache (notso_cache.py:82-86), after which the next sync re-pulls from 2024-01-01. The file sits inside the package directory, which in the image is ephemeral (/app/spectre/data).
Impact:      Data loss on a crash or disk-full, a stalled event loop during each page write, and a cache that disappears on every pod restart.
Fix:         Write to a temp file in the configured data directory and `os.replace` it; run the write in a thread; move the path under SPECTRE_DATA_DIR or STORAGE_MOUNT_PATH; keep the corrupt file aside instead of silently resetting.
Gate:        Unit test that simulates an exception mid-dump and asserts the previous file survives.
Verdict:     CONFIRMED
```

```
ID:          F-142   (origin F-S07-14)
Lens:        L3 Security
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:981-982
Evidence:
               catalog = get_onorbit_catalog()
               status = get_catalog_status()
Issue:       /udl/catalog/search and the cache path of /pol/notso-correlate (pol.py:1035-1036) serve UDL-derived data fetched with one operator's credential to any logged-in operator, and check neither that operator's UDL session nor their UDL entitlement.
Impact:      A SPECTRE account with no UDL access can browse the UDL on-orbit catalogue and REAL-mode JCO notifications, so UDL's own access decision is bypassed (the entitlement consequence is inference; the mechanism is fact).
Fix:         Require an active UDL session for both routes at minimum; preferably cache per UDL identity, or re-validate entitlement per request.
Gate:        Integration test: operator B without UDL login gets an error from /udl/catalog/search after operator A has populated the catalogue.
Verdict:     CONFIRMED
```

```
ID:          F-143   (origin F-S07-15)
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:316-317
Evidence:
               asyncio.create_task(_fetch_onorbit_background(username, password))
               asyncio.create_task(_discover_tle_sources(username, password, state))
Issue:       The task handles are discarded, so the event loop holds only a weak reference and a task can be collected before it finishes (Python asyncio documentation). The "ready" guard (udl.py:197-199) does not cover "loading", so concurrent logins duplicate the 60 s catalogue pull. Once "ready", the catalogue is never refreshed for the life of the process. The tasks keep using the password after the operator presses UDL logout.
Impact:      Silent catalogue load failure stuck at "loading", duplicate full-catalogue pulls, a catalogue that goes stale indefinitely, and credential use after logout.
Fix:         Keep task references in a module set with a done-callback, add a single-flight lock, add a TTL refresh, and cancel session-bound tasks on UDL logout.
Gate:        Unit test that two logins in quick succession produce one /onorbit request.
Verdict:     CONFIRMED
```

```
ID:          F-144   (origin F-S07-16)
Lens:        L4 Contracts and data
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/pol.py:114-116
Evidence:
               params: dict[str, Any] = {
               "satNo": satno,
               "epoch": ">2015-01-01T00:00:00.000000Z",
Issue:       The history pull is a single request capped at 5,000 records (pol.py:35,117), with no paging and no check of whether the cap was hit. The current elset is then appended, so a long-lived object whose archive is truncated gets a silent gap between the 5,000th elset and today.
Impact:      Manoeuvres inside the gap are never detected, and the PoL verdict and cumulative delta-v are presented as covering 2015 to now when they do not. The gap may only show as `skipped_long_gap` in the detection audit.
Fix:         Page until exhausted (with a cap), or detect `len(records) == _UDL_MAX_RESULTS` and show "history truncated at <epoch>" in the results panel.
Gate:        Unit test: a mocked 5,000-record response produces a visible truncation flag in the view context.
Verdict:     CONFIRMED
```

```
ID:          F-145   (origin F-S07-19)
Lens:        L6 Performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:797-800
Evidence:
               n_samples=min(max(n_samples, 50), 2000),
               archetype_override=manoeuvre_type,
               )
Issue:       /pol/monte-carlo clamps samples but leaves `horizon_h` (pol.py:762,800) unbounded, runs in the shared default executor, and has no rate limit. /pol/photometry-analyse parses an unbounded CSV on the event loop.
Impact:      One operator can queue arbitrarily long propagations and starve the executor that other features use.
Fix:         Bound horizon_h (for example to 720 h), cap the CSV size, and add a per-operator compute rate limit.
Gate:        Form-validation test rejecting horizon_h above the cap.
Verdict:     CONFIRMED
```

```
ID:          F-146   (origin F-S07-20)
Lens:        L8 Clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/data/intel.py:4-5
Evidence:
               keyed by NORAD catalogue number.  Data sourced from the Adversary Satellite
               Activity Report (UNCLASSIFIED // PAIR, 30 March 2026).
Issue:       The docstring attributes the whole dataset to one PAIR report, but the records cite open sources (McDowell 2025, CSIS 2025, SWF 2025, RAND 2025) and one "Iran Space OOB (PAIR/PatchPlus Feb 2026)" source (adversary_intel.json:350). The JSON itself carries no marking, and the threat_level values (CRITICAL/HIGH/MEDIUM/LOW) have no stated method.
Impact:      Operators see these records as "pair" in PoL results (pol.py:192,366) with an authority and handling status the data does not state.
Fix:         Record the actual per-record provenance and handling marking in the file header, and label threat_level as an analyst judgement in the template.
Gate:        Test asserting every record has a non-empty `source` and that the file carries a top-level marking and provenance field.
Verdict:     CONFIRMED
```

```
ID:          F-147   (origin F-S07-26)
Lens:        L8 Clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_udl_tle_fetch.py:43-45
Evidence:
               def test_two_digit_year_post_2000(self) -> None:
               # Year "99" → 1999 (< 57 threshold)
               line = "1 25544U 98067A   99001.00000000  .00000000  00000-0  00000-0 0  9999 0"
Issue:       The test name and comment contradict what it asserts (99 is not below 57 and maps to 1999). Its sibling `test_two_digit_year_pre_2000` (:50) tests 57 to 1957, and no test pins 56 to 2056 or 00 to 2000. Separately, test_notso_cache.py:145 asserts only `added >= 0`, which cannot fail.
Impact:      The pivot boundary on the 20xx side is unpinned, and one cache test proves nothing.
Fix:         Rename the tests; add cases for 00, 56 and 57; replace the vacuous assertion with the intended behaviour.
Gate:        A ruff/pytest plugin flagging tautological assertions (`>= 0` on a count).
Verdict:     CONFIRMED
```

```
ID:          F-148   (origin F-S08-03)
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/admin.py:283-285, spectre/web/planning_state.py:126-133
Evidence:
               username = user.username
               await db.delete(user)
               await db.commit()
Issue:       Deleting a user (and session expiry, and a password reset) never clears that username's `SessionState`, which holds the UDL username and password, so the state outlives the account and is handed to any later account created with the same name.
Impact:      A recreated or reassigned username inherits the previous holder's live UDL credentials, planning results and caches; a removed operator's UDL password stays in process memory until restart, contradicting planning_state.py:55.
Fix:         Call `clear_session_state(username)` in `delete_user` and whenever the generation is advanced (password change listener, logout); key the store by user id rather than username.
Gate:        Integration test: set UDL credentials on X's state, delete X, assert `planning_state._store` has no entry for X; recreate X and assert `udl_password is None`.
Verdict:     CONFIRMED
```

```
ID:          F-149   (origin F-S08-05)
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  inference
Location:    spectre/web/routes/admin.py:221-231
Evidence:
               if user.role == "admin" and role != "admin":
               admin_count = await _admin_count(db)
               if admin_count <= 1:
Issue:       The last-admin guard is a read-then-write with no lock or conditional update, so two concurrent demotions (or a demotion racing a delete) each see a count of 2 and both commit; the delete guard at admin.py:274-281 is unreachable except under this race, because self-delete is refused first.
Impact:      Zero admin accounts; recovery needs SPECTRE_ADMIN_RESET and a redeploy.
Fix:         Perform the demotion or delete as a single conditional statement (`UPDATE ... WHERE (SELECT count(*) ... role='admin') > 1`) or take a row lock (`SELECT ... FOR UPDATE`) on admin rows inside the transaction.
Gate:        Concurrency test issuing two simultaneous demotions of two remaining admins, asserting at least one admin remains.
Verdict:     CONFIRMED
```

```
ID:          F-150   (origin F-S08-06)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/auth.py:39, spectre/web/auth.py:45
Evidence:
               hashed: bytes = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt())
               return bool(bcrypt.checkpw(plaintext.encode(), hashed.encode()))
Issue:       The pinned bcrypt is 5.0.0 (requirements-runtime.txt:81), which raises ValueError for inputs over 72 bytes instead of truncating, and nothing bounds or catches it.
Impact:      A long password at POST /login raises before the limiter is charged (unmetered 500 on an unauthenticated endpoint); a long admin-set password gives a 500; a long SPECTRE_ADMIN_PASS stops the boot in `_bootstrap_admin` (database.py:245).
Fix:         Reject passwords over 72 UTF-8 bytes with a form error at create/update and bootstrap, and treat an over-long login password as a failed attempt (charged to the limiter) without calling bcrypt.
Gate:        Unit test `verify_password("x"*100, h)` path and integration test posting a 100-byte password to /login asserting 401, not 500.
Verdict:     CONFIRMED
```

```
ID:          F-151   (origin F-S08-07)
Lens:        L3 security
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/csrf.py:25
Evidence:
               _EXEMPT_PATHS = frozenset({"/login"})
Issue:       POST /login has no CSRF, Origin or Referer check, so a cross-site page can sign the victim's browser into an attacker-owned account (login CSRF); SameSite=Lax does not stop a cookie being set on a top-level cross-site POST response.
Impact:      Speculation: an operator who does not notice the username then enters UDL credentials and planning inputs into the attacker's session, where they are stored under the attacker's username (planning_state.py:113).
Fix:         Require `Origin` (or `Referer`) to match the host on POST /login, or issue a pre-session CSRF cookie on GET /login and verify it on POST.
Gate:        Integration test: POST /login with `Origin: https://evil.example` asserts 403.
Verdict:     CONFIRMED
```

```
ID:          F-152   (origin F-S08-08)
Lens:        L3 security
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/login.py:202-212, spectre/web/deps.py:48-49
Evidence:
               cookie = request.cookies.get(_COOKIE_NAME)
               if cookie:
               username = decode_session_cookie(cookie)
Issue:       Logout decodes the cookie without the generation check, and `render` mints a valid CSRF token for whatever cookie is presented (GET /login renders base.html's meta tag), so a holder of a revoked but unexpired token can obtain a token and call /logout repeatedly.
Impact:      The very attacker logout was meant to cut off can keep ending the operator's live sessions for up to 8 hours after the token was issued.
Fix:         In `post_logout`, resolve the user and skip `_revoke_sessions` when `_session_revoked(user, gen)` is true; mint CSRF tokens in `render` only for a cookie that decodes to a current session.
Gate:        Integration test: capture cookie A, log out, log in as B session, replay logout with A and its token, assert B's session still answers 200.
Verdict:     CONFIRMED
```

```
ID:          F-153   (origin F-S08-10)
Lens:        L3 security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/config/settings.py:230-238
Evidence:
               elif sslmode and sslmode not in _SSLMODE_NEGOTIATE:
Issue:       Any unrecognised sslmode (a typo such as `verify_full`) falls into the `require` branch and builds a context with `CERT_NONE`, silently downgrading a requested verification to none, and `sslcert`/`sslkey` are dropped without warning.
Impact:      An operator who asked for certificate verification gets an unauthenticated TLS channel to the database, open to interception, with no log line.
Fix:         Treat only `require` as encrypt-without-verify and raise ConfigurationError for any other unknown value; log dropped client-certificate parameters.
Gate:        Unit test: `split_database_url(...?sslmode=verify_full)` raises ConfigurationError.
Verdict:     CONFIRMED
```

```
ID:          F-154   (origin F-S08-11)
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/planning_state.py:51, spectre/web/planning_state.py:108-109
Evidence:
               log_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
               with contextlib.suppress(asyncio.QueueFull):
               self.log_queue.put_nowait(message)
Issue:       The queue is unbounded and has no consumer, so every log line a session ever writes is retained, and the `QueueFull` suppression is dead code because an unbounded queue never raises it.
Impact:      Per-session memory grows without limit across a long shift while the docstring claims a 200-entry bound.
Fix:         Remove `log_queue` or give it `maxsize=_MAX_LOG_ENTRIES` and drop the oldest on full.
Gate:        Unit test appending 1000 entries and asserting `log_queue.qsize() <= _MAX_LOG_ENTRIES`.
Verdict:     CONFIRMED
```

```
ID:          F-155   (origin F-S08-12)
Lens:        L4 contracts and data
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/auth.py:71
Evidence:
               data = _serializer().loads(token, max_age=_SESSION_MAX_AGE)
Issue:       Session expiry, the only server-side bound on a token not revoked by logout, has no test at any layer.
Impact:      A refactor that drops `max_age` (or changes the constant) turns every session into a permanent one with the suite green.
Fix:         Add a unit test that freezes or patches time beyond 28 800 s and asserts `decode_session_cookie` returns None, and one at 28 799 s that it does not.
Gate:        That test.
Verdict:     CONFIRMED
```

```
ID:          F-156   (origin F-S08-14)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_admin_routes.py:178-196, tests/integration/test_admin_routes.py:257-260
Evidence:
               for uid in matches:
               edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
               if b"new_op" in edit_resp.content:
Issue:       Four admin tests (password reset, delete, self-delete, last admin) search in a loop and `break` with no assertion after the loop, so they pass vacuously if the row is absent; `test_cannot_delete_last_admin` tests demotion, not deletion; `test_update_role` posts the role the user already has and asserts only 200; `test_login_is_exempt_so_a_session_can_be_established` asserts only `!= 403` (test_csrf.py:118); test_csrf.py:121-164 duplicates tests/unit/test_auth.py:18-49.
Impact:      The admin authz and last-admin guards look covered while their regressions can pass.
Fix:         Add `else: pytest.fail(...)` (or a `found` flag) to each loop, add a real delete-last-admin case and a real role change asserted by re-reading the row, assert `401` on the exempt-login test, delete the duplicate class.
Gate:        Ruff PT rule set, plus a custom check that a `for ... break` in a test is followed by an assertion.
Verdict:     CONFIRMED
```

```
ID:          F-157   (origin F-S08-16)
Lens:        L7 design and structure
Severity:    Medium   (reviewer graded Low; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/app_logging/config.py:12, spectre/config/settings.py:325-327
Evidence:
               def configure_logging(run_id: str, log_level: str = "INFO", log_dir: str = "logs") -> None:
               log_dir: str = field(
               default_factory=lambda: os.environ.get("SPECTRE_LOG_DIR", "logs")
Issue:       The structlog configuration with run_id correlation is never called and `Settings.log_dir` is never read, so SPECTRE_LOG_DIR is a dead setting.
Impact:      Operators who set SPECTRE_LOG_DIR expect per-run JSON logs that are never written.
Fix:         Delete the module and the field, or wire `configure_logging` into the planning-run path.
Gate:        Vulture in CI at the current confidence.
Verdict:     CONFIRMED
```

```
ID:          F-158   (origin F-S09-02)
Lens:        L3 security
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:405-429
Evidence:
               for obj_id in completed_ids:
               obj = obj_by_id.get(obj_id)
               if obj is None:
Issue:       The client-supplied objectives list is not de-duplicated, so `["obj_load","obj_load",...]` adds an objective's points once per repetition and passes any scenario whose objectives carry no answer field.
Impact:      Every self-certified scenario, including the unpassable planner_05 (F-S09-07), passes on demand; with F-S09-01 this turns the whole progression into an unauthenticated-effort grind.
Fix:         completed_ids = list(dict.fromkeys(x for x in parsed if isinstance(x, str)))` before scoring, and score from the set of objective ids.
Gate:        Unit test posting a duplicated id list and asserting total_score equals the single-count sum.
Verdict:     CONFIRMED
```

```
ID:          F-159   (origin F-S09-03)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:215-244, 378-386, 594-603
Evidence:
               scenario = get_scenario(scenario_id)
               if scenario is None:
               return HTMLResponse('<p class="error-msg">Scenario not found.</p>', status_code=404)
Issue:       Level gating exists only on the GET detail view (training.py:191); _start_scenario, submit and tutorial completion never check level_required or the unlocked list, and submit does not check that `cr.scenario_id` matches the path scenario_id.
Impact:      A Level 1 user can start and submit a Level 5 challenge, or complete all six tutorials (580 points) on first login; a result row from one scenario can be scored against another scenario's objectives.
Fix:         Factor a `_require_unlocked(progress, scenario)` check into start, explore and submit; reject submit when `cr.scenario_id != scenario_id`; check `f"tutorial:{id}" in progress.unlocked` before awarding tutorial points.
Gate:        Integration tests: Level 1 POST to /training/scenario/planner_challenge_theatre_defence/start returns 403; mismatched result_id returns 404.
Verdict:     CONFIRMED
```

```
ID:          F-160   (origin F-S09-04)
Lens:        L1 correctness and edge cases
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:447-457
Evidence:
               if is_scored and passed:
               pa2 = award_points("challenge_passed", current_axis)
               total_points_earned += pa2.total_points
Issue:       "challenge_passed" (250, labelled "Pass a challenge scenario") and "challenge_passed_first_try" (100, "Pass a challenge on first attempt") are awarded for every passed scored attempt, including the 10 free-play scenarios; only the counter at :464 checks `scenario.challenge`.
Impact:      Free-play passes earn 500 points instead of 150, so the level thresholds in gamification.yaml do not mean what their authors tuned them for and progression is about three times faster than designed.
Fix:         Wrap the two challenge awards in `if scenario.challenge:`; award a free-play pass action (add one to the YAML) otherwise.
Gate:        Unit test on the scoring path: a passed non-challenge scenario earns exactly the scenario_completed award.
Verdict:     CONFIRMED
```

```
ID:          F-161   (origin F-S09-09)
Lens:        L8 clarity and comments
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    README.md:189-208
Evidence:
               | 2 | Trainee | 200 |
               | 6 | Expert | 4 000 |
               | `intercept_planning` | Intercept Engine and transfer methods |
Issue:       Every level title except Cadet, every threshold after 0, and four of five axis names in the README disagree with gamification.yaml (Observer 100, Planner 400, Analyst 1200, Operator 3000, Instructor 8000; axes manoeuvre_planning, decision_quality, operational_tempo, efficiency), and none of the README's unlock conditions (tutorial, scenario count, axis threshold, challenge count) are mentioned.
Impact:      Instructors and assessors reading the README will set expectations and certification criteria against a scheme that does not exist.
Fix:         Regenerate the README tables from gamification.yaml, including unlock conditions.
Gate:        Test that parses the README level and axis tables and compares them to get_config().
Verdict:     CONFIRMED
```

```
ID:          F-162   (origin F-S09-10)
Lens:        L11 numerical and scientific correctness
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    tle_clustering/clustering.py:62-74, 165; tle_clustering/selection.py:62
Evidence:
               [[r.inclination_deg, r.raan_deg, r.eccentricity] for r in records],
               return raw / tolerances
               centroid_raan = float(np.mean([m.raan_deg for m in members]))
Issue:       RAAN is treated as a linear quantity: two element sets at 359.99° and 0.01° (0.02° apart) are 7199.6 normalised units apart, and the centroid of such a group is the arithmetic mean near 180°.
Impact:      Every object whose node is near 0/360° (all LEO objects pass through it every few months under J2 regression) is split into separate clusters or noise, raising the README's "elevated uncertainty ... possible recent unannounced manoeuvre" flag on a well-tracked satellite, and a cluster that straddles the seam gets a meaningless centroid.
Fix:         Feature RAAN as a wrapped difference: use a precomputed distance matrix with `d_raan = min(|Δ|, 360 − |Δ|)` (DBSCAN `metric="precomputed"`), take the centroid as a circular mean (atan2 of mean sin and cos), and apply the same wrap in selection.py:62.
Gate:        Unit test: three TLEs at RAAN 359.98°, 359.99°, 0.01° with identical inc and ecc form one cluster with centroid within 0.01° of 359.99°.
Verdict:     CONFIRMED
```

```
ID:          F-163   (origin F-S09-12)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    README.md:399; tle_clustering/clustering.py:131-136
Evidence:
               DBSCAN (Chebyshev / L-∞)  ← eps=1.0 → all three elements within tolerance
Issue:       DBSCAN with min_samples=2 is density-connected (equivalent to single linkage), so a chain of TLEs each within tolerance of the next forms one cluster whose extremes can differ by many tolerances; "all three elements within tolerance" holds only for neighbouring pairs.
Impact:      A slow drift across a 24 h window (or a small manoeuvre bridged by intermediate fits) is merged into one cluster and one representative, hiding exactly the change the elevated-uncertainty flag claims to detect.
Fix:         State the pairwise meaning in the README, and if cluster-wide bounds are wanted, post-check each cluster's per-element span against the tolerance and split or flag when exceeded.
Gate:        Unit test with a chain of five TLEs stepped by 0.9 tolerance in inclination asserting the documented behaviour.
Verdict:     CONFIRMED
```

```
ID:          F-164   (origin F-S09-13)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/decision.py:56-151
Evidence:
               probability=float(adv_probs[i]) if i < len(adv_probs) else 0.5,
               total_w = w_custody + w_ca + w_dv + w_time + w_rev
               if total_w < 0.01:
Issue:       decision_evaluate (cognitive complexity 44, audit/tools-raw/cogcx_run.txt:3) accepts any float for probability, confidence, cost, reversibility, time, weights and horizon (including negative, NaN and 0), and any number of rows; horizon_hours=0 raises ZeroDivisionError in domain/decision.py:250 that is surfaced as "Evaluation error", and an empty numeric field returns a 422 that htmx does not swap.
Impact:      Negative weights or probabilities invert rankings and produce a "Robust Recommendation" with no warning; an unbounded N×M matrix is a cheap request amplifier.
Fix:         Validate in a Pydantic model: probability, confidence, cost, reversibility and weights in [0, 1]; 0 < horizon_hours <= 720; 1 to 5 rows each (matching README.md:166-167); reject NaN; split row parsing into a helper to bring complexity under 15.
Gate:        Route tests for negative weight, horizon 0 and six rows, each expecting a 422-style inline error; cogcx gate at 15.
Verdict:     CONFIRMED
```

```
ID:          F-165   (origin F-S09-15)
Lens:        L6 performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:363-518
Evidence:
               @router.post("/scenario/{scenario_id}/submit", response_class=HTMLResponse)
               async def training_scenario_submit(
Issue:       training_scenario_submit has cognitive complexity 40 and _start_scenario 17 (cogcx_run.txt:4, :21), and the level-up loop at :470-487 is duplicated verbatim at :619-636.
Impact:      The four integrity defects above (F-S09-01, -02, -03, -04) all sit in this function, and coverage is 70% with the answer-validation and award branches uncovered (pytest.txt:118: 406-429, 448-457).
Fix:         Extract `_parse_completed(...)`, `_score_objectives(...)`, `_award(...)` and a shared `_apply_level_ups(progress)` used by both routes.
Gate:        cogcx gate at 15 on this file; unit tests on each extracted helper.
Verdict:     CONFIRMED
```

```
ID:          F-166   (origin F-S09-16)
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_web_routes_extended.py:84-100, 558-611
Evidence:
               assert resp.status_code in (200, 403)
               assert resp.status_code in (200, 404)
               assert submit_resp.status_code == 200
Issue:       The training and decision route tests assert status codes only, accept either success or failure codes, skip when result_id cannot be scraped (:578-579), and the "idempotent" tutorial test never compares points.
Impact:      None of F-S09-01 to F-S09-06 or F-S09-13 would fail a test; the suite reports training as covered when the scoring path is not.
Fix:         Assert on progress.total_points, scenarios_passed and the rendered score after each call, and pin start to 200 for a Level 1 scenario.
Gate:        Ruff or a custom check forbidding `status_code in (` tuples with both 2xx and 4xx in tests.
Verdict:     CONFIRMED
```

```
ID:          F-167   (origin F-S09-18)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:298-304; spectre/web/templates/partials/training_dashboard.html:197-198
Evidence:
               and see what they do, but no points are awarded and the attempt counter
               is not incremented.  The row is deleted when the operator resets or submits.
Issue:       Submitting an explore run does not delete the row; it is completed with `passed` set (training.py:493), then listed in Recent Activity as PASS or FAIL beside scored attempts, and counted in the detail view's "Attempt #" (training.py:198-209 has no `scored` filter, unlike :253 and :350).
Impact:      An operator's activity history shows exploration runs as passes, and the attempt number shown before starting disagrees with the one recorded.
Fix:         Delete or mark explore rows on submit, filter `scored == True` in recent results and in the detail count, and correct the docstring.
Gate:        Integration test: explore then submit, assert the dashboard shows no PASS row.
Verdict:     CONFIRMED
```

```
ID:          F-168   (origin F-S09-19)
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:368-391, 491
Evidence:
               completed_ids: list[str] = json.loads(objectives_completed)
               except (ValueError, TypeError):
               completed_ids = []
Issue:       A JSON value that parses but is not a list of strings (`5`, `[{}]`) raises TypeError in the loop at :405-406 (500), time_taken_minutes accepts negative, NaN and infinity and is stored unchecked, and time_limit_minutes is never enforced server-side (the timer and elapsed time exist only for timed scenarios in client script at training_scenario_active.html:195-215).
Impact:      "Submit within the 20-minute time limit" objectives are self-certified, timed challenges are untimed, and a NaN may fail the NOT NULL Float column on SQLite (TBC: confirm sqlite stores NaN as NULL).
Fix:         Validate the list shape, bound time_taken to [0, horizon], compute elapsed server-side from cr.started_at, and fail timed objectives when elapsed exceeds time_limit_minutes.
Gate:        Route tests for `objectives_completed=5`, negative time, and an over-limit submission.
Verdict:     CONFIRMED
```

```
ID:          F-169   (origin F-S09-22)
Lens:        L7 design and structure
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/training/config/gamification.yaml:44-116, 130-198
Evidence:
               - action_id: efficiency_bonus
               label: "Complete scenario with minimal ΔV (< threshold)"
               base_points: 100
Issue:       Six of nine point actions (tutorial_step_complete, tutorial_complete, manoeuvre_planned_valid, manoeuvre_planned_optimal, threat_assessed_timed, efficiency_bonus) and efficiency_bonus_dv_threshold_ms are never used; `scenario:` unlock entries are ignored (scenarios_for_level uses level_required), level 2 "unlocks" observer_03, _04 and _05 that require level 3 (scenarios.yaml:480, :549, :614), and challenge:instructor_degraded_sensors and challenge:instructor_multi_threat do not exist.
Impact:      Anyone tuning the YAML ("Edit this file to tune points ... without changing any Python code", :2-3) changes nothing for most entries, and the Level 2 and Level 6 level-up banners announce content that is locked or absent.
Fix:         Remove or wire the unused actions, derive scenario availability from one source, and add a load-time check that every `scenario:` and `challenge:` unlock names an existing scenario at a consistent level.
Gate:        Unit test cross-checking unlocks against load_scenarios().
Verdict:     CONFIRMED
```

```
ID:          F-170   (origin F-S09-27)
Lens:        L10 build, config and deploy
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/static/spectre-theme.css:18-19
Evidence:
               @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');
               @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');
Issue:       The loaded theme stylesheet fetches fonts from Google on every console load, which is why the CSP allows fonts.googleapis.com and fonts.gstatic.com (app.py:273-274); the same imports appear in the unused copy and splash.html:8.
Impact:      A sovereign defence console beacons each operator's IP and access times to a third party, and an air-gapped deployment renders with fallback fonts; Referrer-Policy no-referrer limits but does not remove the leak.
Fix:         Self-host the two font families under /static as the app.py comment already proposes, delete the @import lines, and drop the Google hosts from the CSP.
Gate:        Test that no file under spectre/web/static contains `https://` in an @import or url().
Verdict:     CONFIRMED
```

```
ID:          F-171   (origin F-S09-32)
Lens:        L11 numerical and scientific correctness
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/tle_clustering/conftest.py:30; tests/integration/test_tle_clustering_pipeline.py:35
Evidence:
               We use a fixed epoch '26091.5' (2026-04-01 12:00:00 UTC, approximately) and
Issue:       Every clustering test TLE shares one epoch and RAAN values away from 0/360, with no near-equatorial GEO case (where RAAN is ill-defined), so no test can detect F-S09-10 or F-S09-11.
Impact:      The suite is green while the method mis-clusters the realistic input the README describes.
Fix:         Add cases for RAAN seam, multi-epoch LEO sets generated by SGP4 propagation, and i < 0.1° GEO sets.
Gate:        Those tests.
Verdict:     CONFIRMED
```

```
ID:          F-172   (origin F-S09-38)
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/training_debrief.html:77-90; spectre/web/routes/training.py:494
Evidence:
               letter-spacing:0.05em; margin-bottom:0.25rem">Skill Points Earned</div>
Issue:       The debrief lists per-axis objective points under "Skill Points Earned", but those values are only stored on the result row (training.py:494); the operator's axis totals are changed by the award actions' fixed weights (training.py:442-457), which may credit axes the operator did not exercise.
Impact:      Operators are told they earned, for example, +60 Efficiency when their efficiency axis rose by a different amount or not at all, so the dashboard and debrief disagree.
Fix:         Either add axis_scores to progress.axis_points or relabel the panel "Objective points by axis" and show the actual axis deltas separately.
Gate:        Integration test comparing debrief axis figures with the change in progress.axis_points.
Verdict:     CONFIRMED
```

```
ID:          F-173   (origin F-S10-01)
Lens:        L11 numerical and scientific correctness (documentation of solver capability)
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    docs/intercept_engine.md:126
Evidence:
               The Lambert solver in `transfers.py` uses the universal variable (Battin) formulation. It iterates on the universal variable `x` using Halley's method until the desired time of flight is matched. The solution is always computed for the prograde direction; retrograde and multi-revolution solutions are available via `lambert.py`.
Issue:       Three operator-facing documents (this line; docs/architecture.md:48-49; README.md:309-310) attribute a Battin/Halley Lambert solver to `transfers.py`, which contains no Lambert code, and claim multi-revolution solutions in `lambert.py`, whose module docstring (lines 13-16) says it solves single-revolution only and rejects multi-revolution transfers; `solve_lambert`'s own docstring at spectre/astro/lambert.py:53 still reads "Solve Lambert's problem using Izzo's algorithm."
Impact:      An analyst plans a multi-revolution GEO phasing intercept believing the tool supports it, receives a `LambertConvergenceError` or a single-revolution answer, and the docs give no hint that the capability was never there; the Izzo attribution repeats the exact false-provenance defect the audit note says was fixed.
Fix:         Rewrite the three passages to "Curtis Algorithm 5.2, universal variables, bracketed bisection on z, single revolution only, multi-revolution rejected"; correct the `solve_lambert` docstring; drop `transfers.py` from every Lambert row.
Gate:        A docs test that greps README.md, docs/architecture.md and docs/intercept_engine.md for "multi-rev", "Halley", "Battin" and "Izzo" and fails, plus a unit test asserting `solve_lambert.__doc__` does not contain "Izzo".
Verdict:     CONFIRMED
```

```
ID:          F-174   (origin F-S10-02)
Lens:        L8 clarity and comments (capability claim)
Severity:    Medium   (reviewer graded High; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1304-1306
Evidence:
               _COAST_ONLY_SOLVERS: dict[InterceptMethod, Callable[..., InterceptSolution]] = {
               InterceptMethod.HOHMANN: hohmann_intercept,
               InterceptMethod.RENDEZVOUS: hohmann_intercept,
Issue:       The engine exposes 25 selectable methods (25 `InterceptMethod` members, spectre/domain/models.py:120-144) but only 23 distinct solvers: RENDEZVOUS runs the Hohmann solver and PROXIMITY runs the same `_lambert_transfer` as LAMBERT (line 1322), while docs/intercept_engine.md:18-19 and spectre/domain/models.py:96-97 describe them as "match position + velocity" and "minimise range to target_distance_m" with distinct outputs; README.md:13 and :146 count "23 methods" but list neither V-bar nor H-bar hops and do list Rendezvous and Proximity.
Impact:      An operator choosing "Rendezvous" gets a Hohmann transfer labelled as a rendezvous solution, with no velocity match at arrival, and a trade-space plot showing two "different" methods that are the same computation.
Fix:         Either implement distinct rendezvous and proximity solvers or remove the two aliases from the method list and the docs, and state the true count (23 solvers, list them) in README.md, docs/intercept_engine.md and docs/architecture.md:107.
Gate:        Unit test asserting each `InterceptMethod` maps to a distinct solver object unless listed in an explicit, documented alias table that the UI labels as such.
Verdict:     CONFIRMED
```

```
ID:          F-175   (origin F-S10-08)
Lens:        L10 build, config and deploy (supply chain)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    .github/workflows/ci.yml:105-107
Evidence:
               curl -sSfL \
               https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_x64.tar.gz \
               | tar -xz -C /usr/local/bin gitleaks
Issue:       The secret-scanning binary is downloaded and executed with no checksum or signature verification, and every action (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `actions/setup-node@v4`) is pinned by mutable tag; the quality job also fetches `npx --yes jscpd@4` at run time (scripts/check-quality.sh:176).
Impact:      A compromised release asset or retagged action executes arbitrary code in CI with the repository checkout and full history (`fetch-depth: 0`).
Fix:         Pin each action to a full commit SHA with the tag in a comment, verify the gitleaks tarball against the published checksums file (`sha256sum -c`), and pin jscpd to an exact version.
Gate:        A CI lint step (or test) that fails on `uses:` lines without a 40-hex SHA and on `curl ... | tar` without a checksum step.
Verdict:     CONFIRMED
```

```
ID:          F-176   (origin F-S10-10)
Lens:        L10 build, config and deploy
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    scripts/verify-container.sh:44-47
Evidence:
               awk '
               /^COPY requirements\.lock \.\/$/ {
               print "COPY .verify-proxy-ca.crt /tmp/ca.crt"
Issue:       The proxy-CA injection matches `COPY requirements.lock ./`, a line no Dockerfile contains (both copy `requirements-runtime.txt`, Dockerfile:42 and Dockerfile.docker-only:55), so nothing is inserted, yet line 53 prints "building with proxy CA trusted"; scripts/simulate-pipeline.sh:96 and :103 carry the same dead pattern and message.
Impact:      Behind a TLS-intercepting proxy the build fails on pip certificate errors while the log claims the CA was trusted, sending the operator down the wrong diagnosis.
Fix:         Match `^COPY requirements-runtime\.txt \./$`, and fail if the generated file is identical to the input.
Gate:        Unit test that runs the awk program against Dockerfile and asserts the output contains `PIP_CERT`.
Verdict:     CONFIRMED
```

```
ID:          F-177   (origin F-S10-11)
Lens:        L1 correctness and edge cases
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    scripts/cognitive_complexity.py:224-230
Evidence:
               for value in node.values:
               # Count each operand's own structure, but never re-count the
               # sequences already charged above.
Issue:       A boolean operator nested exactly one call deep is charged twice: `_boolean_sequences` (lines 238-260) walks into a direct child BoolOp of a non-BoolOp operand, and `_visit_without_boolops` then visits the same node through `generic_visit`, so `if a and g(b or c)` scores 4 while `if a and g(h(b or c))` scores 3 (reproduced by importing the script and calling `measure_source`); the inner `for sub in ast.walk(value)` loop at lines 227-229 does nothing.
Impact:      The meter that gates S3776 on changed code over-reports some functions, so a developer refactors code Sonar would pass, or loses trust in the gate.
Fix:         Make `_boolean_sequences` the only counter (walk every descendant BoolOp once) and have the visitor skip all BoolOp descendants, or the reverse; delete the dead loop.
Gate:        Add `def f(a,b,c):\n if a and g(b or c): pass\n` == 3 to tests/unit/test_cognitive_complexity_meter.py.
Verdict:     CONFIRMED
```

```
ID:          F-178   (origin F-S10-12)
Lens:        L8 clarity and comments (calibration claim)
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    scripts/cognitive_complexity.py:42-44
Evidence:
               Increment of 1 with NO nesting penalty (the structure is already announced):
               elif, else, the else clause of a for/while/try, finally
Issue:       check-quality.sh:109-110 says the tool "computes exactly" because it is calibrated against 16 functions, but none of the 16 contains `finally`, a `try`/`else`, a loop `else` or `match` (checked by walking each function at revision 047a9eb: only lambdas and nested defs occur), and scoring `finally` as +1 (lines 206-207) diverges from the SonarSource Cognitive Complexity specification, which ignores try and finally blocks and increments only catch (TBC, re-verify against the whitepaper section on catch and against sonar-python's CognitiveComplexity visitor).
Impact:      Functions with `finally` or loop/try `else` are scored by uncalibrated rules, so the gate can fail or pass code differently from SonarQube while claiming exactness.
Fix:         Reword the claim to "matches Sonar on 16 calibration functions; finally, try-else, loop-else and match are uncalibrated"; check the finally rule against sonar-python and add calibration cases that exercise each construct.
Gate:        Calibration cases covering each rule in the docstring; a test that fails if a docstring rule has no calibration or unit case.
Verdict:     CONFIRMED
```

```
ID:          F-179   (origin F-S10-13)
Lens:        L10 build, config and deploy (test that can never run)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_deployment_contract.py:795-797
Evidence:
               @pytest.mark.skipif(not _DOCKER_ONLY, reason="python template: manifests ship by design")
               def test_no_recognised_manifest_at_any_depth(self) -> None:
Issue:       TestDockerOnlyContract` runs only inside the docker-only archive, but the packager drops `tests` from that archive (scripts/package-appstore.sh:98-99), so both tests (lines 796 and 813) are skipped everywhere they can execute; the phase 2 run shows exactly these two skips (audit/tools-raw/pytest.txt).
Impact:      The docstring's promise that "the skip is not a hole" is false: the docker-only package's manifest contract is enforced only by the root-level check at package-appstore.sh:200-205 (see F-S10-29).
Fix:         Move these assertions into a repository-side test that builds the docker-only package (as tests/integration/test_packager_gates.py:191 already partly does) and inspects the zip at every depth.
Gate:        A test asserting no test in the suite is unconditionally skipped in both the repository and every package mode.
Verdict:     CONFIRMED
```

```
ID:          F-180   (origin F-S10-14)
Lens:        L8 clarity and comments (test documentation)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    docs/architecture.md:212-213
Evidence:
               Integration tests that require a live network (UDL, GCAT) are guarded by
               `@pytest.mark.integration` and skipped unless `SPECTRE_INTEGRATION_TESTS=1` is set.
Issue:       No test carries the `integration` marker and nothing reads `SPECTRE_INTEGRATION_TESTS`, though pyproject.toml:58 declares the marker; README.md:254 repeats "opt-in network tests", README.md:242 and docs/architecture.md:202 claim "74 parametrised tactical solver cases" while tests/unit/test_tactical.py has 75 plain tests and no `parametrize`, and README.md:373 lists five CI jobs where ci.yml has seven.
Impact:      Readers believe live UDL and GCAT paths are tested on demand when no such test exists, so the network integration paths carry no evidence.
Fix:         Either write the marked network tests or delete the claim and the unused marker; correct the test table from the actual modules.
Gate:        A test that fails when a marker declared in pyproject.toml is used by no test.
Verdict:     CONFIRMED
```

```
ID:          F-181   (origin F-S10-15)
Lens:        L8 clarity and comments (API and units)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    docs/intercept_engine.md:78-82
Evidence:
               | `total_delta_v_km_s` | `float` | Total ΔV magnitude (km/s) |
               | `burns` | `list[BurnResult]` | Per-burn breakdown (see below) |
               | `intercept_range_km` | `float` | Miss distance at arrival epoch (km) |
Issue:       The documented result contract does not match the code: the field is `total_delta_v_m_s` in m/s (spectre/domain/models.py:347), `transfer_time_h` and `location_label` do not exist, burn components are `dv_prograde`, `dv_normal`, `dv_radial` in m/s (models.py:326-329) not `dv_along_track`/`dv_cross_track`, and the documented routes `POST /plan/maneuver/calculate` and `GET /plan/maneuver/tradespace` (lines 99, 107) do not exist (actual `/apply-intercept` at maneuver.py:783 and `/trade-space-data` at maneuver.py:1152).
Impact:      An integrator or analyst reading the doc misreads delta-V by a factor of 1,000 or calls routes that 404.
Fix:         Regenerate the result and route tables from `InterceptResult`, `BurnResult` and the router.
Gate:        A docs test that checks every backticked field name in docs/intercept_engine.md exists on the dataclass and every route exists in `docs/openapi.json`.
Verdict:     CONFIRMED
```

```
ID:          F-182   (origin F-S10-19)
Lens:        L4 contracts and data (configuration contract)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    .env.example:34-35
Evidence:
               # OPTIONAL. Overrides the database. Leave unset to use SQLite inside the
               # resolved data directory. The POSTGRESQL add-on injects this automatically.
Issue:       SQLite does not live in the resolved data directory: `_resolve_database_url` uses `_resolve_sqlite_dir()` (spectre/config/settings.py:164-183), which ignores SPECTRE_DATA_DIR and STORAGE_MOUNT_PATH, and the function's own docstring (settings.py:174) repeats the wrong claim; SPECTRE_SQLITE_DIR, SPECTRE_COOKIE_SECURE (line 263), SPECTRE_DB_POOL_RECYCLE (line 304), SPECTRE_LOG_DIR (line 326) and APPSTORE_DAST_SCAN (line 68) are read but absent from .env.example, and settings.py:38 says placeholders are "shipped in .env.example" although it ships `SECRET_KEY=` blank. Extends O11.
Impact:      An operator who sets SPECTRE_DATA_DIR to a persistent volume expecting the database there loses all users and audit rows on restart, because SQLite stays on the ephemeral container filesystem.
Fix:         Correct .env.example and the docstring to say "SQLite under ./data or SPECTRE_SQLITE_DIR, ephemeral in the container", and list every variable the settings module reads.
Gate:        A test that collects every `os.environ.get("...")` name in spectre/config/settings.py and asserts each appears in .env.example.
Verdict:     CONFIRMED
```

```
ID:          F-183   (origin F-S10-21)
Lens:        L10 build, config and deploy (supply chain)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    scripts/verify-dependency-scan.sh:49-50
Evidence:
               [ -d "$CACHE/src/.git" ] || git clone --depth 1 --quiet "$REPO" "$CACHE/src"
               ( cd "$CACHE/src" && go build -o ../analyzer ./cmd/dependency-scanning )
Issue:       The script clones the upstream analyser at whatever HEAD is current, builds it and runs it, and scripts/package-appstore.sh:331-333 invokes it automatically on every package build whenever a Go toolchain is present; the cache is reused, so the version that runs is whatever HEAD was on first use.
Impact:      Unpinned third-party code executes on the packaging workstation with access to the working tree; results are not reproducible between machines.
Fix:         Pin a tag or commit (`git clone --branch <tag>` then `git checkout <sha>`), verify it, and make the packager call opt-in.
Gate:        A test that fails if a `git clone` in scripts/ has no pinned ref.
Verdict:     CONFIRMED
```

```
ID:          F-184   (origin F-S10-23)
Lens:        L8 clarity and comments (misattributed control)
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    requirements-runtime.in:3-4
Evidence:
               # it is never scanned directly: it must stay a strict, version-identical
               # subset of requirements.txt, and scripts/check-quality.sh asserts that.
Issue:       Four files (this one, Dockerfile:38-39, scripts/package-appstore.sh:125, docs/DEPENDENCY-SCANNING.md:31) name check-quality.sh as the control that keeps the image's lock a subset of the scanned lock, but check-quality.sh contains no such check; it lives in scripts/preflight-gate.py:286-309 and tests/unit/test_deployment_contract.py:239-259.
Impact:      Someone tightening or removing check-quality.sh believes the subset control is preserved or lost in the wrong place.
Fix:         Point the comments at preflight-gate.py and the contract test.
Gate:        Review only; optionally a test that any comment naming `scripts/check-quality.sh asserts` matches text in that script.
Verdict:     CONFIRMED
```

## Low

```
ID:          F-185   (origin F-S00-10)
Lens:        L10 Build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    pyproject.toml:76
Evidence:
               fail_under = 74
Issue:       Three different coverage floors are in force: 74 here, 70 in CI (ci.yml:55) and 80 in scripts/check-quality.sh:18.
Impact:      The CI floor of 70 sits below the declared ratchet, so coverage could fall four points without CI noticing even once the jobs run.
Fix:         Remove `--cov-fail-under=70` from ci.yml so pyproject's ratchet governs.
Gate:        A test asserting ci.yml carries no `--cov-fail-under` or carries the pyproject value.
Verdict:     CONFIRMED
```

```
ID:          F-186   (origin F-S00-11)
Lens:        L10 Build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    audit/tools-raw/ci_master_run_40020299345.txt:9
Evidence:
               fatal: No url found for submodule path 'SPECTRE-1' in .gitmodules
Issue:       SPECTRE-1` is a gitlink (mode 160000) with no `.gitmodules`, so it cannot be initialised and makes every CI checkout's cleanup fail with "No url found for submodule path 'SPECTRE-1'".
Impact:      Noise and a failing git command in every CI job; anyone cloning gets an empty directory.
Fix:         git rm --cached SPECTRE-1` and remove the directory.
Gate:        A test asserting `git ls-files -s` contains no mode 160000 entry.
Verdict:     CONFIRMED
```

```
ID:          F-187   (origin F-S00-13)
Lens:        L3 Security
Severity:    Low
Confidence:  Medium
Epistemics:  fact
Location:    spectre/web/static/hammer.min.js:1
Evidence:
               /*! Hammer.JS - v2.0.7 - 2016-04-22
Issue:       Four vendored JavaScript libraries (Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.JS 2.0.7 from 2016, htmx 1.9.12) are covered by no dependency scanner; pip-audit sees Python only.
Impact:      An advisory against a vendored library would never surface; Hammer.JS is unmaintained.
Fix:         Record the vendored versions in a manifest and scan them with an SCA tool that reads JS (for example OSV against a package-lock or an SBOM).
Gate:        A CI SCA step over the vendored manifest.
Verdict:     CONFIRMED
```

```
ID:          F-188   (origin F-S00-15)
Lens:        L8 Clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_planning_state.py:38
Evidence:
               clear_session_state("nobody")  # should not raise
Issue:       No test follows the required `test_should_<expected>_when_<condition>` convention (0 of 1,389).
Impact:      Consistency only; the existing descriptive names are mostly readable.
Fix:         Adopt the convention for new tests, or amend the standard to the sentence style in use.
Gate:        A naming lint over `tests/` once the standard is settled.
Verdict:     CONFIRMED
```

```
ID:          F-189   (origin F-S01-14)
Lens:        L8 clarity and comments
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/lambert.py:208-211
Evidence:
               # The single-revolution solution lies below the parabolic limit z = 4*pi^2.
               # At that limit the time of flight diverges; above it the transfer needs a
               # full extra revolution, which this solver does not model.
Issue:       z = 0 is the parabolic case. z = 4π² is the single-revolution elliptic boundary. The constant name and the operator-facing error message at :285-287 ("exceeds the parabolic limit") misname it.
Impact:      Misleading diagnostics. Together with F-S01-04, the message describes a condition that does not occur.
Fix:         Rename to _Z_SINGLE_REV_LIMIT and correct the comment and message.
Gate:        n/a (review).
Verdict:     CONFIRMED
```

```
ID:          F-190   (origin F-S01-15)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/lambert.py:131
Evidence:
               # Solve via Stumpff functions with Newton–Raphson iteration.
Issue:       The solver is bisection (:308-316), as _solve_z's own docstring states at :266.
Impact:      Misleading comment.
Fix:         Change the comment to "bisection".
Gate:        n/a
Verdict:     CONFIRMED
```

```
ID:          F-191   (origin F-S01-17)
Lens:        L11 numerical and scientific correctness
Severity:    Low
Confidence:  High
Epistemics:  inference
Location:    spectre/astro/propagator.py:213-216
Evidence:
               if circular and equatorial:
               # True longitude: angle from the x-axis to the position vector.
               argp = 0.0
Issue:       For a retrograde circular equatorial orbit (inc = 180 deg), ta = atan2(y, x), but keplerian_to_state with i = 180, Ω = 0 and ω = 0 maps (cos ta, sin ta) to (cos ta, −sin ta). The round trip mirrors the position, unlike the elliptical branch, which handles retrograde at :228-229. The docstring at :196 says "every case".
Impact:      The position error is up to 2r for that orbit class. It is rare operationally.
Fix:         If h[2] < 0 in the circular-equatorial branch, use ta = 360 − true longitude.
Gate:        Add an inc = 180 circular case to tests/unit/test_orbital_units_and_degeneracies.py:46-54.
Verdict:     CONFIRMED
```

```
ID:          F-192   (origin F-S01-20)
Lens:        L2 error handling and failure modes
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/transfers.py:66-80
Evidence:
               rb: Intermediate apoapsis radius (km) — must be > max(r1, r2).
Issue:       The precondition is documented but not enforced. With rb below r2 the formulae still return numbers for a geometrically different manoeuvre, and r or rb ≤ 0 raises an unexplained math domain error. bielliptic_intercept's default rb = 1.5·max(r1, r2) (maneuvers.py:238) also means bi-elliptic is always dearer than Hohmann unless r2/r1 > 11.94 (Vallado section 6.3.2), which is not flagged.
Impact:      Silent wrong transfer for a bad rb.
Fix:         Raise ValueError if rb <= max(r1, r2) or any radius is ≤ R_EARTH.
Gate:        Test that pytest.raises(ValueError) for rb < r2.
Verdict:     CONFIRMED
```

```
ID:          F-193   (origin F-S01-22)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/config/constants.py:8-18
Evidence:
               SPEED_UNIT: str = "m/s"
Issue:       PROP_STEP_SEC, ANALYSIS_STEP_SEC, DISTANCE_UNIT, SPEED_UNIT, ANGLE_UNIT, COORD_FRAME and TIME_SYSTEM are unused. COORD_FRAME = "ICRF" contradicts the TEME states (propagator.py:33), and SPEED_UNIT "m/s" contradicts the km/s astro layer.
Impact:      Misleading "documentation" constants.
Fix:         Delete them, or set them to TEME and km/s and use them.
Gate:        vulture in CI.
Verdict:     CONFIRMED
```

```
ID:          F-194   (origin F-S01-23)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/maneuvers.py:1031
Evidence:
               altitude = sv.r_mag - 6378.137
Issue:       There are duplicated or unsourced constants. The R_EARTH literal is inlined here. _GEO_BAND_ALT and _GEO_TOL_ALT (constants.py:21-22) are unused. scripts/build-hrr-default.py:42 has `_SIDEREAL_DAY_S = 86164.0905` against SIDEREAL_DAY = 86164.1. A mean radius of 6371.0 is used at spectre/domain/decision.py:34 and spectre/astro/photometry.py:38. tactical.py:1057 hardcodes 35786. None of MU_EARTH, R_EARTH or J2_EARTH carries a source citation (values match WGS-84/EGM-96: 398600.4418, 6378.137, 1.08263e-3).
Impact:      Drift risk; the R_EARTH values are inconsistent across modules (equatorial versus mean).
Fix:         Import R_EARTH, delete the unused constants, and add source comments.
Gate:        A grep test forbidding `6378\.137|398600` outside constants.py.
Verdict:     CONFIRMED
```

```
ID:          F-195   (origin F-S01-24)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/constants.py:20
Evidence:
               _MEO_MAX_ALT: float = 35386.0   # GEO lower bound − 400 km
Issue:       35,386 is the GEO lower bound (35,786 − 400), not the GEO lower bound minus 400. Separately, the regimes_compatible docstring (:52-56) says HEO and GTO are allowed "against any regime they physically cross", but :60 allows them against every regime, including DEEP and OTHER.
Impact:      Misleading comments on gating logic.
Fix:         Correct both comments, or implement the crossing check.
Gate:        n/a
Verdict:     CONFIRMED
```

```
ID:          F-196   (origin F-S02-18)
Lens:        L11 numerical and scientific correctness
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/tactical.py:594-619
Evidence:
               # x(t) = (Δvx / n) sin(nt)
               dv_radial = desired_miss_km * n / abs(sin_nt)
               miss_distance_km=desired_miss_km,
Issue:       Each strategy sizes the burn on one displacement component and ignores the coupled component (a radial burn also produces y = -2Δvx/n(1 - cos nt)), the reported miss distance echoes the input instead of the achieved displacement, and no encounter geometry (relative velocity, B-plane) is used, so "minimum-ΔV" means the cheapest of three single-axis approximations.
Impact:      COLA and formation plans quote a miss distance that is not the computed one and may not lie in the direction that matters for the conjunction.
Fix:         Return the achieved |r(TCA)| from the full CW solution and document that the result is not encounter-plane aware.
Gate:        Test that miss_distance_km equals the norm of `_cw_propagate` displacement at TCA.
Verdict:     CONFIRMED
```

```
ID:          F-197   (origin F-S02-21)
Lens:        L4 contracts and data
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:2095-2099
Evidence:
               if time_per_hop_s is None:
               time_per_hop_s = T_orbit / 2.0
               dv_per_hop = n * hop_distance_km / 2.0
Issue:       A caller-supplied time_per_hop_s changes total_time_s but not ΔV, although the n·d/4 per-burn result holds only at T/2 (y = -2v/n(1 - cos nt)); the V-bar model was checked by hand and is correct at T/2 only.
Impact:      Any non-default hop time returns an inconsistent ΔV; neither hop solver has a unit test.
Fix:         Compute ΔV from 2(1 - cos nt)/n at the requested time, or reject non-default times.
Gate:        Unit tests pinning V-bar ΔV to n·d/2 at T/2 and to the general form elsewhere.
Verdict:     CONFIRMED
```

```
ID:          F-198   (origin F-S02-24)
Lens:        L8 clarity and comments
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:1433-1438
Evidence:
               solutions for a co-orbital GEO case it underestimated the cost by
               between 1.3x and 121x, and for equal radii its Hohmann reference
               It is retained as a cheap upper-bound sketch for unequal radii. For an
Issue:       A routine documented as underestimating cost is then described as an upper bound, and it has no production caller (also cw_combined and graveyard_transfer).
Impact:      A future caller trusting "upper bound" would under-cost intercepts.
Fix:         Delete the three dead routines or correct the wording to "lower-bound sketch".
Gate:        vulture in CI at 60% confidence for spectre/astro.
Verdict:     CONFIRMED
```

```
ID:          F-199   (origin F-S02-29)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/cw_geometry.py:28, 76-77, 463-468
Evidence:
               - All numeric inputs are validated to be finite and within operational bounds.
               # Hard cap on initial separation (km).
               _RANGE_HARD_CAP_KM: float = 100_000.0
Issue:       The "hard cap" only logs a warning and computation continues; tof_s and coast_s have no upper bound, so "within operational bounds" is overstated.
Impact:      A 100,000 km separation produces a chart with cw_valid False but no refusal.
Fix:         Raise RelativeGeometryError above the cap and add a tof ceiling, or rename to a warning threshold.
Gate:        Unit test that separation above the cap raises.
Verdict:     CONFIRMED
```

```
ID:          F-200   (origin F-S02-30)
Lens:        L9 observability
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/cw_geometry.py:347-351, 473-475
Evidence:
               if not cw_valid:
               for note in validity_notes:
               logger.warning("cw_geometry validity: %s", note)
Issue:       The time-of-flight note does not clear cw_valid, so when it is the only problem it is never logged, contrary to the module docstring (claim 41).
Impact:      Long-TOF CW breakdown leaves no WARNING record.
Fix:         Log every note other than the "valid" one regardless of cw_valid.
Gate:        caplog test for tof_hours above 6 h.
Verdict:     CONFIRMED
```

```
ID:          F-201   (origin F-S02-31)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/geometry.py:1-5
Evidence:
               """Pure-math geometry helpers for intercept planning.
Issue:       None of the module's functions is called from production code.
Impact:      Maintained, tested code that nothing uses; a second SEZ implementation could drift from any other.
Fix:         Delete it, or route ground-station look-angle code through it.
Gate:        vulture in CI.
Verdict:     CONFIRMED
```

```
ID:          F-202   (origin F-S02-32)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_geometry.py:86-87
Evidence:
               These tests define the behaviour of the *correct* SEZ implementation
               (Phase 2.2). They are expected to fail on the current placeholder stub.
Issue:       The implementation is no longer a stub and the tests pass, so the docstring is stale.
Impact:      Misleads a reader about the state of the code.
Fix:         Remove the sentence.
Gate:        n/a
Verdict:     CONFIRMED
```

```
ID:          F-203   (origin F-S02-33)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tactical.py:96; spectre/astro/maneuvers.py:1031
Evidence:
               if far_apsis <= R_EARTH + 100.0:
               altitude = sv.r_mag - 6378.137
Issue:       The 100 km atmosphere floor has no stated source (the Kármán line is a definition, not a flyable perigee; practical floors are nearer 150 to 200 km), maneuvers.py re-types R_EARTH as a literal, tests/unit/test_tactical.py:37 re-types GEO_RADIUS, and `_cos_nt`, `_sin_nt`, `_T` (tactical.py:592, 1173, 1554, 1780) are assigned and unused.
Impact:      Constants can drift apart; a 100 km perigee phasing plan is accepted although it would decay within a revolution or two (inference).
Fix:         Name and source a MIN_PERIGEE_ALT_KM constant, import R_EARTH and GEO_RADIUS, delete unused locals.
Gate:        Grep check in CI for 6378.137 outside constants.py.
Verdict:     CONFIRMED
```

```
ID:          F-204   (origin F-S02-34)
Lens:        L11 numerical and scientific correctness
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/tactical.py:735-740
Evidence:
               graveyard_altitude_km: float = 300.0,
               Standard end-of-life disposal: Hohmann transfer to GEO + 300 km.
Issue:       The IADC re-orbit guideline is 235 km plus 1,000·C_R·A/m, not a fixed 300 km, and the function has no production caller.
Impact:      Minor; a fixed 300 km presented as "standard".
Fix:         Cite IADC and compute the minimum from C_R and A/m, or delete the dead routine.
Gate:        n/a
Verdict:     CONFIRMED
```

```
ID:          F-205   (origin F-S03-17)
Lens:        L2 error handling and failure modes
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:760-761
Evidence:
               except Exception:  # noqa: BLE001
               return False
Issue:       A record dropped on malformed provenance (and a record dropped as a duplicate epoch, line 787) is not counted anywhere on PolAnalysis. The noqa carries no justification (audit/tools-raw/suppressions.md:23).
Impact:      tle_count shrinks without explanation. The operator cannot tell that element sets were discarded before detection.
Fix:         Count dropped_on_provenance and dropped_duplicate_epoch and render them with the other detection audit counters (spectre/web/templates/partials/pol_results.html:628-631). Narrow the except to (TypeError, ValueError).
Gate:        Extend tests/unit/test_pattern_of_life.py:199-233 to assert the counter.
Verdict:     CONFIRMED
```

```
ID:          F-206   (origin F-S03-18)
Lens:        L4 contracts and data
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:765-768
Evidence:
               def parse_tle_history(
               tle_text: str,
               satno: int | None = None,
Issue:       The satno parameter is accepted but never used. Element sets for other catalogue numbers in the block are parsed into the history, which is then differenced as one object.
Impact:      A mixed block (a provider returning a parent and a debris piece) produces large spurious ΔV between different objects.
Fix:         Reject or count pairs whose line 1 catalogue number (columns 3-7) differs from satno.
Gate:        A unit test with two catalogue numbers interleaved asserting only the requested one survives.
Verdict:     CONFIRMED
```

```
ID:          F-207   (origin F-S03-19)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:349-351
Evidence:
               """Greenwich Apparent Sidereal Time (degrees) at *epoch*."""
               return (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0
Issue:       The formula is the GMST of Meeus, Astronomical Algorithms, eq. 12.4, without the T² term. It is not apparent sidereal time. Hand check: at J2000 it returns 280.46061837 deg, which matches Meeus. GMST is in fact the right angle for TEME mean longitude, so only the docstring is wrong. UTC is used as UT1 (|DUT1| < 0.9 s, under 0.004 deg).
Impact:      Misleads a maintainer into "fixing" it with a nutation term, which would be wrong for TEME.
Fix:         Rename to _gmst_deg and correct the docstring, citing Meeus 12.4.
Gate:        A unit test pinning GMST at a published epoch (Vallado Example 3-5) to 1e-4 deg.
Verdict:     CONFIRMED
```

```
ID:          F-208   (origin F-S03-20)
Lens:        L11 numerical and scientific correctness
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/pattern_of_life.py:363-373
Evidence:
               n_rad_min = sat.no_kozai          # rad/min
               sma       = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
               alt_km     = sma - R_EARTH
Issue:       The semi-major axis comes from the Kozai mean motion with the WGS84 μ, while SGP4 initialised the set with WGS72 and an un-Kozai'd (Brouwer) mean motion. The SGP4 del term is 1.5·J2·(3cos²i - 1)/(2·ak²) to first order, so a differs by up to about 6 km at i=0 and -3 km at sun-synchronous inclination (hand estimate).
Impact:      The "Altitude ... current mean" card is off by a few km. Successive differences cancel at constant inclination, so detection is mostly unaffected.
Fix:         Use sat.no_unkozai and the WGS72 constants for the absolute figure, or label it "Kozai mean".
Gate:        A unit test comparing alt_km with an SGP4 period-averaged radius for a reference TLE.
Verdict:     CONFIRMED
```

```
ID:          F-209   (origin F-S03-21)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:672-673
Evidence:
               dist       = mean_rate * dur
               # Use signed raw longitude difference for distance (handles 180° wrap)
Issue:       The comment describes a longitude difference, but the code integrates the mean rate.
Impact:      A maintainer assumes the wrap is handled from longitudes. A phase that brackets a manoeuvre misstates the distance.
Fix:         Either compute the wrapped _angle_diff(start_lon, end_lon) or correct the comment.
Gate:        A drift phase unit test asserting distance across the antimeridian.
Verdict:     CONFIRMED
```

```
ID:          F-210   (origin F-S03-22)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/pol_results.html:328
Evidence:
               {{ stat_card("Drift Rate", dr | round(4) | abs ~ "°/d " ~ ("→E" if dr > 0.005 else ("←W" if dr < -0.005 else "—SK")),
Issue:       The template hard-codes a 0.005 deg/day East/West cut, while _DRIFT_STATIONARY is 0.05 (spectre/astro/pattern_of_life.py:111). Both thresholds are untraced.
Impact:      The same object shows "←W" on the card and "STATIONARY" in the phase log.
Fix:         Pass _DRIFT_STATIONARY through the view and cite or label it as tuned.
Gate:        A template test rendering dr=0.01 and asserting the card and phase agree.
Verdict:     CONFIRMED
```

```
ID:          F-211   (origin F-S03-23)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:844-847
Evidence:
               raan_j2  = _j2_raan_rate(rp)  * gap
               d_raan   = _angle_diff(rp.raan_deg + raan_j2, rc.raan_deg)
Issue:       This duplicates spectre/astro/dv_estimation.py:414-441 in closed form. dv_estimation.py:450-452 states that the closed form differs from SGP4's own rate by enough to put 38 m/s of phantom plane change on a 15-day gap. The resulting fields have no consumer.
Impact:      Dead and known-inaccurate fields invite reuse.
Fix:         Delete the fields and the duplicate rate functions, or source them from secular_rates_deg_day.
Gate:        A vulture check in CI (audit/tools-raw/vulture.txt:57-58 already lists them).
Verdict:     CONFIRMED
```

```
ID:          F-212   (origin F-S03-24)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/pattern_of_life.py:1015-1016
Evidence:
               chart_lons      = [round(r.geo_longitude_deg, 3) if r.geo_longitude_deg is not None else 0 for r in cr]
Issue:       A missing longitude is plotted as 0 deg, a real longitude, and pyright flags the types (audit/tools-raw/pyright.txt:3,7).
Impact:      A mixed-regime history draws false points at 0 deg E.
Fix:         Emit None and let the chart skip gaps.
Gate:        Pyright in CI.
Verdict:     CONFIRMED
```

```
ID:          F-213   (origin F-S03-25)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tle_preprocessing.py:271-273
Evidence:
               total_reps_out = objects_clustered - objects_fallback + (1 if objects_fallback > 0 else 0)
               # Simpler: count how many entries made it into reduced_cache.
               total_reps_out = len(reduced_cache)
Issue:       Dead assignment, overwritten on the next line.
Impact:      Confuses the reader about which count is authoritative.
Fix:         Delete line 271.
Gate:        ruff F841-style or a pylint redefined-variable check.
Verdict:     CONFIRMED
```

```
ID:          F-214   (origin F-S03-26)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/notso.py:188-189
Evidence:
               "%m/%d/%Y %H:%M:%S",
               "%m/%d/%Y %H:%M",
Issue:       Slash dates are parsed US-order only. A UK or NATO-style 03/04/2026 becomes 4 March with no ambiguity flag. Military date-time groups ("141200Z MAR 25") are not supported at all.
Impact:      A day-month swap shifts the NOTSO window by up to 11 months without notice.
Fix:         Reject ambiguous slash dates where both fields are 12 or less, or flag them, and add a date-time group parser.
Gate:        Unit tests for 03/04/2026 and a date-time group.
Verdict:     CONFIRMED
```

```
ID:          F-215   (origin F-S03-28)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/tle_preprocessing.py:200-241
Evidence:
               clusters_found=0, representatives_out=1,
               clusters_found=n_clusters, representatives_out=0,
Issue:       The exception path reports representatives_out=1 although nothing is written to reduced_cache. The no-cache path reports 0, contradicting "Always 1" (line 53). Neither path increments objects_fallback despite fallback=True.
Impact:      The sweep summary undercounts fallbacks. An object left with no TLE at all is not surfaced as such.
Fix:         Derive aggregate counters from obj_summaries, and set representatives_out from whether reduced_cache gained the key.
Gate:        Unit tests for both branches (currently uncovered: audit/tools-raw/pytest.txt:71, 192-206, 234-243).
Verdict:     CONFIRMED
```

```
ID:          F-216   (origin F-S03-31)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/notso.py:228-231
Evidence:
               if any(w in low for w in ("test", "testing", "calibration", "demonstration")):
               return NOTSOType.TEST
               if any(w in low for w in ("manoeuv", "maneuv", "thruster", "station keep", "stationkeep",
Issue:       Substring keywords over the whole message when there is no TYPE field: "test" matches "latest" and "contest", and "lower" matches "follower". TEST is checked before MANOEUVRE.
Impact:      notso_without_detection_types is misreported. This affects display only.
Fix:         Use word-boundary regexes and prefer the TYPE field.
Gate:        Unit test for "latest manoeuvre plan" giving MANOEUVRE.
Verdict:     CONFIRMED
```

```
ID:          F-217   (origin F-S03-33)
Lens:        L1 correctness and edge cases (tests)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_notso.py:81-163
Evidence:
               assert dt is not None  # format may not match exactly but shouldn't crash
               assert len(msgs) >= 2
Issue:       Weak assertions. The date test does not check the value, and the split test allows any count of 2 or more.
Impact:      Regressions in date parsing and splitting pass, and F-S03-09 is hidden.
Fix:         Assert exact datetimes and exact message counts.
Gate:        Mutation testing on _parse_dt and _split_messages.
Verdict:     CONFIRMED
```

```
ID:          F-218   (origin F-S03-35)
Lens:        L1 correctness and edge cases (tests)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_tle_filter.py:247-249
Evidence:
               if len(flags) >= 2:
               epochs = [f.epoch for f in flags]
               assert epochs == sorted(epochs, reverse=True)
Issue:       A conditional assertion can pass vacuously.
Impact:      The sort order can regress unnoticed if the flag count drops.
Fix:         Assert the flag count first, then the order.
Gate:        A lint rule against assertions inside if blocks in tests (for example flake8-pytest-style PT017-like).
Verdict:     CONFIRMED
```

```
ID:          F-219   (origin F-S04-10)
Lens:        L11 numerical and scientific correctness
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:603-605; spectre/web/templates/partials/pol_mc_results.html:96
Evidence:
               centroid  = pos_cloud.mean(axis=0)
               dists     = np.linalg.norm(pos_cloud - centroid, axis=1)
               pos_3s    = float(np.percentile(dists, 99.7))
Issue:       The "3-σ radius" is the 99.7th percentile of 3D distance, which is not 3σ in three dimensions (a 3σ sphere holds about 97% of a 3D Gaussian), and with the default 500 samples it rests on about 1.5 points beyond it, yet it is displayed to 0.1 km.
Impact:      The headline uncertainty radius is a noisy extreme-order statistic labelled as a sigma; it fluctuates materially with seed and sample count.
Fix:         Report the RIC covariance and the 3σ ellipsoid semi-axes, or rename to "99.7th percentile distance" with a bootstrap interval; round to the supported precision.
Gate:        Unit test on a synthetic isotropic Gaussian cloud comparing the reported radius with the analytic value.
Verdict:     CONFIRMED
```

```
ID:          F-220   (origin F-S04-16)
Lens:        L11 numerical and scientific correctness
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:361-366
Evidence:
               half = 3.0 * hypothesis.delta_v_magnitude_1sigma_km_s
               dv_mags = rng.uniform(
               hypothesis.delta_v_magnitude_km_s - half,
Issue:       A uniform distribution of half-width 3σ has standard deviation √3·σ ≈ 1.73σ, so the "1sigma" input is not the sample sigma in uniform mode.
Impact:      Uniform-mode dispersion bands are 73% wider than requested.
Fix:         Use half-width `math.sqrt(3) * sigma`, or document the 3σ bound semantics.
Gate:        Test that `np.std` of uniform samples is within 5% of the requested sigma.
Verdict:     CONFIRMED
```

```
ID:          F-221   (origin F-S04-17)
Lens:        L6 performance and complexity
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/astro/monte_carlo.py:20-21
Evidence:
               - Concurrency: ThreadPoolExecutor (scipy/NumPy releases the GIL; no Windows
               spawn restrictions).
Issue:       solve_ivp RK45 steps in Python and calls a Python right-hand side that builds small NumPy arrays, so the GIL is held for most of each sample and threads give little speedup (about 9 s per 50-sample 6 h test, audit/tools-raw/pytest.txt:132-135).
Impact:      2000-sample 48 h runs requested from the web route can occupy an executor thread for minutes.
Fix:         Vectorise the ensemble into one ODE or use a process pool; correct the docstring.
Gate:        Benchmark test with a wall-time budget.
Verdict:     CONFIRMED
```

```
ID:          F-222   (origin F-S04-18)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/monte_carlo.py:284; spectre/astro/monte_carlo.py:320-322; spectre/astro/photometry.py:13
Evidence:
               bstar : B* parameter from TLE (used for regime check only; drag uses bc)
               """Compute (sma_km, ecc, inc_deg, raan_deg, argp_deg, ta_deg) from state.
               4. Compute per-epoch residuals; run a two-sample Student's t-test on a
Issue:       Three docstrings misdescribe their code: `bstar` is never read in `_j2_drag_ode`, `_state_to_keplerian` returns three values not six, and the photometry test is Welch's, not Student's.
Impact:      Reviewers and operators are misled about the model.
Fix:         Correct the docstrings; drop the unused `bstar` argument.
Gate:        Review checklist; ruff ARG001 on the ODE argument.
Verdict:     CONFIRMED
```

```
ID:          F-223   (origin F-S04-19)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/dv_estimation.py:66-69; spectre/astro/dv_estimation.py:429; spectre/astro/dv_estimation.py:729
Evidence:
               A second, independent estimator cross-checks the first. Velocity differencing
               doubled it. On a 550 km, 53° orbit the rate is +3.10°/day, not −3.10.
               """Golden-section refine of the closest approach, one coarse step either side.
Issue:       The module docstring describes the epoch-swept estimator twice (lines 37-43 and 66-71), the second time as the "second" estimator after calling it the headline; the quoted 3.10°/day does not match the formula (hand: +3.02°/day at a = 6928.137 km, +3.05 at 15.1 rev/day); and the refine is ternary, not golden-section.
Impact:      Minor confusion over which estimator is primary and a wrong reference value for anyone checking by hand.
Fix:         Delete the duplicated paragraph, restate the rate as about +3.0°/day, rename to ternary search.
Gate:        Review.
Verdict:     CONFIRMED
```

```
ID:          F-224   (origin F-S04-21)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/photometry.py:713-714
Evidence:
               epoch_str_clean = epoch_str.rstrip("Z")
               epoch = datetime.fromisoformat(epoch_str_clean).replace(tzinfo=UTC)
Issue:       .replace(tzinfo=UTC)` overwrites an explicit offset such as "+01:00" instead of converting it, shifting that epoch by the offset.
Impact:      Mis-timed observations near the window boundaries and in manoeuvre correlation (±48 h).
Fix:         Use `dt.astimezone(UTC)` when `dt.tzinfo` is set, `replace` only when naive.
Gate:        Parser test with an offset epoch.
Verdict:     CONFIRMED
```

```
ID:          F-225   (origin F-S04-24)
Lens:        L2 error handling and failure modes
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/dv_estimation.py:797-799
Evidence:
               # BLE001: SGP4 can diverge; that sample is simply unusable.
               except Exception:  # noqa: BLE001
               return None
Issue:       TLEOrbit.propagate` raises RuntimeError on SGP4 error (spectre/astro/propagator.py:93-94), so the broad catch also hides programming errors, and partial sample loss is not counted on the estimate.
Impact:      A swept estimate from a handful of surviving samples looks identical to one from 65.
Fix:         Catch RuntimeError only; record the sample count in the notes.
Gate:        ruff BLE001 without suppression.
Verdict:     CONFIRMED
```

```
ID:          F-226   (origin F-S04-25)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/astro/dv_estimation.py:120-121; spectre/web/templates/partials/pol_manoeuvre_detail.html:156
Evidence:
               #: Scale factor on the robust spread when setting the reporting floor.
               _NOISE_SIGMA_MULTIPLIER = 5.0
Issue:       The multiplier is applied to an unscaled MAD (5 MAD ≈ 3.4σ for Gaussian scatter), so the name says sigma where it is not; the template also hard-codes the SNR colour thresholds 10 and 5, duplicating `_SNR_HIGH` and `_SNR_LOW` (dv_estimation.py:112-113).
Impact:      The template and the verdict can drift apart, and "×" SNR on the panel is in MAD units, not sigma.
Fix:         Rename to `_NOISE_MAD_MULTIPLIER`, pass the thresholds into the view, and label SNR "× MAD".
Gate:        Test that the template colour bands come from the module constants.
Verdict:     CONFIRMED
```

```
ID:          F-227   (origin F-S05-14)
Lens:        L11 numerical and scientific correctness
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  fact
Location:    spectre/domain/manoeuvre_calibration.py:213-217, :236-240
Evidence:
               ("GEO", ManoeuvreKind.ALTITUDE_CHANGE): _Band(
               20.0, 60.0,
               "Table 3: GEO graveyard raise 7-11 m/s. Luch/Olymp-K 1 rose more than "
Issue:       Several bounds are analyst interpolations not present in their own basis text (GEO ALTITUDE_CHANGE 20/60 cites 7-11 and 15; LEO PHASING 50/200 cites 500 and "far less"; GEO PHASING benign 15 is not among 6, 11, 34, 170), contrary to "Every boundary below is traceable" at :47.
Impact:      The posture word (BENIGN/ANNOYANCE/AGGRESSIVE) feeds the threat access band; operators see a cited basis and assume the boundary is published when it is a judgement.
Fix:         Add a `judgement: bool` field to _Band and a sentence in basis naming the choice; surface it in the posture rationale.
Gate:        Test that every band either has both bounds appearing in its basis or has judgement=True.
Verdict:     CONFIRMED
```

```
ID:          F-228   (origin F-S05-16)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/threat_assessment.py:395-402
Evidence:
               for label, value in (
               ("assessed threat level", capability.intel_threat_level),
               ("operational status", capability.operational_status),
Issue:       The evidence list omits discretionary_remaining_m_s, so a caller supplying only the discretionary reserve sees "propellant budget" listed as missing although _signals used it, and confidence undercounts; manoeuvres_observed = 0 counts as used evidence while contributing no signal.
Impact:      The rationale misreports which evidence produced the verdict, undermining the stated aim at :331-333.
Fix:         Add ("discretionary reserve", capability.discretionary_remaining_m_s) to the list.
Gate:        Test asserting a discretionary-only CapabilityEvidence lists it in inputs_used.
Verdict:     CONFIRMED
```

```
ID:          F-229   (origin F-S05-19)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/pol_assessment.py:211-214
Evidence:
               #: True when this single manoeuvre exceeds what any platform in this regime
               #: could hold in total. The assessment's second watchlist recommendation.
               exceeds_on_station_anomaly: bool
Issue:       The comment describes exceeds_platform_ceiling but is attached to exceeds_on_station_anomaly, which is the 500 m/s watchlist threshold (:363).
Impact:      A maintainer swaps the two flags' meanings.
Fix:         Give each field its own correct comment.
Gate:        Doc review.
Verdict:     CONFIRMED
```

```
ID:          F-230   (origin F-S05-20)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/pol_assessment.py:712-717
Evidence:
               if invisible and not missed_routine:
               narrative += (
               " Counterspace-scale behaviour is above it: the smallest event on "
Issue:       Unreachable: `invisible` is non-empty only when the floor exceeds 1.0 m/s, and the 1.0 m/s collision-avoidance reference event is routine, so `missed_routine` is then always non-empty; coverage confirms line 713 never runs.
Impact:      The operator never sees the "smallest event this would catch" sentence the code intends.
Fix:         Change the condition to `if visible:` or remove the branch.
Gate:        Test for a floor of 5 m/s asserting the sentence appears.
Verdict:     CONFIRMED
```

```
ID:          F-231   (origin F-S05-21)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/models.py:21, :38, :205, :348
Evidence:
               stk_name: Auto-derived object name (equals ``name``).
               dv_radial: VNC radial (cross-track) component in m/s.
               arrival_epoch: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
Issue:       stk_name is prefixed (:29, :47), not equal to name; radial is not cross-track (in VNC, N is the cross-track axis); InterceptResult defaults arrival_epoch to the wall clock, so an unset arrival looks like a real one.
Impact:      Misleading frame labels in a manoeuvre record; a silent plausible timestamp on a malformed result.
Fix:         Correct the docstrings; make arrival_epoch required or Optional[None].
Gate:        Doc review; mypy on construction sites after removing the default.
Verdict:     CONFIRMED
```

```
ID:          F-232   (origin F-S05-22)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/decision.py:34, :276-277; spectre/domain/exceptions.py:6-19; spectre/domain/maneuver_planner.py:19
Evidence:
               _R_EARTH_KM = 6371.0
               adversary_idx: int,
               def validate_search_config(config: ManeuverSearchConfig) -> None:
Issue:       Dead code: _R_EARTH_KM is unused and duplicated at spectre/astro/photometry.py:38; adversary_idx is accepted and ignored (no lost logic: ranking needs only the row); summary_table, all four domain exceptions, validate_search_config and ScenarioPlanner have no production caller.
Impact:      Readers infer a validation and planning pipeline that does not run; a mean-radius constant sits beside code using the equatorial R_EARTH.
Fix:         Delete or wire each; drop the adversary_idx parameter.
Gate:        vulture at 60 per cent confidence in CI for spectre/domain.
Verdict:     CONFIRMED
```

```
ID:          F-233   (origin F-S05-23)
Lens:        L11 numerical and scientific correctness
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/domain/manoeuvre_calibration.py:521-528
Evidence:
               if delta_v_m_s >= _BEYOND_ANY_FLOWN_PLATFORM_M_S:
               posture = Posture.BEYOND_PLATFORM
               elif delta_v_m_s <= band.benign_max_m_s:
Issue:       No guard for NaN or negative delta-v: NaN fails every comparison and is classified AGGRESSIVE, and a negative figure is BENIGN.
Impact:      A solver returning NaN appears as an aggressive manoeuvre with a confident rationale ("nan m/s ... is AGGRESSIVE").
Fix:         Raise ValueError (or return an UNASSESSED posture) when not math.isfinite(delta_v_m_s) or delta_v_m_s < 0.
Gate:        Parametrised test for NaN, inf and -1.
Verdict:     CONFIRMED
```

```
ID:          F-234   (origin F-S06-12)
Lens:        L2 error handling and failure modes
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:1340-1343
Evidence:
               red_regime = regime_from_tle(red_tle)
               # BLE001: a malformed element set must not kill the sweep.
               except Exception:  # noqa: BLE001
Issue:       A red regime parse failure silently becomes "LEO" (1343), a target failure silently becomes "compatible" (1219-1220), and in maneuver.py:842-843 and 1091-1092 both sides become "LEO"; none is reported, and the assumed regime drives regime skipping and the posture band (`classify_posture(…, regime, …)`, threat.py:559-561; maneuver.py:667).
Impact:      A GEO interceptor whose regime could not be read is judged against LEO posture bands and its GEO targets are reported as "regime mismatch", with the mismatch text quoting the assumed regime as fact.
Fix:         Append a visible error naming the assumption, or refuse the sweep when the interceptor regime is unknown.
Gate:        Unit test forcing `regime_from_tle` to raise and asserting an operator-visible error.
Verdict:     CONFIRMED
```

```
ID:          F-235   (origin F-S06-15)
Lens:        L6 performance and complexity
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  fact (placement); inference (cost)
Location:    spectre/web/routes/threat.py:1322-1333
Evidence:
               clustering_summary = _reduce_tle_clusters(state)
               epochs = _compute_epochs(red_tle, now)
Issue:       DBSCAN clustering and the 24 h event scan (81 % of 53.8 ms per the comment at threat.py:914-915) run on the event loop before the executor hand-off, and nothing limits concurrent sweeps or screens, which all share the default executor.
Impact:      Each sweep stalls all operators for the clustering time (TBC, depends on history size); repeated sweep or screen requests from one user can saturate the default thread pool that /readyz also uses through `asyncio.to_thread` (health.py:66), risking a readiness failure.
Fix:         Move both calls into the executor job and bound per-user and global concurrency with a semaphore.
Gate:        Test asserting the handler performs no CPU-bound call outside `run_in_executor`; load test on concurrent sweeps.
Verdict:     CONFIRMED
```

```
ID:          F-236   (origin F-S06-19)
Lens:        L4 contracts and data
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:688
Evidence:
               dv_budget_pct = min(100.0, dv / DEFAULT_SWEEP_BUDGET_M_S * 100.0)
Issue:       The intercept panel's "ΔV Budget" bar is always computed against the 500 m/s default (also 711), never the `max_dv_m_s` the operator submitted, unlike the sweep (threat.py:812).
Impact:      An operator working to a 150 m/s budget reads "30 % of 500 m/s" for a burn that uses all of it.
Fix:         Thread `max_dv_m_s` into `_compute_intercept_intel`.
Gate:        Integration test posting a non-default budget and asserting it appears as the denominator.
Verdict:     CONFIRMED
```

```
ID:          F-237   (origin F-S06-21)
Lens:        L1 correctness and edge cases
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:815-817
Evidence:
               if manoeuvre_start.strip():
               with contextlib.suppress(ValueError):
               manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
Issue:       An unparseable start epoch silently becomes "now", and `.replace(tzinfo=UTC)` discards any offset supplied instead of converting it (same at 1067-1069).
Impact:      The operator's chosen burn epoch (for example an apogee from the events panel) is replaced without notice, or shifted by the offset.
Fix:         Reject unparseable input with an operator message; use `.astimezone(UTC)` for aware values and `.replace` only for naive ones.
Gate:        Unit test with "garbage" and with "2026-03-01T00:00:00+01:00".
Verdict:     CONFIRMED
```

```
ID:          F-238   (origin F-S06-29)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/maneuver.py:1060
Evidence:
               Executes all 23 methods concurrently using sensible shared parameters,
Issue:       The batch runs sequentially in one executor thread (1001-1011); apply_intercept's docstring (801-802) names three methods of 25; the module docstring (4) names the same three.
Impact:      Misleads maintainers about concurrency and scope.
Fix:         Correct the three docstrings.
Gate:        Review.
Verdict:     CONFIRMED
```

```
ID:          F-239   (origin F-S06-30)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_all_intercepts_ranking.py:130
Evidence:
               assert "0.001 km/s" in row, (
Issue:       A solver refusal reaches the operator in km/s through the failed-row error text (all_intercepts_result.html:357), and this test pins it, contradicting the m/s rule that test_threat_screen_route.py asserts (`assert "km/s" not in resp.text`) and that the static guard in test_operator_sees_metres_per_second.py cannot see at runtime.
Impact:      An operator-facing km/s figure in a panel otherwise entirely in m/s.
Fix:         Have the solver raise a structured error and render the budget in m/s at the route boundary; update the test to "1 m/s".
Gate:        Rendered-output test asserting no "km/s" in the all-intercepts fragment.
Verdict:     CONFIRMED
```

```
ID:          F-240   (origin F-S06-31)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/threat_sweep.html:100
Evidence:
               <div class="stat-val">{{ "%.3f" | format(worst_coa.dv) }} <span style="font-size:0.7rem; font-weight:400">m/s</span></div>
Issue:       The headline and the group column (285) print three decimals of m/s, which the route comment (threat.py:814-818) calls "noise presented as precision".
Impact:      False precision on the most-read figure.
Fix:         Use the `m_s` filter as the child rows do (333).
Gate:        Tighten test_threat_sweep_template.py:194 to reject a decimal point.
Verdict:     CONFIRMED
```

```
ID:          F-241   (origin F-S06-32)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/threat.py:664
Evidence:
               kwargs["max_delta_v"] = budget / 1000.0  # m/s -> km/s for astro
Issue:       A call-site conversion that manoeuvre_calibration.py:104 says must not exist; also duplicated logic: `_find_tle` (threat.py:494, maneuver.py:1194), `_dominant_axis` and `_burn_direction` (threat.py:708, maneuver.py:253), the 0.7 literal (maneuver.py:291) versus `_DOMINANT_AXIS_FRACTION`, and `_sweep_intents` versus `_INTENT_LABELS`.
Impact:      Numerically correct today; the next edit can drift one copy.
Fix:         Use `to_km_s`; move the shared helpers to one module.
Gate:        Grep test rejecting `/ 1000` and `* 1000` in spectre/web/routes.
Verdict:     CONFIRMED
```

```
ID:          F-242   (origin F-S06-33)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/all_intercepts_result.html:136
Evidence:
               onclick="event.stopPropagation(); aiLoadEngine('{{ item.result.red_name }}','{{ item.result.blue_name }}','{{ item.result.arrival_epoch.strftime('%Y-%m-%dT%H:%M') }}','{{ item.result.method.value }}')"
Issue:       "Load" passes the ARRIVAL epoch, which `aiLoadEngine` writes into `manoeuvre_start` (line 387), and ignores the method argument.
Impact:      Re-running a loaded result starts the burn at the previous solution's arrival time.
Fix:         Pass `item.result.burns[0].burn_epoch`.
Gate:        Template test asserting the Load epoch equals the first burn epoch.
Verdict:     CONFIRMED
```

```
ID:          F-243   (origin F-S06-34)
Lens:        L9 observability
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/maneuver.py:874-876
Evidence:
               logger.error(
               "apply_intercept failed for operator %s: %s", log_safe(current_user.username), exc
               )
Issue:       Raw exception text reaches the log unsanitised here and at threat.py:1180, although threat.py:143-148 records that exception text built from operator element sets can carry newlines and forge records.
Impact:      Log line injection from operator-pasted or UDL-supplied element sets.
Fix:         Wrap with `log_safe(exc)`.
Gate:        Lint or grep test: logger calls in routes pass exceptions only through `log_safe`.
Verdict:     CONFIRMED
```

```
ID:          F-244   (origin F-S06-35)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/maneuver_status.html:7
Evidence:
               {{ selected.burn_location.value | replace("_", " ") | title }}
Issue:       maneuver_status.html, osint_card.html and trade_space_chart.html have no renderer or include, and POST /plan/maneuver/apply-intercept has no caller outside tests.
Impact:      Dead surface that still has to be kept safe; trade_space_chart.html carries its own copy of the "Miss: … km" tooltip.
Fix:         Delete them, or wire them in and test them.
Gate:        Test that every partial is referenced by a route or template.
Verdict:     CONFIRMED
```

```
ID:          F-245   (origin F-S06-36)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/sweep_target_config.html:25
Evidence:
               Regime: <strong style="color:var(--ops-blue)">{{ interceptor_regime }}</strong> — targets filtered to match interceptor orbit.
Issue:       When `_interceptor_regime` fails (threat.py:171-172) the regime is None, counts are unfiltered, and the panel reads "Regime: None … targets filtered".
Impact:      The operator is told filtering happened when it did not.
Fix:         Branch on a None regime and say the list is unfiltered and why.
Gate:        Template test with `interceptor_regime=None`.
Verdict:     CONFIRMED
```

```
ID:          F-246   (origin F-S06-37)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/templates/partials/sweep_manual_tles.html:51
Evidence:
               hx-vals='{"manual_name": "{{ m.name | e }}"}'
Issue:       HTML escaping is not JSON escaping; the attribute is decoded before htmx parses it, so a name containing `"` or `\` yields invalid JSON.
Impact:      Such a manual target cannot be removed.
Fix:         hx-vals='{{ {"manual_name": m.name} | tojson }}'`.
Gate:        Template test with a quote in the name, asserting the attribute parses as JSON.
Verdict:     CONFIRMED
```

```
ID:          F-247   (origin F-S07-06)
Lens:        L3 Security
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:298-300
Evidence:
               url = urllib.parse.urljoin(url, resp.headers.get("location", ""))
               scheme = urllib.parse.urlsplit(url).scheme
               if scheme not in _ALLOWED_URL_SCHEMES:
Issue:       The per-hop redirect check enforces scheme only, yet the docstring (gcat.py:288-289) claims it stops a redirect "onto an address inside the cluster". An https redirect to any host, internal ones included, is followed, and its body is parsed and shown to the operator.
Impact:      If planet4589.org or the DNS path to it is compromised, a 302 to an https service inside the cluster turns the GCAT panel into an SSRF read primitive. The test that names the metadata service (test_outbound_and_ddl_guards.py:171) passes only because it uses http.
Fix:         Pin each hop's host to planet4589.org (or an allowlist) and refuse private, loopback and link-local resolved addresses.
Gate:        Parametrised test adding `https://169.254.169.254/` and `https://10.0.0.1/` as redirect targets, asserting they are refused.
Verdict:     CONFIRMED
```

```
ID:          F-248   (origin F-S07-10)
Lens:        L4 Contracts and data
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/udl.py:724-725
Evidence:
               params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z",
               "dataMode": dm, "maxResults": 1},
Issue:       The docstring promises the state vector "at the most recent available epoch" (udl.py:704), but the query asks for any one record after 2020 with no ordering. `rec = data[0]` (udl.py:760) raises KeyError if UDL answers with a bare object, which the same module says it does elsewhere (udl.py:443-444). The frame silently defaults to "J2000" when absent (udl.py:770).
Impact:      An operator can start intercept geometry from a state vector years old, presented as the latest, or get an unhandled 500.
Fix:         Bound the epoch to a recent window and select the newest client-side as `_select_latest_elset` does; normalise the payload with `_normalise_elset_records`; refuse when referenceFrame is absent.
Gate:        Unit tests for dict payloads and for unordered multi-record payloads.
Verdict:     CONFIRMED
```

```
ID:          F-249   (origin F-S07-12)
Lens:        L3 Security
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  fact
Location:    spectre/web/routes/udl.py:1177-1179
Evidence:
               error_html = "".join(f'<p style="margin:0.1rem 0">{e}</p>' for e in errors)
               return _HTMLResponse(
               f'<div class="callout callout-red" style="font-size:0.72rem">{error_html}</div>'
Issue:       The sync response is built by f-string with exception text (`{exc}` at udl.py:1145,1167) inserted without html.escape, bypassing the Jinja autoescaping every other route relies on (app.py:49).
Impact:      Today the exception strings carry server-built URLs and library messages (inference), so exploitation needs attacker influence over an httpx or JSON error message. Any future error that includes response content becomes stored-free reflected XSS in the console.
Fix:         Render a template, or html.escape each entry.
Gate:        Ruff/semgrep rule forbidding f-string HTMLResponse bodies that interpolate a variable not wrapped in html.escape.
Verdict:     CONFIRMED
```

```
ID:          F-250   (origin F-S07-17)
Lens:        L7 Design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:289-290
Evidence:
               resp.raise_for_status()
               except httpx.HTTPStatusError as exc:
Issue:       Every non-2xx response has already returned at udl.py:278, so the `raise_for_status` and the HTTPStatusError handler (udl.py:290-297) are dead code.
Impact:      Misleading error handling. A maintainer may believe that path is live and tested.
Fix:         Delete the dead branch.
Gate:        Coverage gate on routes/udl.py login lines.
Verdict:     CONFIRMED
```

```
ID:          F-251   (origin F-S07-18)
Lens:        L3 Security
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/pol_panel.html:70
Evidence:
               <input type="password" name="udl_pass" autocomplete="current-password" placeholder="UDL password" />
Issue:       The PoL direct-credential field invites the browser to save the UDL password, which contradicts `autocomplete="off"` on the main UDL form (udl_status.html:12). The route also `.strip()`s the password (pol.py:297), which alters a credential that has leading or trailing spaces.
Impact:      The UDL password is stored in browser profiles on shared operations-room terminals.
Fix:         Use `autocomplete="off"` (or `new-password`) and do not strip passwords.
Gate:        Template lint asserting every password input named for UDL carries autocomplete="off".
Verdict:     CONFIRMED
```

```
ID:          F-252   (origin F-S07-21)
Lens:        L7 Design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:1027
Evidence:
               _UDL_BASE = "https://unifieddatalibrary.com/udl"
Issue:       The UDL base URL is defined three times (udl.py:55, udl.py:1027 shadowing the module constant, pol.py:32), with no configuration for test or alternative UDL instances.
Impact:      A base-URL change made in one place leaves the other routes talking to the old host.
Fix:         Define it once in settings and import it.
Gate:        Grep check in CI for the literal outside settings.
Verdict:     CONFIRMED
```

```
ID:          F-253   (origin F-S07-22)
Lens:        L8 Clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:108-111
Evidence:
               ) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
               Returns ``(tle_text, metadata, rms_metadata)``.
Issue:       The docstring says three elements are returned. The signature and `_parse_udl_elset_response` return four, with sat_name as the fourth.
Impact:      Misleading contract for the next caller.
Fix:         Correct the docstring.
Gate:        Docstring-signature check (pydoclint) in CI.
Verdict:     CONFIRMED
```

```
ID:          F-254   (origin F-S07-23)
Lens:        L4 Contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:476
Evidence:
               df = df[mask]
Issue:       pyright reports `Series | Unknown | Self@DataFrame` is not assignable to DataFrame here (audit/tools-raw/pyright.txt:16), and `intel.py:23` returns an Optional where a dict is declared (pyright.txt:12). Both are type-only at runtime. In addition, gcat responses have no size cap (`resp.content`, gcat.py:341) and `_page_data` copies the whole frame on every request (gcat.py:467).
Impact:      Type checking is red for these files, and memory use per table request scales with dataset size.
Fix:         Use `df = df.loc[mask]` with a typed mask; return a narrowed value in intel._load; cap the download size; filter without `.copy()`.
Gate:        pyright in CI on spectre/web/routes and spectre/data.
Verdict:     CONFIRMED
```

```
ID:          F-255   (origin F-S07-24)
Lens:        L1 Correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:800-804
Evidence:
               raw = str(rec.get("createdAt") or "").strip().replace("Z", "+00:00")
               try:
               return datetime.fromisoformat(raw)
Issue:       A createdAt without an offset parses to a naive datetime. `max(..., key=_parse_created_at)` (udl.py:857) then compares naive with aware values and raises TypeError, which /udl/hrr does not catch. Separately, `_parse_tle_epoch` accepts a day-of-year of 0 or above 366 without complaint (udl.py:49-51).
Impact:      One malformed notification turns the HRR panel into a 500, and a corrupt epoch field becomes a plausible-looking date.
Fix:         Attach UTC when tzinfo is None; reject a day-of-year outside 1 to 366.
Gate:        Unit tests for both inputs.
Verdict:     CONFIRMED
```

```
ID:          F-256   (origin F-S07-25)
Lens:        L3 Security
Severity:    Low
Confidence:  Medium
Epistemics:  fact
Location:    spectre/web/templates/partials/catalog_results.html:31
Evidence:
               hx-vals='{"satno": {{ obj.satno }}}'
Issue:       A UDL-sourced satno is placed raw into a JSON attribute (also hrr_panel.html:55,63,106,114 for `sat.satno`). Autoescaping stops an attribute break-out, but not JSON injection or invalid JSON (the fallback value is "—", udl.py:992).
Impact:      A catalogue entry without a satno yields a broken button. A crafted upstream value could add keys to the htmx request.
Fix:         Use `{{ obj.satno | tojson }}`.
Gate:        Template lint: every `hx-vals` interpolation goes through tojson.
Verdict:     CONFIRMED
```

```
ID:          F-257   (origin F-S08-09)
Lens:        L2 error handling and failure modes
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/health.py:111-118
Evidence:
               settings = get_settings()
               healthy, detail = await check_storage(settings.data_dir)
Issue:       Readiness probes only the data directory, never the database, so a pod whose PostgreSQL is unreachable reports ready.
Impact:      The platform routes logins to a pod that 500s on every authenticated request; the probe stays green during a database outage.
Fix:         Add a bounded `SELECT 1` through `AsyncSessionLocal` under the same timeout and fold it into the 503 diagnosis.
Gate:        Unit test monkeypatching the engine to raise, asserting /readyz returns 503.
Verdict:     CONFIRMED
```

```
ID:          F-258   (origin F-S08-13)
Lens:        L8 clarity and comments
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/_entrypoint.py:40-44
Evidence:
               # Keycloak single-sign-on gateway in front of the service, not by this bind.
               access_log=False,  # request logging is handled by the application's own audit path
Issue:       Both justifications for the bind and for disabling the access log point at controls that do not exist in the code: there is no request-logging middleware, and nothing in the repository configures or depends on a Keycloak gateway.
Impact:      A reviewer accepts the 0.0.0.0 bind and the missing access log on the strength of two absent controls; requests other than login and admin actions leave no trace.
Fix:         Either add a request-logging middleware (method, path via log_safe, status, user) or re-enable the uvicorn access log; replace the Keycloak sentence with what actually bounds exposure, or cite where the gateway is configured.
Gate:        Test asserting one log record per request; review checklist on security-hotspot justifications.
Verdict:     CONFIRMED
```

```
ID:          F-259   (origin F-S08-15)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/login.py:28
Evidence:
               _SESSION_COOKIE_MAX_AGE = 28_800
Issue:       The session lifetime is defined twice (auth.py:22 and here), kept in step only by a comment.
Impact:      Changing one leaves the browser cookie and the server-side expiry disagreeing.
Fix:         Import `_SESSION_MAX_AGE` from auth.py.
Gate:        Test asserting the Set-Cookie Max-Age equals `auth._SESSION_MAX_AGE`.
Verdict:     CONFIRMED
```

```
ID:          F-260   (origin F-S08-17)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/admin.py:66-67, spectre/web/rate_limit.py:1
Evidence:
               server had already committed the change, so a created, renamed or deleted
               user was invisible until the page was reloaded by hand.
               """In-process sliding-window rate limiters for SPECTRE UDL proxy routes.
Issue:       The admin docstring describes renaming, which no route supports, and the rate_limit module docstring scopes itself to UDL routes while its class also backs both login tiers.
Impact:      Misleads a reader about the admin surface and where the login limiter lives.
Fix:         Drop "renamed"; mention the login tiers in the module docstring.
Gate:        Review.
Verdict:     CONFIRMED
```

```
ID:          F-261   (origin F-S08-18)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/database.py:200
Evidence:
               username = settings.spectre_admin_user.strip()
Issue:       The bootstrap and break-glass paths write SPECTRE_ADMIN_USER to the users table without the `_USERNAME_PATTERN` and 64-character checks that admin.py:126-132 applies, and break-glass silently promotes an existing operator of that name to admin.
Impact:      An environment typo creates an identity the form would refuse, or elevates the wrong account.
Fix:         Validate against the shared pattern at boot and refuse to promote a non-admin without an explicit second flag.
Gate:        Bootstrap test with an invalid name asserting a ConfigurationError.
Verdict:     CONFIRMED
```

```
ID:          F-262   (origin F-S08-19)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/log_safety.py:58
Evidence:
               return collapsed[: max(0, limit - len(_ELLIPSIS))] + _ELLIPSIS
Issue:       For `limit` below 3 the result is "..." (3 characters), longer than `limit`, contradicting "never longer than *limit*" (line 48-49).
Impact:      Latent only; every call site uses the default 120.
Fix:         Return `collapsed[:limit]` when `limit <= len(_ELLIPSIS)`.
Gate:        Parametrised test over limit 0-3 asserting `len(result) <= limit`.
Verdict:     CONFIRMED
```

```
ID:          F-263   (origin F-S08-20)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_login_hardening.py:271-272
Evidence:
               Every write to ``session_epoch`` goes through ``session_epoch_now``, which
               truncates to whole seconds. That is not tidiness. itsdangerous stamps a
Issue:       The class docstring describes a timestamp epoch design that has been replaced by the generation counter; neither name exists.
Impact:      A reader is told the wrong mechanism for the control under test.
Fix:         Rewrite the docstring around `session_generation`.
Gate:        Review.
Verdict:     CONFIRMED
```

```
ID:          F-264   (origin F-S09-20)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/training.py:163-168, 253, 350
Evidence:
               if started.tzinfo is None:
               started = started.replace(tzinfo=UTC)
               elapsed = (ts.ended_at - started).total_seconds() / 60.0
Issue:       pyright reports `Operator "-" not supported for "None"` at :168 (pyright.txt:20) because `ended_at` is `Mapped[datetime | None]`; it is safe at runtime since :163 assigns it, and `ChallengeResult.scored == True # noqa: E712` at :253 and :350 is a working SQLAlchemy expression written in the form that needs a suppression.
Impact:      Type-check noise that hides real Optional misuse; the leave path (:155-171) is uncovered (pytest.txt:118).
Fix:         now = datetime.now(UTC); ts.ended_at = now; elapsed = (now - started)...`; use `ChallengeResult.scored.is_(True)` and drop the noqa.
Gate:        pyright in CI with reportOptionalOperand as error; ruff E712 without suppression.
Verdict:     CONFIRMED
```

```
ID:          F-265   (origin F-S09-21)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/training/gamification.py:162-176
Evidence:
               Speed multiplier [0.5, 1.5] applied when ``speed_multiplier: true``
               multiplier   = max(0.5, min(2.0, speed_factor)) if action.speed_multiplier else 1.0
Issue:       The docstring and gamification.yaml:79 say [0.5, 1.5]; the code clamps to [0.5, 2.0] and the test docstring at test_training_gamification.py:113 says [0.5, 2.0].
Impact:      Three sources disagree on a tuned constant; harmless today only because no caller passes speed_factor (F-S09-22).
Fix:         Pick one range, put it in the YAML, and read it in code.
Gate:        Test asserting the clamp equals the YAML value.
Verdict:     CONFIRMED
```

```
ID:          F-266   (origin F-S09-24)
Lens:        L1 correctness and edge cases
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/operator.py:291-292
Evidence:
               start_dt = datetime.fromisoformat(scenario_start.strip()).replace(tzinfo=UTC)
               stop_dt = datetime.fromisoformat(scenario_stop.strip()).replace(tzinfo=UTC)
Issue:       .replace(tzinfo=UTC)` relabels rather than converts, so an input carrying an offset such as `2026-01-01T00:00:00+05:00` is stored five hours late.
Impact:      Event detection and planning windows silently shift by the offset for any pasted timestamp that is not already UTC.
Fix:         dt = datetime.fromisoformat(s); dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)`.
Gate:        Route test posting an offset timestamp and asserting the stored UTC value.
Verdict:     CONFIRMED
```

```
ID:          F-267   (origin F-S09-26)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/blue_list.html:10; spectre/web/routes/operator.py:86-88
Evidence:
               hx-delete="/assets/blue/{{ asset.name }}"
Issue:       Asset names are HTML-escaped but not URL-encoded into the DELETE path, and add_blue_asset and add_red_track accept any name (including empty) and any string as a TLE without parsing.
Impact:      A name containing `/`, `?` or `#` (possible from UDL-sourced HRR names via quick-add) cannot be removed; malformed TLEs fail later in a solver instead of at entry.
Fix:         Use `{{ asset.name | urlencode }}`, require a non-empty name, and parse the TLE with Satrec on add.
Gate:        Route test adding "A/B" then deleting it; test that a garbage TLE is rejected.
Verdict:     CONFIRMED
```

```
ID:          F-268   (origin F-S09-28)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/static/spectre-theme/css/spectre-theme.css:1-900; spectre/web/templates/base.html:8
Evidence:
               <link rel="stylesheet" href="/static/spectre-theme.css" />
Issue:       Only static/spectre-theme.css (1155 lines) is loaded; static/spectre-theme/css/spectre-theme.css (900 lines) is a stale divergent copy (first difference at line 41, the contrast-raised --spectre-color-sensor-grey), and favicon.svg, spectre_icon_family.svg, spectre_icon_mark.svg, spectre_logo_primary.svg, app-icon-512.svg and splash.html are not referenced by any template or code.
Impact:      A designer editing the copy the theme README points to (README.md:64) changes nothing, and the stale copy reintroduces a contrast failure if anyone links it.
Fix:         Delete the stale copy and unreferenced assets, or make the theme README point at the loaded file.
Gate:        Test that every file under static/ is referenced by a template, CSS or the README allow-list.
Verdict:     CONFIRMED
```

```
ID:          F-269   (origin F-S09-29)
Lens:        L10 build, config and deploy
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/splash_overlay.html:3, 89-91, 119
Evidence:
               Auto-dismissed after 3.2 s or on click/keypress.
               <span style="font-family:var(--spectre-font-mono,'JetBrains Mono',monospace);font-size:9px;color:#374151;letter-spacing:2px;">UNCLASSIFIED</span>
               var timer = setTimeout(spectreCloseSplash, 3400);
Issue:       The classification marking "UNCLASSIFIED" and version "v2.0.0" (:89) are hard-coded while pyproject.toml:44 says 0.5.24, and the comment's 3.2 s disagrees with the 3400 ms timer.
Impact:      On a deployment accredited above OFFICIAL or UNCLASSIFIED the console displays an incorrect protective marking, which is a security-procedure failure rather than a cosmetic one; the version shown to operators is wrong.
Fix:         Drive marking and version from settings (with the marking also used by base.html:62) and fix the comment.
Gate:        Test that the rendered splash and banner marking equal the configured value and the version equals the package version.
Verdict:     CONFIRMED
```

```
ID:          F-270   (origin F-S09-30)
Lens:        L3 security
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/app.py:242-243; spectre/web/templates/partials/training_scenario_list.html:63
Evidence:
               #   style-src 'unsafe-inline'. Roughly 1500 inline style attributes and two
               #     inline <style> blocks. To close: move them into the stylesheet.
               hx-on::after-request="setTimeout(function(){ var el=document.getElementById('scenario-detail'); if(el) el.scrollIntoView({behavior:'smooth', block:'start'}); }, 100)">
Issue:       The CSP is compatible with the slice's markup only because script-src carries 'unsafe-inline' and 'unsafe-eval'; the slice templates hold 38 inline handlers, inline scripts in training.html:271, operator.html (8 blocks), decision_panel.html:157, training_scenario_active.html:193 and splash_overlay.html:109, and an hx-on attribute that needs 'unsafe-eval'; the app.py comment says two inline style blocks where three exist (training.html:266, intercept_geometry.html:6, splash_overlay.html:11).
Impact:      Known and documented gap: the CSP is not a control against injected inline script; the style-block count understates the work to close it.
Fix:         As app.py records: move scripts to /static, convert handlers to delegated listeners, replace hx-on with listeners; correct the count to three.
Gate:        tests/integration/test_security_headers.py extended to fail when the count of inline handlers rises.
Verdict:     CONFIRMED
```

```
ID:          F-271   (origin F-S09-31)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tle_clustering/config.py:58-61, 65-67, 95-114
Evidence:
               To add a fourth clustering dimension (e.g. mean motion), add a
               ``mean_motion_tolerance_rev_per_day`` field here and update
               ``parser.TLERecord`` and ``clustering._normalise`` accordingly — no other
Issue:       TLERecord lives in models.py and the function is `_build_feature_matrix`; selection.py:61-64 also hard-codes the three elements, so "no other files need to change" is false; the defaults 0.01, 0.05, 1e-4, 1.0, 2 and "chebyshev" are written three times (field defaults, from_constants fallbacks, constants.py:53-56), contrary to the module docstring's "Downstream code must not hard-code any of these values".
Impact:      A maintainer following the docstring adds a dimension that clustering uses but representative selection ignores.
Fix:         Correct the names, list selection.py, and have from_constants fall back to `cls.__dataclass_fields__[...].default`.
Gate:        Test that from_constants({}) equals ClusteringConfig().
Verdict:     CONFIRMED
```

```
ID:          F-272   (origin F-S09-33)
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/training/config/scenarios.yaml:53-54
Evidence:
               tle_line1: "1 99001U 25001A   25166.00000000  .00000000  00000-0  00000-0 0  9991"
               tle_line2: "2 99001   0.0100  45.0000 0000200  90.0000   0.0000  1.00270000 00011"
Issue:       50 of the 52 synthetic TLE lines carry an incorrect modulo-10 checksum in column 69 (computed in scratch; this pair should end 7 and 3).
Impact:      Trainees who paste these into any checksum-validating tool see failures, and SPECTRE silently accepts them because it never validates checksums.
Fix:         Regenerate the checksums; add checksum validation at TLE entry.
Gate:        Unit test validating every scenario TLE's checksum and SGP4 error code.
Verdict:     CONFIRMED
```

```
ID:          F-273   (origin F-S09-34)
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/training/config/tutorials.yaml:69-81, 137
Evidence:
               its mission life.  The efficiency score in your debrief rewards low-ΔV solutions.
Issue:       The tutorial names buttons that do not exist ("View Scenario", "Start Scored Attempt", "Explore (Unscored)" versus "View & Load", "Start Scenario", "Explore") and promises an efficiency score the debrief never computes.
Impact:      New operators are misdirected in their first tutorial.
Fix:         Align the text with the templates and drop the efficiency promise until it exists.
Gate:        Test that quoted button labels in tutorials.yaml appear in the training templates.
Verdict:     CONFIRMED
```

```
ID:          F-274   (origin F-S09-35)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_focus_visible_indicator.py:93-116; tests/unit/test_contrast_floors.py:59-106
Evidence:
               def _luminance(colour: str) -> float:
Issue:       _tokens`, `_luminance`, `_ratio`, `_over` and `_rule_block` are re-implemented in both test modules.
Impact:      A fix to the WCAG formula in one copy leaves the other measuring differently.
Fix:         Move them to a shared tests/unit/_css.py helper.
Gate:        jscpd in CI over tests/.
Verdict:     CONFIRMED
```

```
ID:          F-275   (origin F-S09-36)
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/training_scenario_detail.html:69; spectre/web/templates/partials/training_scenario_list.html:6
Evidence:
               <span style="font-size:0.6rem; font-weight:700; color:{{ cfg_axis_colour(obj.skill_axis) if cfg_axis_colour is defined else '#6b7280' }};
               No scenarios are available yet.  Complete the Orientation tutorial to unlock Level 1 scenarios.
Issue:       cfg_axis_colour` is never put in any context, so the branch is dead and every objective renders grey; the empty-list message says Level 1 scenarios need the Orientation tutorial, but they are available by default.
Impact:      Cosmetic and misleading copy.
Fix:         Pass the axis colour map (as the active partial hard-codes at :86-92) or remove the branch; correct the message.
Gate:        n/a
Verdict:     CONFIRMED
```

```
ID:          F-276   (origin F-S09-37)
Lens:        L5 resource lifecycle and concurrency
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/training.py:54-75, 101-102
Evidence:
               # Open a new session row (we close it on departure via /training/leave)
               session = await _open_session(current_user.username, db)
Issue:       Every GET /training (including refreshes and the embedded console iframe returning to it) inserts a TrainingSession row that is closed only by the leave form, and _get_or_create_progress has a check-then-insert race on the unique username column.
Impact:      Orphaned open sessions accumulate and time_in_training_minutes is under-counted; two simultaneous first visits can raise IntegrityError (500).
Fix:         Reuse the latest open session for the user; insert progress with ON CONFLICT DO NOTHING then select.
Gate:        Test that two GETs create one open session.
Verdict:     CONFIRMED
```

```
ID:          F-277   (origin F-S10-06)
Lens:        L10 build, config and deploy
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  Medium
Epistemics:  inference
Location:    .github/workflows/ci.yml:127-128
Evidence:
               count=$(docker run --rm --entrypoint /bin/sh spectre:ci -c \
               'find / -xdev -perm /6000 \( -type f -o -type d \) 2>/dev/null | wc -l')
Issue:       The runtime suid check in CI (and identically scripts/verify-container.sh:71-72 and scripts/simulate-pipeline.sh:115-116) uses the exact pipe-to-`wc -l` with suppressed stderr that Dockerfile:145-148 calls fail-open, and it runs as the image's non-root `USER 10001:0` (Dockerfile:181), so find silently skips directories that uid cannot read and reports 0.
Impact:      A setuid file inside a root-only directory ships while CI, verify-container and the pipeline simulation all print a clean count; the build-time sweep (run as root) remains the only real control, and no test pins these copies.
Fix:         Run the check with `--user 0`, capture paths directly (`remaining=$(find ... -print)`) without suppressing stderr, and fail on any find error, matching Dockerfile:152-160.
Gate:        Extend `test_sweep_verification_uses_no_pipe` (tests/unit/test_deployment_contract.py:162) to scan ci.yml and both scripts for `-perm /6000` followed by a pipe or by `2>/dev/null`.
Verdict:     CONFIRMED
```

```
ID:          F-278   (origin F-S10-07)
Lens:        L10 build, config and deploy
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  inference
Location:    scripts/check-quality.sh:82-84
Evidence:
               if [ -z "$SRC_FILES" ] && [ -z "$TST_FILES" ]; then
               printf '\nNo analysed Python files changed against %s. Nothing to check.\n\n' "$BASE"
               exit 0
Issue:       On a push to master, ci.yml:196 passes `master` as the base, the merge base of master and HEAD is HEAD, a clean CI checkout has no working-tree diff, and the script exits 0 before every leg, including the whole-repository coverage report at lines 132-166, so the "Quality Gate" job is a guaranteed pass on every push to master; separately the diff-cover leg (line 125) uses diff-cover's own comparison, which by default does not include untracked files, unlike the ruff and complexity legs (TBC, re-verify with `diff-cover --help` for `--include-untracked`).
Impact:      A direct push or merge commit to master is never scored, and the job's green tick reads as a pass; with O2 the job also cannot install pytest, so its real state on PRs is TBC.
Fix:         Skip the job on `push` events explicitly (`if: github.event_name == 'pull_request'`) so it reads as skipped, not passed, and move the whole-repository coverage leg above the early exit; pass `--include-untracked` to diff-cover.
Gate:        A test in tests/unit/test_quality_gate_scope.py asserting the whole-repository leg precedes any `exit 0`, and a CI condition on the quality job.
Verdict:     CONFIRMED
```

```
ID:          F-279   (origin F-S10-09)
Lens:        L10 build, config and deploy
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    .pre-commit-config.yaml:13
Evidence:
               rev: v0.9.0
Issue:       The pre-commit hook versions lag the locked tool versions by a wide margin: ruff v0.9.0 against `ruff==0.16.5` (requirements-dev.txt:987), mypy v1.14.0 (line 28) against `mypy==2.3.1` (requirements-dev.txt:758), bandit 1.7.10 (line 20) against `bandit==1.9.4` (requirements-dev.txt:72).
Impact:      A commit passes the local hook and fails CI or the house loop (or the reverse), which trains developers to bypass hooks; mypy 1.x and 2.x can disagree on strict-mode errors.
Fix:         Set each `rev` to the locked version, or replace the hooks with `repo: local` entries that run the venv tools so there is one version source.
Gate:        A test comparing each `rev` in .pre-commit-config.yaml with the matching pin in requirements-dev.txt.
Verdict:     CONFIRMED
```

```
ID:          F-280   (origin F-S10-16)
Lens:        L8 clarity and comments (architecture drift)
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    docs/architecture.md:57
Evidence:
               | `monte_carlo.py` | `ManoeuvreHypothesis`, `ManoeuvreType`, `MANOEUVRE_ARCHETYPES`; `run_monte_carlo()` (ProcessPoolExecutor, RK45 + J2 + drag); `MonteCarloResult` with P5/P50/P95 and regime probabilities |
Issue:       The architecture document has drifted from the code in several places: Monte Carlo uses `ThreadPoolExecutor` (spectre/astro/monte_carlo.py:29), line 174 repeats the ProcessPool claim, the run log evicts at 200 not 500 (planning_state.py:32 against line 102), the `maneuvers.py` functions named at line 47 do not exist, and `SPECTRE_logo.svg` is not in static/ (line 115).
Impact:      Concurrency reasoning (GIL, memory isolation, Windows spawn) based on the document is wrong.
Fix:         Correct each row from the code; add a "last verified at version" line.
Gate:        A docs test that resolves every backticked `name()` in docs/architecture.md to a definition under spectre/.
Verdict:     CONFIRMED
```

```
ID:          F-281   (origin F-S10-17)
Lens:        L8 clarity and comments (security policy)
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    SECURITY.md:67-69
Evidence:
               | SEC-01 | No CSRF middleware — form submissions are session-cookie authenticated only | Medium | P1 |
               | SEC-02 | No per-user rate limiting on `/udl/*` proxy routes | Medium | P1 |
               | SEC-03 | No user management web UI — new users require direct DB access | Operational | P1 |
Issue:       The published open items are stale: CSRF is enforced app-wide (spectre/web/app.py:314), UDL routes are rate-limited per user (spectre/web/routes/udl.py:255, 568), and an admin UI exists (spectre/web/routes/admin.py); the two security policies also contradict each other on supported versions (SECURITY.md:14 against docs/SECURITY.md:19).
Impact:      A reporter or assessor gets a wrong picture of the attack surface and of which releases receive fixes.
Fix:         Close SEC-01 to SEC-03 with the implementing commit, keep SEC-04, and make docs/SECURITY.md defer to root SECURITY.md on supported versions.
Gate:        Review checklist item; optionally a test that SECURITY.md open items do not name a control whose module exists.
Verdict:     CONFIRMED
```

```
ID:          F-282   (origin F-S10-18)
Lens:        L8 clarity and comments (stale report restamped)
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    scripts/bump-version.sh:71-75
Evidence:
               DOCS="READINESS.md README.md"
               for doc in $DOCS; do
               [ -f "$doc" ] || continue
Issue:       Every bump rewrites the version literal in READINESS.md, so a report "Assessed 21 August 2026" (READINESS.md:5) headlines "Version **0.5.24**" (line 4) while its evidence is stale: "797 passed, 0 skipped", coverage 74% and "43 packages" (lines 65, 93) against 1,896 passed, 2 skipped, statements 84.35 % (audit/TOOLS.md:31) and 55 pins in requirements.txt; it also says "Template: python" (line 4) and that "The docker-only template skips the SonarQube gate, so those rows are scored against the conditions directly" (lines 106-108).
Impact:      A reader trusts a readiness score as current for 0.5.24 when it describes an older build.
Fix:         Stop rewriting READINESS.md in bump-version.sh; stamp the report with the version it was actually assessed against and regenerate it per release.
Gate:        A test that fails when READINESS.md's assessed date predates the latest CHANGELOG entry while its version matches the current one.
Verdict:     CONFIRMED
```

```
ID:          F-283   (origin F-S10-20)
Lens:        L7 design and structure (dependency surface)
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    requirements-runtime.in:21
Evidence:
               python-docx>=1.1
Issue:       python-docx` is a runtime dependency installed into the image, but the only importer is docs/generate_guide.py:20, which never ships (.dockerignore:18, package-appstore.sh:171); `hypothesis` is pinned in the scanned set (requirements.in:10) and used by no test.
Impact:      The runtime image carries python-docx and its XML stack for no runtime purpose, widening what the container scan can report and what an attacker can reach.
Fix:         Move python-docx to requirements-dev.in (or a docs extra) and drop hypothesis or write the property tests docs/SECURITY.md:94 promises; relock.
Gate:        A test that every top-level name in requirements-runtime.in is imported somewhere under spectre/ or tle_clustering/.
Verdict:     CONFIRMED
```

```
ID:          F-284   (origin F-S10-22)
Lens:        L3 security
Severity:    Low   (reviewer graded Medium; changed in refutation)
Confidence:  High
Epistemics:  fact
Location:    query_UDL_Data.py:12-14
Evidence:
               basicAuth = "Basic " + base64.b64encode(("username:password").encode('utf-8')).decode("ascii")
               # OR (comment one of these lines out)
               basicAuth = "Basic aCharacterStringFromUDLutility=="
Issue:       Extends the ledger's verify=False note (query_UDL_Data.py:22): the root-level sample teaches pasting UDL credentials into source as literals and sends them with TLS verification disabled ("ignore the InsecureRequestWarning", line 21); it is excluded from the image (.dockerignore:52) but sits at the repository root beside the product.
Impact:      A user following the sample commits real UDL credentials and exposes them to any on-path interceptor.
Fix:         Delete it, or move it under docs/examples with credentials read from the environment and `verify=True`.
Gate:        bandit over the whole tree (B501 flags `verify=False`; audit/TOOLS.md 5b) in CI, not only `spectre/`.
Verdict:     CONFIRMED
```

```
ID:          F-285   (origin F-S10-24)
Lens:        L8 clarity and comments (stale build comments)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    Dockerfile:194-196
Evidence:
               # `spectre-serve` was a console script generated by the pip install above.
               # With the package on the path instead, the module entrypoint is equivalent.
               CMD ["/opt/venv/bin/python", "-m", "spectre.web._entrypoint"]
Issue:       There is no pip install of the application "above" (lines 47-53 say it is not installed), line 53 claims "the install ran --no-deps" when line 44 has no `--no-deps`, line 1 calls this the "docker-only template" when it is the python-template input, Dockerfile.docker-only:11 and package-appstore.sh:28-29 still describe a `requirements.lock` that no longer exists, and bump-version.sh:9 says "hatch reads it" while pyproject.toml uses setuptools with a literal version.
Impact:      Maintainers reason about the build from comments that describe an earlier design.
Fix:         Rewrite the comments to the current flow.
Gate:        Review only.
Verdict:     CONFIRMED
```

```
ID:          F-286   (origin F-S10-25)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    .github/workflows/ci.yml:93
Evidence:
               run: pip-audit --desc on --requirement requirements.txt
Issue:       CI audits only requirements.txt; the dev lock, which CI and developers install, carries three urllib3 2.7.0 advisories (audit/TOOLS.md row 6c), and bandit in CI scans only spectre/ (ledger fact).
Impact:      Known-vulnerable tooling in the developer and CI environment is never reported.
Fix:         Add `pip-audit -r requirements-dev.txt` as a non-blocking or blocking step.
Gate:        The CI step itself.
Verdict:     CONFIRMED
```

```
ID:          F-287   (origin F-S10-26)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    .github/workflows/ci.yml:157-159
Evidence:
               - name: Must refuse to boot without a real SECRET_KEY
               run: |
               if docker run --rm spectre:ci 2>&1 | grep -q "ConfigurationError"; then
Issue:       If a regression lets the image boot without a key, `docker run` never exits and, with no `timeout-minutes` on any job, the step hangs until GitHub's 6-hour default rather than failing fast.
Impact:      A fail-closed regression shows as a stuck job for hours instead of a red check.
Fix:         Wrap in `timeout 60 docker run ...` and set `timeout-minutes` on every job.
Gate:        The CI timeouts.
Verdict:     CONFIRMED
```

```
ID:          F-288   (origin F-S10-27)
Lens:        L10 build, config and deploy (shell safety)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    scripts/check-quality.sh:125-128
Evidence:
               if diff-cover "$COVERAGE_XML" --compare-branch="$BASE" --fail-under="$COVERAGE_FLOOR" >/tmp/diffcov.out 2>&1; then
               pass "$(grep -E '^Coverage: ' /tmp/diffcov.out || echo "at or above ${COVERAGE_FLOOR}%")"
               else
Issue:       Fixed, predictable paths in shared /tmp (`/tmp/diffcov.out`, `/tmp/jscpd.out` at line 178, and `/tmp/sim-deps.out`, `/tmp/sim-test.out`, `/tmp/sim-build.out` in scripts/simulate-pipeline.sh:72, 81, 105) while the same scripts use `mktemp -d` elsewhere.
Impact:      Concurrent runs clobber each other's results, and on a shared host another user can pre-create a symlink at the path.
Fix:         Write into a `mktemp -d` directory removed by a trap.
Gate:        shellcheck plus a grep test for `>/tmp/` in scripts/.
Verdict:     CONFIRMED
```

```
ID:          F-289   (origin F-S10-28)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    scripts/package-appstore.sh:251-252
Evidence:
               if [ -f "$LEDGER" ]; then
               if ! grep -qxF "## ${VERSION}" "$LEDGER"; then
Issue:       The ledger gate (lines 236-239: "Refuse to build a version with no ledger entry") passes silently when docs/CHANGE-LEDGER.md is absent, because both checks are guarded by `[ -f "$LEDGER" ]`.
Impact:      Deleting or failing to check out the ledger disables the control with no message.
Fix:         Fail when the ledger file is missing.
Gate:        Add a "ledger file missing" refusal case to tests/integration/test_packager_gates.py:132.
Verdict:     CONFIRMED
```

```
ID:          F-290   (origin F-S10-29)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    scripts/package-appstore.sh:200
Evidence:
               for manifest in pyproject.toml requirements.txt setup.py setup.cfg Pipfile poetry.lock; do
Issue:       The docker-only fail-closed check inspects only the package root and omits names the contract test treats as recognised (requirements.in, uv.lock, Pipfile.lock, pdm.lock; tests/unit/test_deployment_contract.py:778-792), while the only at-any-depth check is the unreachable test of F-S10-13.
Impact:      A recognised manifest nested in spectre/ or tle_clustering/ would flip template detection without the packager noticing.
Fix:         Use `find "$STAGE" -name` over the full recognised list.
Gate:        A packager-gate test that plants `spectre/requirements.in` in a docker-only build.
Verdict:     CONFIRMED
```

```
ID:          F-291   (origin F-S10-30)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    .gitignore:121
Evidence:
               lib/
Issue:       Unanchored directory rules (`lib/`, `logs/`, `var/`, `env/`, `parts/`) match at any depth, the same class of defect the file documents having fixed for `/data/` (lines 107-114), and `git check-ignore` confirms `spectre/lib/x.py` would be ignored; the section comments have been sorted into one block (lines 12-34) detached from the rules they describe.
Impact:      A future `spectre/lib/` or `tle_clustering/env/` package is silently left out of commits, exactly as spectre/data/ was.
Fix:         Anchor root-only rules with a leading slash and restore comment-rule grouping.
Gate:        Extend tests/unit/test_docs_are_committable.py to probe new files under spectre/ and tle_clustering/.
Verdict:     CONFIRMED
```

```
ID:          F-292   (origin F-S10-31)
Lens:        L10 build, config and deploy
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    .dockerignore:26-30
Evidence:
               .env
               .env.*
               !.env.example
Issue:       Docker matches .dockerignore patterns from the context root, so `.env`, `.env.*`, `__pycache__/` and `*.py[cod]` exclude only root-level entries; a `.env` placed under spectre/ would be copied by `COPY spectre/ /app/spectre/` (Dockerfile:77).
Impact:      Low in practice (settings.py:30 loads only the root .env, and the prep stage deletes `__pycache__`), but a stray nested secret file would ship in the image.
Fix:         Use `**/.env`, `**/.env.*`, `**/__pycache__/`, `**/*.py[cod]`.
Gate:        A contract test that each secret and cache pattern in .dockerignore starts with `**/`.
Verdict:     CONFIRMED
```

```
ID:          F-293   (origin F-S10-32)
Lens:        L7 design and structure (obsolete capability material)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    docs/astrogator_notes.md:3-4
Evidence:
               Reference for implementing `StkComSession.compute_maneuver_options` and
               `StkComSession.apply_maneuver` against the STK 13 Astrogator Object Model.
Issue:       Two STK COM reference documents (this and docs/stk_object_model_notes.md:3, with `win32com.client.Dispatch("STK13.Application")` at line 9) describe implementing a `StkComSession` that does not exist and carry no historical banner, unlike docs/phased_plan.md:58 and docs/intercept_engine.md:5; the root SPECTRE_logo.svg:226 brands the product "STK INTERCEPT".
Impact:      Readers infer an STK integration path or dependency that contradicts README.md:20 and docs/architecture.md:5-7.
Fix:         Delete both notes (git history keeps them) or add the same historical banner; retire SPECTRE_logo.svg.
Gate:        A docs test that fails on `STK` or `win32com` in a doc without a "Historical" banner.
Verdict:     CONFIRMED
```

```
ID:          F-294   (origin F-S10-33)
Lens:        L7 design and structure (non-product documents)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    docs/UK_Principal_Engineer_Persona.md:3-4
Evidence:
               > **Version:** 1.0
               > **Classification:** UNCLASSIFIED — For System Prompt / Persona Field Use
Issue:       Four files in docs/ are LLM persona or prompt material, not product documentation: this one (1,114 lines), docs/claude-persona-solution-architect.md (system-prompt persona), docs/SPECTRE_Training_Specialist_Persona.md (persona charter plus design spec) and docs/SPECTRE_Gamification_Prompt.md ("Claude Prompt: Gamified Training Environment..."); .gitignore:92-101 already ignores sibling persona and prompt files, so the policy is inconsistent.
Impact:      Prompt material is versioned as if it were specification, inflating the documentation surface and mixing tooling instructions with product claims.
Fix:         Move them to a separate prompts repository or a clearly named `prompts/` directory excluded from docs indexes; keep only the training design specification, if still authoritative, as product docs.
Gate:        Review only.
Verdict:     CONFIRMED
```

```
ID:          F-295   (origin F-S10-34)
Lens:        L7 design and structure (duplicated assets)
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre_splash_screen.html:2
Evidence:
               <div style="position: relative; background: #0a0c10; border-radius: var(--border-radius-lg); overflow: hidden; padding: 0; min-height: 520px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
Issue:       The splash screen is an HTML fragment (no doctype, depends on an undefined `--border-radius-lg`) referenced by nothing but .dockerignore:51, and the three root SVGs are byte-identical to spectre/web/static/ copies (SHA-1 equal; O8).
Impact:      Two sources of truth for brand assets; an edit to one silently diverges.
Fix:         Delete the root copies and the splash fragment, or move design sources under a `design/` directory with a note naming the shipped copy.
Gate:        A test that fails on any root file whose hash equals a file under spectre/web/static/.
Verdict:     CONFIRMED
```

```
ID:          F-296   (origin F-S10-36)
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  Medium
Epistemics:  inference
Location:    scripts/audit-dependencies.sh:82-86
Evidence:
               case "$FLOOR" in
               3.9|3.10|3.11)
               echo "  PASS  at or below python ${SCANNER_PYTHON}, which is what the App Store's"
Issue:       The gate passes when the lowest resolving interpreter is at or below 3.11, but the property it needs is that 3.11 itself resolves; a set that resolves on 3.9 and fails on 3.11 (an upper-bounded `Requires-Python`) still passes.
Impact:      Rare, but the exact failure the header describes (scanner on 3.11 cannot resolve) would be reported PASS.
Fix:         Test 3.11 directly and fail if it does not resolve.
Gate:        The script itself.
Verdict:     CONFIRMED
```

