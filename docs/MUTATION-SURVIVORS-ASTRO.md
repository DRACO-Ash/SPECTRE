# Mutation run: every surviving mutant in spectre/astro

The list docs/MUTATION-REPORT.md refers to: every mutant in spectre/astro that
no test killed, after the tests added under SPC-071, as `scripts/mutate.py
report --survivors` printed it. The report says how the run was made, which
astro survivors were killed and why the ones in the core geometry modules are
equivalent. The rest are listed here, unjudged, for the module owners.

A row's id is the last part of the runner's mutant id, so `scripts/mutate.py
run --ids` can rerun it. "no_tests" means no test executed the line at all.
Each row survived its covering tests in one of two passes, both recorded in
the runner's results: every covering test, or (for the larger modules) a
quick pass then up to 10 to 20 s of covering tests, the module's own test
files and unit tests first.

These are the figures of the run of 2026-11-04, made with runner versions 1
to 3. They were not re-run with version 4, which checks every kill with the
killing test alone, so the kill counts may include order-dependent false
kills; docs/MUTATION-REPORT.md says how many were checked alone. One row has
been dealt with since without a re-run: `d9509d06aa`, constants.py:91, is
killed by a boundary test in tests/unit/test_astro_edges_from_mutation.py.

| Module | Mutants | Killed | Timed out | Survived | No covering test | Invalid | Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| `spectre/astro/along_track.py` | 47 of 47 run | 43 | 0 | 4 | 0 | 0 | 91.5% |
| `spectre/astro/catalogue.py` | 18 of 18 run | 17 | 0 | 1 | 0 | 0 | 94.4% |
| `spectre/astro/closest_approach.py` | 107 of 107 run | 92 | 0 | 15 | 0 | 0 | 86.0% |
| `spectre/astro/constants.py` | 53 of 53 run | 43 | 0 | 10 | 0 | 0 | 81.1% |
| `spectre/astro/cw_geometry.py` | 202 of 202 run | 128 | 0 | 74 | 0 | 0 | 63.4% |
| `spectre/astro/dv_estimation.py` | 476 of 476 run | 296 | 0 | 161 | 19 | 0 | 62.2% |
| `spectre/astro/elset_approach.py` | 37 of 37 run | 36 | 0 | 1 | 0 | 0 | 97.3% |
| `spectre/astro/events.py` | 71 of 71 run | 28 | 1 | 42 | 0 | 0 | 40.8% |
| `spectre/astro/kepler.py` | 80 of 80 run | 73 | 0 | 7 | 0 | 0 | 91.2% |
| `spectre/astro/lambert.py` | 255 of 255 run | 159 | 2 | 94 | 0 | 0 | 63.1% |
| `spectre/astro/maneuvers.py` | 613 of 613 run | 205 | 4 | 383 | 21 | 0 | 34.1% |
| `spectre/astro/monte_carlo.py` | 665 of 665 run | 312 | 7 | 258 | 88 | 0 | 48.0% |
| `spectre/astro/notso.py` | 239 of 239 run | 140 | 0 | 94 | 5 | 0 | 58.6% |
| `spectre/astro/pattern_of_life.py` | 511 of 511 run | 308 | 2 | 196 | 5 | 0 | 60.7% |
| `spectre/astro/phase_angle.py` | 8 of 8 run | 8 | 0 | 0 | 0 | 0 | 100.0% |
| `spectre/astro/photometry.py` | 454 of 454 run | 268 | 0 | 174 | 12 | 0 | 59.0% |
| `spectre/astro/propagator.py` | 214 of 214 run | 156 | 0 | 46 | 12 | 0 | 72.9% |
| `spectre/astro/response_burn.py` | 90 of 90 run | 69 | 1 | 20 | 0 | 0 | 77.8% |
| `spectre/astro/tactical.py` | 1110 of 1110 run | 618 | 0 | 470 | 22 | 0 | 55.7% |
| `spectre/astro/tle_filter.py` | 63 of 63 run | 52 | 0 | 10 | 1 | 0 | 82.5% |
| `spectre/astro/tle_preprocessing.py` | 93 of 93 run | 45 | 0 | 41 | 7 | 0 | 48.4% |
| `spectre/astro/transfers.py` | 49 of 49 run | 46 | 2 | 1 | 0 | 0 | 98.0% |

| Mutant | Line | Operator | Change | Status |
|---|---:|---|---|---|
| `7fa841db2e` | `spectre/astro/along_track.py:29` | number | `51 -> (52)` | survived |
| `138a410368` | `spectre/astro/along_track.py:30` | number | `63 -> (64)` | survived |
| `04552c95f4` | `spectre/astro/along_track.py:40` | number | `1 -> (2)` | survived |
| `63cc0a3d5c` | `spectre/astro/along_track.py:51` | number | `69 -> (70)` | survived |
| `6e109c8faa` | `spectre/astro/catalogue.py:26` | compare | `set(text) <= _DIGITS -> (set(text) < _DIGITS)` | survived |
| `4b961eb430` | `spectre/astro/closest_approach.py:40` | number | `0.01 -> (0.015)` | survived |
| `ba0e7fd094` | `spectre/astro/closest_approach.py:43` | number | `1e-9 -> (1.5000000000000002e-09)` | survived |
| `f05ad287a2` | `spectre/astro/closest_approach.py:46` | bool | `True -> (False)` | survived |
| `b5a1e4fa32` | `spectre/astro/closest_approach.py:82` | compare | `tolerance_s < b - a < width -> (tolerance_s <= b - a < width)` | survived |
| `a18c197f60` | `spectre/astro/closest_approach.py:84` | compare | `fc < fd -> (fc <= fd)` | survived |
| `eebe1b87ed` | `spectre/astro/closest_approach.py:122` | number | `1 -> (2)` | survived |
| `a863444112` | `spectre/astro/closest_approach.py:146` | number | `1 -> (2)` | survived |
| `f40c943c57` | `spectre/astro/closest_approach.py:147` | compare | `t < span_s - _GRID_SLACK_S -> (t <= span_s - _GRID_SLACK_S)` | survived |
| `ba06ba5948` | `spectre/astro/closest_approach.py:162` | compare | `b < a -> (b <= a)` | survived |
| `a3a1a27c4e` | `spectre/astro/closest_approach.py:162` | return | `return not (a < b or b < a) -> return None` | survived |
| `c92c1d98fe` | `spectre/astro/closest_approach.py:162` | compare | `a < b -> (a <= b)` | survived |
| `9bc30aa22c` | `spectre/astro/closest_approach.py:174` | compare | `values[first] < values[first - 1] -> (values[first] <= values[first - 1])` | survived |
| `b1c9138f2c` | `spectre/astro/closest_approach.py:175` | compare | `values[first] <= values[last + 1] -> (values[first] < values[last + 1])` | survived |
| `85da84977e` | `spectre/astro/closest_approach.py:192` | number | `1 -> (2)` | survived |
| `9810888427` | `spectre/astro/closest_approach.py:196` | number | `1 -> (2)` | survived |
| `c54fcb07e8` | `spectre/astro/constants.py:81` | compare | `apogee_alt < _LEO_MAX_ALT -> (apogee_alt <= _LEO_MAX_ALT)` | survived |
| `9fcdcfd0ae` | `spectre/astro/constants.py:83` | compare | `perigee_alt > _GEO_MAX_ALT -> (perigee_alt >= _GEO_MAX_ALT)` | survived |
| `e108960e77` | `spectre/astro/constants.py:85` | compare | `perigee_alt >= _MEO_MAX_ALT -> (perigee_alt > _MEO_MAX_ALT)` | survived |
| `315b6f525e` | `spectre/astro/constants.py:85` | compare | `apogee_alt <= _GEO_MAX_ALT -> (apogee_alt < _GEO_MAX_ALT)` | survived |
| `fb04e9c861` | `spectre/astro/constants.py:87` | compare | `perigee_alt < _LEO_MAX_ALT -> (perigee_alt <= _LEO_MAX_ALT)` | survived |
| `18bda05fa7` | `spectre/astro/constants.py:87` | compare | `apogee_alt > _MEO_MAX_ALT -> (apogee_alt >= _MEO_MAX_ALT)` | survived |
| `563068a16a` | `spectre/astro/constants.py:90` | compare | `apogee_alt <= _GEO_MAX_ALT -> (apogee_alt < _GEO_MAX_ALT)` | survived |
| `d9509d06aa` | `spectre/astro/constants.py:91` | compare | `apogee_alt > _MEO_MAX_ALT -> (apogee_alt >= _MEO_MAX_ALT)` | survived |
| `999998c0f9` | `spectre/astro/constants.py:94` | compare | `apogee_alt > _LEO_MAX_ALT -> (apogee_alt >= _LEO_MAX_ALT)` | survived |
| `18ec4af4e1` | `spectre/astro/constants.py:96` | compare | `perigee_alt >= _LEO_MAX_ALT -> (perigee_alt > _LEO_MAX_ALT)` | survived |
| `9df9fa941f` | `spectre/astro/cw_geometry.py:69` | number | `0.05 -> (0.07500000000000001)` | survived |
| `d0e0520c73` | `spectre/astro/cw_geometry.py:71` | number | `6.0 -> (9.0)` | survived |
| `ec27d88a6c` | `spectre/astro/cw_geometry.py:73` | number | `1e-6 -> (1.5e-06)` | survived |
| `655979b6ad` | `spectre/astro/cw_geometry.py:75` | number | `120 -> (121)` | survived |
| `e22c5bafda` | `spectre/astro/cw_geometry.py:79` | number | `100_000.0 -> (150000.0)` | survived |
| `365f77cbea` | `spectre/astro/cw_geometry.py:187` | return | `return _sanitise_name(str(value)) -> return None` | survived |
| `094a8f97f8` | `spectre/astro/cw_geometry.py:193` | return | `return value -> return None` | survived |
| `1ab8ab98dd` | `spectre/astro/cw_geometry.py:234` | binop | `z0 * c + zd0 * s / n -> (z0 * c - zd0 * s / n)` | survived |
| `181911db94` | `spectre/astro/cw_geometry.py:236` | binop | `3.0 * n * s * x0 + c * xd0 -> (3.0 * n * s * x0 - c * xd0)` | survived |
| `b056bcfce6` | `spectre/astro/cw_geometry.py:236` | binop | `3.0 * n -> (3.0 / n)` | survived |
| `10680922ca` | `spectre/astro/cw_geometry.py:236` | number | `2.0 -> (3.0)` | survived |
| `a2ec325632` | `spectre/astro/cw_geometry.py:236` | binop | `3.0 * n * s * x0 + c * xd0 + 2.0 * s * yd0 -> (3.0 * n * s * x0 + c * xd0 - 2.0 * s * yd0)` | survived |
| `9b7f169927` | `spectre/astro/cw_geometry.py:236` | number | `3.0 -> (4.5)` | survived |
| `d21710e77d` | `spectre/astro/cw_geometry.py:237` | binop | `4.0 * c -> (4.0 / c)` | survived |
| `245bdcde2c` | `spectre/astro/cw_geometry.py:237` | binop | `c - 1.0 -> (c + 1.0)` | survived |
| `e87bb5dfc6` | `spectre/astro/cw_geometry.py:237` | binop | `4.0 * c - 3.0 -> (4.0 * c + 3.0)` | survived |
| `e6554cfc51` | `spectre/astro/cw_geometry.py:237` | number | `2.0 -> (3.0)` | survived |
| `6d365d7e87` | `spectre/astro/cw_geometry.py:237` | number | `6.0 -> (9.0)` | survived |
| `09b57c2649` | `spectre/astro/cw_geometry.py:237` | binop | `6.0 * n * (c - 1.0) * x0 - 2.0 * s * xd0 -> (6.0 * n * (c - 1.0) * x0 + 2.0 * s * xd0)` | survived |
| `69d935ac66` | `spectre/astro/cw_geometry.py:237` | number | `4.0 -> (6.0)` | survived |
| `d9a8bbe896` | `spectre/astro/cw_geometry.py:237` | binop | `6.0 * n -> (6.0 / n)` | survived |
| `8ab16430a0` | `spectre/astro/cw_geometry.py:237` | binop | `6.0 * n * (c - 1.0) * x0 - 2.0 * s * xd0 + (4.0 * c - 3.0) * yd0 -> (6.0 * n * (c - 1.0) * x0 - 2.0 * s * xd0 - (4.0 * c - 3.0) * yd0)` | survived |
| `59db833da6` | `spectre/astro/cw_geometry.py:237` | number | `3.0 -> (4.5)` | survived |
| `54a614db31` | `spectre/astro/cw_geometry.py:237` | number | `1.0 -> (1.5)` | survived |
| `8e8b5286c0` | `spectre/astro/cw_geometry.py:238` | binop | `-z0 * n * s + zd0 * c -> (-z0 * n * s - zd0 * c)` | survived |
| `fc7294b6e4` | `spectre/astro/cw_geometry.py:238` | unary | `-z0 -> (z0)` | survived |
| `44170012dc` | `spectre/astro/cw_geometry.py:238` | binop | `-z0 * n -> (-z0 / n)` | survived |
| `7f5814b785` | `spectre/astro/cw_geometry.py:238` | binop | `zd0 * c -> (zd0 / c)` | survived |
| `045632085b` | `spectre/astro/cw_geometry.py:250` | number | `0.0 -> (1.0)` | survived |
| `98263e9fed` | `spectre/astro/cw_geometry.py:252` | binop | `state0.z**2 -> (state0.z * 2)` | survived |
| `84f2597294` | `spectre/astro/cw_geometry.py:252` | binop | `state0.y**2 -> (state0.y * 2)` | survived |
| `7f6f04b70a` | `spectre/astro/cw_geometry.py:252` | number | `2 -> (3)` | survived |
| `0c18d5a8a2` | `spectre/astro/cw_geometry.py:252` | binop | `state0.x**2 + state0.y**2 + state0.z**2 -> (state0.x ** 2 + state0.y ** 2 - state0.z ** 2)` | survived |
| `920af4dead` | `spectre/astro/cw_geometry.py:252` | binop | `state0.x**2 -> (state0.x * 2)` | survived |
| `0d9bb166b5` | `spectre/astro/cw_geometry.py:252` | number | `2 -> (3)` | survived |
| `e7d7d8145d` | `spectre/astro/cw_geometry.py:252` | number | `2 -> (3)` | survived |
| `33c15ee943` | `spectre/astro/cw_geometry.py:252` | binop | `state0.x**2 + state0.y**2 -> (state0.x ** 2 - state0.y ** 2)` | survived |
| `b4ba519086` | `spectre/astro/cw_geometry.py:253` | binop | `tof_s / n_points -> (tof_s * n_points)` | survived |
| `1beaa2d386` | `spectre/astro/cw_geometry.py:257` | binop | `i * dt -> (i / dt)` | survived |
| `8aa6c9cc7b` | `spectre/astro/cw_geometry.py:260` | compare | `i < n_points -> (i <= n_points)` | survived |
| `b64cd8e2b5` | `spectre/astro/cw_geometry.py:261` | number | `1 -> (2)` | survived |
| `6464276f4c` | `spectre/astro/cw_geometry.py:261` | binop | `(i + 1) * dt -> ((i + 1) / dt)` | survived |
| `9cd7ebeb3a` | `spectre/astro/cw_geometry.py:261` | binop | `i + 1 -> (i - 1)` | survived |
| `c25c0d03a9` | `spectre/astro/cw_geometry.py:296` | compare | `n < _N_MIN_RAD_S -> (n <= _N_MIN_RAD_S)` | survived |
| `a09d5e5a88` | `spectre/astro/cw_geometry.py:314` | number | `0.0 -> (1.0)` | survived |
| `6883de7adc` | `spectre/astro/cw_geometry.py:314` | unary | `-n -> (n)` | survived |
| `f1872dc73a` | `spectre/astro/cw_geometry.py:314` | binop | `n * r_rel[0] -> (n / r_rel[0])` | survived |
| `c7518b5ac0` | `spectre/astro/cw_geometry.py:314` | number | `1 -> (2)` | survived |
| `e0f5fbf5f5` | `spectre/astro/cw_geometry.py:357` | compare | `ecc > _ECC_WARN_THRESHOLD -> (ecc >= _ECC_WARN_THRESHOLD)` | survived |
| `69ab95e864` | `spectre/astro/cw_geometry.py:363` | compare | `tof_hours > _TOF_WARN_HOURS -> (tof_hours >= _TOF_WARN_HOURS)` | survived |
| `c3e9ef04dc` | `spectre/astro/cw_geometry.py:402` | number | `0.0 -> (1.0)` | survived |
| `f479ea8bce` | `spectre/astro/cw_geometry.py:459` | binop | `dv_radial_km_s**2 + dv_prograde_km_s**2 + dv_normal_km_s**2 -> (dv_radial_km_s ** 2 + dv_prograde_km_s ** 2 - dv_normal_km_s ** 2)` | survived |
| `a77fd3efb0` | `spectre/astro/cw_geometry.py:459` | binop | `dv_normal_km_s**2 -> (dv_normal_km_s * 2)` | survived |
| `ccfdb5b289` | `spectre/astro/cw_geometry.py:459` | number | `2 -> (3)` | survived |
| `d7346418dd` | `spectre/astro/cw_geometry.py:460` | compare | `dv_total > _DV_HARD_CAP_KM_S -> (dv_total >= _DV_HARD_CAP_KM_S)` | survived |
| `22e7f6d1c7` | `spectre/astro/cw_geometry.py:465` | compare | `tof_s < 0.0 -> (tof_s <= 0.0)` | survived |
| `3a3f1cb94b` | `spectre/astro/cw_geometry.py:465` | number | `0.0 -> (1.0)` | survived |
| `3acfb09135` | `spectre/astro/cw_geometry.py:472` | boolop | `not red_tle.strip() or not blue_tle.strip() -> (not red_tle.strip() and (not blue_tle.strip()))` | survived |
| `4beed953fe` | `spectre/astro/cw_geometry.py:496` | compare | `initial_range > _RANGE_UNRELIABLE_KM -> (initial_range >= _RANGE_UNRELIABLE_KM)` | survived |
| `d3c738476f` | `spectre/astro/cw_geometry.py:506` | call | `_log_validity(validity_notes) -> pass` | survived |
| `fc3a44f404` | `spectre/astro/cw_geometry.py:511` | number | `0.0 -> (1.0)` | survived |
| `9d7083c178` | `spectre/astro/cw_geometry.py:525` | number | `1 -> (2)` | survived |
| `5d2561075b` | `spectre/astro/cw_geometry.py:525` | unary | `-1 -> (1)` | survived |
| `fbeef81734` | `spectre/astro/cw_geometry.py:525` | number | `0.0 -> (1.0)` | survived |
| `ad45b5d08a` | `spectre/astro/cw_geometry.py:531` | number | `10.0 -> (15.0)` | survived |
| `06532fdb84` | `spectre/astro/cw_geometry.py:531` | compare | `arrival_range > 10.0 -> (arrival_range >= 10.0)` | survived |
| `4324706860` | `spectre/astro/cw_geometry.py:543` | number | `4 -> (5)` | survived |
| `92254b6cff` | `spectre/astro/cw_geometry.py:543` | number | `4 -> (5)` | survived |
| `07bace5020` | `spectre/astro/cw_geometry.py:546` | number | `1 -> (2)` | survived |
| `50b3e001ae` | `spectre/astro/cw_geometry.py:552` | number | `8 -> (9)` | survived |
| `0b6547ff35` | `spectre/astro/cw_geometry.py:553` | number | `3 -> (4)` | survived |
| `8c7f2991a3` | `spectre/astro/cw_geometry.py:554` | number | `4 -> (5)` | survived |
| `4854583b6d` | `spectre/astro/cw_geometry.py:555` | number | `2 -> (3)` | survived |
| `7c8363a94e` | `spectre/astro/cw_geometry.py:562` | number | `4 -> (5)` | survived |
| `37f879f9db` | `spectre/astro/dv_estimation.py:107` | number | `1.5 -> (2.25)` | survived |
| `e16b761974` | `spectre/astro/dv_estimation.py:109` | number | `3.0 -> (4.5)` | survived |
| `4315b3bf19` | `spectre/astro/dv_estimation.py:112` | number | `3.0 -> (4.5)` | survived |
| `cb2ed0677b` | `spectre/astro/dv_estimation.py:113` | number | `5.0 -> (7.5)` | survived |
| `651eab849d` | `spectre/astro/dv_estimation.py:114` | number | `10.0 -> (15.0)` | survived |
| `081c2b78f8` | `spectre/astro/dv_estimation.py:140` | number | `4 -> (5)` | survived |
| `5db17661aa` | `spectre/astro/dv_estimation.py:148` | number | `3.0 -> (4.5)` | survived |
| `2eb539f4a1` | `spectre/astro/dv_estimation.py:156` | number | `3.0e-4 -> (0.00045)` | survived |
| `40b59c0f31` | `spectre/astro/dv_estimation.py:162` | number | `50.0 -> (75.0)` | survived |
| `4af32023a4` | `spectre/astro/dv_estimation.py:177` | number | `64 -> (65)` | survived |
| `59e8e5f791` | `spectre/astro/dv_estimation.py:178` | number | `24 -> (25)` | survived |
| `dd9dccbb69` | `spectre/astro/dv_estimation.py:182` | number | `1e-9 -> (1.5000000000000002e-09)` | survived |
| `2732712b49` | `spectre/astro/dv_estimation.py:187` | number | `3.0 -> (4.5)` | survived |
| `ca9d7f4ede` | `spectre/astro/dv_estimation.py:199` | number | `10.0 -> (15.0)` | survived |
| `c240b30400` | `spectre/astro/dv_estimation.py:204` | bool | `True -> (False)` | survived |
| `be33e19053` | `spectre/astro/dv_estimation.py:236` | number | `0 -> (1)` | survived |
| `ed87507fe9` | `spectre/astro/dv_estimation.py:242` | call | `parts.append(f"set {self.element_set_no}") -> pass` | survived |
| `c2dd6b4704` | `spectre/astro/dv_estimation.py:243` | return | `return " · ".join(parts) if parts else "unattributed" -> return None` | survived |
| `682578dae1` | `spectre/astro/dv_estimation.py:246` | bool | `True -> (False)` | survived |
| `5b77f96254` | `spectre/astro/dv_estimation.py:268` | bool | `True -> (False)` | survived |
| `8a6b8591c3` | `spectre/astro/dv_estimation.py:285` | bool | `False -> (True)` | survived |
| `5c7902ff7d` | `spectre/astro/dv_estimation.py:296` | bool | `True -> (False)` | survived |
| `d141862274` | `spectre/astro/dv_estimation.py:334` | binop | `dv_km_s - self.median_km_s -> (dv_km_s + self.median_km_s)` | survived |
| `6dff8ec64c` | `spectre/astro/dv_estimation.py:349` | bool | `True -> (False)` | survived |
| `7630497250` | `spectre/astro/dv_estimation.py:402` | boolop | `a and b and a != b -> (a or b or a != b)` | survived |
| `054e93cce7` | `spectre/astro/dv_estimation.py:407` | return | `return self.confidence != "REJECT" -> return None` | survived |
| `564e6caebc` | `spectre/astro/dv_estimation.py:413` | number | `360.0 -> (540.0)` | survived |
| `e86827442f` | `spectre/astro/dv_estimation.py:413` | binop | `deg + 180.0 -> (deg - 180.0)` | survived |
| `e8524cce91` | `spectre/astro/dv_estimation.py:419` | number | `2 -> (3)` | survived |
| `de539d8191` | `spectre/astro/dv_estimation.py:419` | binop | `1.0 - ecc ** 2 -> (1.0 + ecc ** 2)` | survived |
| `381af50b4b` | `spectre/astro/dv_estimation.py:419` | number | `2 -> (3)` | survived |
| `0283f6b99e` | `spectre/astro/dv_estimation.py:420` | binop | `-1.5 * n * J2_EARTH * (R_EARTH / sma_km) ** 2 * math.cos(math.radians( -> (-1.5 * n * J2_EARTH * (R_EARTH / sma_km) ** 2 * math.cos(math.radians` | survived |
| `8939ab1446` | `spectre/astro/dv_estimation.py:461` | unary | `-1 -> (1)` | survived |
| `ab5b76651f` | `spectre/astro/dv_estimation.py:480` | binop | `-math.sin(i1) * math.cos(0.0) -> (-math.sin(i1) / math.cos(0.0))` | survived |
| `1b16a79342` | `spectre/astro/dv_estimation.py:481` | binop | `-math.sin(i2) * math.cos(d_raan) -> (-math.sin(i2) / math.cos(d_raan))` | survived |
| `7a5585e7a1` | `spectre/astro/dv_estimation.py:482` | bool | `True -> (False)` | survived |
| `eaf531ed27` | `spectre/astro/dv_estimation.py:482` | number | `1.0 -> (1.5)` | survived |
| `127e9e7b21` | `spectre/astro/dv_estimation.py:482` | number | `1.0 -> (1.5)` | survived |
| `52152dd885` | `spectre/astro/dv_estimation.py:527` | number | `0.0 -> (1.0)` | survived |
| `dea8393b74` | `spectre/astro/dv_estimation.py:527` | number | `0.0 -> (1.0)` | survived |
| `e095257b5b` | `spectre/astro/dv_estimation.py:527` | boolop | `getattr(rec, "bstar", 0.0) or 0.0 -> (getattr(rec, 'bstar', 0.0) and 0.0)` | survived |
| `53096c3963` | `spectre/astro/dv_estimation.py:531` | boolop | `getattr(rec, "data_mode", "") or "" -> (getattr(rec, 'data_mode', '') and '')` | survived |
| `cf415ed420` | `spectre/astro/dv_estimation.py:533` | number | `0 -> (1)` | survived |
| `702c615002` | `spectre/astro/dv_estimation.py:533` | boolop | `getattr(rec, "element_set_no", 0) or 0 -> (getattr(rec, 'element_set_no', 0) and 0)` | survived |
| `8ab2d0b987` | `spectre/astro/dv_estimation.py:533` | number | `0 -> (1)` | survived |
| `52faa26a2f` | `spectre/astro/dv_estimation.py:571` | number | `0 -> (1)` | survived |
| `b2b965a972` | `spectre/astro/dv_estimation.py:571` | compare | `r_peri > 0 -> (r_peri >= 0)` | survived |
| `e38f5526a9` | `spectre/astro/dv_estimation.py:573` | compare | `v_peri > 0 -> (v_peri >= 0)` | survived |
| `746f654d2f` | `spectre/astro/dv_estimation.py:573` | number | `0 -> (1)` | survived |
| `3c40644766` | `spectre/astro/dv_estimation.py:573` | number | `0.0 -> (1.0)` | survived |
| `de1718552d` | `spectre/astro/dv_estimation.py:578` | compare | `before.sma_km > 0 -> (before.sma_km >= 0)` | survived |
| `b05bd8611a` | `spectre/astro/dv_estimation.py:578` | binop | `abs(d_sma) / before.sma_km -> (abs(d_sma) * before.sma_km)` | survived |
| `9cb665bab5` | `spectre/astro/dv_estimation.py:578` | number | `0.0 -> (1.0)` | survived |
| `a13074fc24` | `spectre/astro/dv_estimation.py:578` | number | `0 -> (1)` | survived |
| `39a64839a8` | `spectre/astro/dv_estimation.py:579` | unary | `not d_sma -> (d_sma)` | survived |
| `d8c589b29b` | `spectre/astro/dv_estimation.py:581` | number | `0 -> (1)` | survived |
| `9ff755961b` | `spectre/astro/dv_estimation.py:581` | compare | `d_sma > 0 -> (d_sma >= 0)` | survived |
| `d965ddc528` | `spectre/astro/dv_estimation.py:585` | compare | `ratio > _ALONG_TRACK_LINEARITY_LIMIT -> (ratio >= _ALONG_TRACK_LINEARITY_LIMIT)` | survived |
| `fad57f89df` | `spectre/astro/dv_estimation.py:626` | binop | `2.0 * dv_along / v -> (2.0 * dv_along * v)` | survived |
| `0356b76c5a` | `spectre/astro/dv_estimation.py:626` | compare | `v > 0 -> (v >= 0)` | survived |
| `4bcc01a431` | `spectre/astro/dv_estimation.py:626` | number | `0 -> (1)` | survived |
| `584eddf4d6` | `spectre/astro/dv_estimation.py:626` | number | `0.0 -> (1.0)` | survived |
| `97b8e1c76c` | `spectre/astro/dv_estimation.py:626` | number | `2.0 -> (3.0)` | survived |
| `9e24601f3d` | `spectre/astro/dv_estimation.py:627` | binop | `d_e_explained ** 2 -> (d_e_explained * 2)` | survived |
| `cd5d28629a` | `spectre/astro/dv_estimation.py:627` | number | `2 -> (3)` | survived |
| `9547d6d4cc` | `spectre/astro/dv_estimation.py:649` | compare | `d_e_residual <= 0.0 -> (d_e_residual < 0.0)` | survived |
| `764c5a2c6e` | `spectre/astro/dv_estimation.py:649` | number | `0.0 -> (1.0)` | survived |
| `1ca35f49c6` | `spectre/astro/dv_estimation.py:670` | binop | `after.inc_deg - before.inc_deg -> (after.inc_deg + before.inc_deg)` | survived |
| `c744619259` | `spectre/astro/dv_estimation.py:684` | compare | `gap_days <= 0.0 -> (gap_days < 0.0)` | survived |
| `e1ae3d688f` | `spectre/astro/dv_estimation.py:684` | number | `0.0 -> (1.0)` | survived |
| `10c56f74c8` | `spectre/astro/dv_estimation.py:685` | call | `notes.append("Zero or negative epoch gap: the drift corrections are ni -> pass` | survived |
| `d5e3ff31f8` | `spectre/astro/dv_estimation.py:687` | compare | `abs(raan_j2_deg) > 1.0 -> (abs(raan_j2_deg) >= 1.0)` | survived |
| `a897e480d1` | `spectre/astro/dv_estimation.py:687` | number | `1.0 -> (1.5)` | survived |
| `92d59dc212` | `spectre/astro/dv_estimation.py:688` | call | `notes.append(f"Removed {raan_j2_deg:+.3f}° of natural node drift over  -> pass` | survived |
| `8871e0d705` | `spectre/astro/dv_estimation.py:717` | number | `0.0 -> (1.0)` | survived |
| `2077fcc614` | `spectre/astro/dv_estimation.py:717` | number | `0.0 -> (1.0)` | survived |
| `a255a88907` | `spectre/astro/dv_estimation.py:719` | number | `1 -> (2)` | survived |
| `8c1d595b74` | `spectre/astro/dv_estimation.py:724` | binop | `k / coarse_steps -> (k * coarse_steps)` | survived |
| `c970172c49` | `spectre/astro/dv_estimation.py:725` | compare | `dr < best[1] -> (dr <= best[1])` | survived |
| `d3faadec8b` | `spectre/astro/dv_estimation.py:741` | number | `1.0 -> (1.5)` | survived |
| `ff44d7aaf3` | `spectre/astro/dv_estimation.py:741` | binop | `1.0 / coarse_steps -> (1.0 * coarse_steps)` | survived |
| `8d03f48a6b` | `spectre/astro/dv_estimation.py:742` | number | `1.0 -> (1.5)` | survived |
| `851677df1b` | `spectre/astro/dv_estimation.py:742` | number | `0 -> (1)` | survived |
| `88dc5e00a7` | `spectre/astro/dv_estimation.py:744` | binop | `hi - lo -> (hi + lo)` | survived |
| `ad3884ab52` | `spectre/astro/dv_estimation.py:744` | compare | `hi - lo < _REFINE_CONVERGED_FRACTION -> (hi - lo <= _REFINE_CONVERGED_FRACTION)` | survived |
| `cd56bab8fd` | `spectre/astro/dv_estimation.py:746` | binop | `hi - (hi - lo) / 3.0 -> (hi + (hi - lo) / 3.0)` | survived |
| `b2596a3d34` | `spectre/astro/dv_estimation.py:746` | number | `3.0 -> (4.5)` | survived |
| `f943c3de61` | `spectre/astro/dv_estimation.py:746` | number | `3.0 -> (4.5)` | survived |
| `623ba4d55d` | `spectre/astro/dv_estimation.py:748` | boolop | `p1 is None or p2 is None -> (p1 is None and p2 is None)` | survived |
| `869ce108d0` | `spectre/astro/dv_estimation.py:750` | compare | `p1[0] <= p2[0] -> (p1[0] < p2[0])` | survived |
| `39b944c98d` | `spectre/astro/dv_estimation.py:756` | number | `0 -> (1)` | survived |
| `9083be5a30` | `spectre/astro/dv_estimation.py:756` | compare | `pick[0] < best[1] -> (pick[0] <= best[1])` | survived |
| `f285e85b4e` | `spectre/astro/dv_estimation.py:790` | number | `0.0 -> (1.0)` | survived |
| `dacf07579a` | `spectre/astro/dv_estimation.py:794` | number | `0.0 -> (1.0)` | survived |
| `d799af8197` | `spectre/astro/dv_estimation.py:806` | bool | `True -> (False)` | survived |
| `7d759c56ba` | `spectre/astro/dv_estimation.py:807` | bool | `True -> (False)` | survived |
| `173f9109f1` | `spectre/astro/dv_estimation.py:813` | number | `0 -> (1)` | survived |
| `51d3ead8d4` | `spectre/astro/dv_estimation.py:814` | return | `return DvEstimate( method=_SWEPT_METHOD, label=_SWEPT_ESTIMATOR_LABEL, -> return None` | no_tests |
| `7e8f594e06` | `spectre/astro/dv_estimation.py:816` | number | `0.0 -> (1.0)` | no_tests |
| `7f713bffaa` | `spectre/astro/dv_estimation.py:816` | bool | `True -> (False)` | no_tests |
| `bf0921c78f` | `spectre/astro/dv_estimation.py:828` | number | `2.0 -> (3.0)` | survived |
| `f4415c50bc` | `spectre/astro/dv_estimation.py:828` | number | `1 -> (2)` | survived |
| `eba6b0568f` | `spectre/astro/dv_estimation.py:828` | compare | `dr <= max(best_dr * 2.0, best_dr + 1.0) -> (dr < max(best_dr * 2.0, best_dr + 1.0))` | survived |
| `5480e68721` | `spectre/astro/dv_estimation.py:828` | binop | `best_dr + 1.0 -> (best_dr - 1.0)` | survived |
| `9b12c1e441` | `spectre/astro/dv_estimation.py:828` | number | `1.0 -> (1.5)` | survived |
| `97235f1f0a` | `spectre/astro/dv_estimation.py:828` | binop | `best_dr * 2.0 -> (best_dr / 2.0)` | survived |
| `2ee23c460a` | `spectre/astro/dv_estimation.py:829` | number | `3 -> (4)` | survived |
| `34d6d76e72` | `spectre/astro/dv_estimation.py:829` | number | `8 -> (9)` | survived |
| `3a97ac74f2` | `spectre/astro/dv_estimation.py:829` | compare | `comparable > max(3, sampled // 8) -> (comparable >= max(3, sampled // 8))` | survived |
| `63c96ec125` | `spectre/astro/dv_estimation.py:829` | binop | `sampled // 8 -> (sampled / 8)` | survived |
| `79947f1d38` | `spectre/astro/dv_estimation.py:839` | call | `notes.append(f"{comparable} instants across the gap are equally close, -> pass` | survived |
| `596564a6c7` | `spectre/astro/dv_estimation.py:842` | compare | `best_dr > _SWEPT_NEVER_CLOSE_KM -> (best_dr >= _SWEPT_NEVER_CLOSE_KM)` | survived |
| `80fa89eeee` | `spectre/astro/dv_estimation.py:843` | call | `notes.append("The two element sets never come close together inside th -> pass` | survived |
| `30394208db` | `spectre/astro/dv_estimation.py:872` | binop | `(float(b) - float(a)) ** 2 -> ((float(b) - float(a)) * 2)` | survived |
| `657238917c` | `spectre/astro/dv_estimation.py:872` | binop | `float(b) - float(a) -> (float(b) + float(a))` | survived |
| `e77de8e549` | `spectre/astro/dv_estimation.py:872` | number | `2 -> (3)` | survived |
| `44f7bed3e4` | `spectre/astro/dv_estimation.py:873` | bool | `True -> (False)` | survived |
| `0618adf32f` | `spectre/astro/dv_estimation.py:878` | bool | `True -> (False)` | survived |
| `1b73c1abfc` | `spectre/astro/dv_estimation.py:878` | number | `0.0 -> (1.0)` | survived |
| `3c9aeebdce` | `spectre/astro/dv_estimation.py:899` | compare | `n < _MIN_SAMPLES_FOR_NOISE -> (n <= _MIN_SAMPLES_FOR_NOISE)` | survived |
| `a837d59d58` | `spectre/astro/dv_estimation.py:901` | number | `0.0 -> (1.0)` | survived |
| `f0a60792a6` | `spectre/astro/dv_estimation.py:901` | number | `0.0 -> (1.0)` | survived |
| `f9e0e93415` | `spectre/astro/dv_estimation.py:912` | number | `1 -> (2)` | survived |
| `59f5958fde` | `spectre/astro/dv_estimation.py:940` | number | `0.0 -> (1.0)` | survived |
| `0c092754eb` | `spectre/astro/dv_estimation.py:943` | number | `0.0 -> (1.0)` | survived |
| `dfa9767cc9` | `spectre/astro/dv_estimation.py:955` | compare | `hi >= _NOISE_ABSOLUTE_FLOOR_KM_S -> (hi > _NOISE_ABSOLUTE_FLOOR_KM_S)` | survived |
| `727f3fcaa2` | `spectre/astro/dv_estimation.py:956` | compare | `lo > 0 -> (lo >= 0)` | survived |
| `6ceee337e4` | `spectre/astro/dv_estimation.py:957` | binop | `hi / lo -> (hi * lo)` | survived |
| `6207048f7a` | `spectre/astro/dv_estimation.py:958` | return | `return float("inf") -> return None` | no_tests |
| `3f5ecc62ae` | `spectre/astro/dv_estimation.py:971` | boolop | `b.data_mode.strip() and a.data_mode.strip() and b.data_mode != a.data_ -> (b.data_mode.strip() or a.data_mode.strip() or b.data_mode != a.data_m` | survived |
| `de478e0074` | `spectre/astro/dv_estimation.py:971` | compare | `b.data_mode != a.data_mode -> (b.data_mode == a.data_mode)` | survived |
| `d7668e584b` | `spectre/astro/dv_estimation.py:972` | call | `warnings.append(f"Data mode changes across the pair ({b.data_mode} → { -> pass` | no_tests |
| `d709167a10` | `spectre/astro/dv_estimation.py:976` | boolop | `b.rms_residual is not None and a.rms_residual is not None -> (b.rms_residual is not None or a.rms_residual is not None)` | survived |
| `c94536d3f9` | `spectre/astro/dv_estimation.py:976` | compare | `b.rms_residual is not None -> (b.rms_residual is None)` | survived |
| `42ed822704` | `spectre/astro/dv_estimation.py:976` | compare | `a.rms_residual is not None -> (a.rms_residual is None)` | survived |
| `a5d1d77723` | `spectre/astro/dv_estimation.py:978` | boolop | `best > 0 and worst / best > _RMS_DISPARITY_RATIO -> (best > 0 or worst / best > _RMS_DISPARITY_RATIO)` | no_tests |
| `daf198f768` | `spectre/astro/dv_estimation.py:978` | number | `0 -> (1)` | no_tests |
| `a885a63a05` | `spectre/astro/dv_estimation.py:978` | binop | `worst / best -> (worst * best)` | no_tests |
| `5208b5abe3` | `spectre/astro/dv_estimation.py:978` | compare | `worst / best > _RMS_DISPARITY_RATIO -> (worst / best >= _RMS_DISPARITY_RATIO)` | no_tests |
| `c5883785f6` | `spectre/astro/dv_estimation.py:978` | compare | `best > 0 -> (best >= 0)` | no_tests |
| `4acc4a7f49` | `spectre/astro/dv_estimation.py:979` | call | `warnings.append(f"Fit quality differs sharply across the pair " f"(RMS -> pass` | no_tests |
| `9086e010e3` | `spectre/astro/dv_estimation.py:991` | unary | `not swept.failed -> (swept.failed)` | survived |
| `7af9ae7950` | `spectre/astro/dv_estimation.py:991` | compare | `miss is not None -> (miss is None)` | survived |
| `d165940f4e` | `spectre/astro/dv_estimation.py:992` | call | `warnings.append( f"The two fits never come within {miss:.1f} km of eac -> pass` | survived |
| `28bfd7a59e` | `spectre/astro/dv_estimation.py:998` | compare | `ratio > _AGREEMENT_POOR -> (ratio >= _AGREEMENT_POOR)` | survived |
| `434e647f97` | `spectre/astro/dv_estimation.py:999` | call | `warnings.append(f"The two estimators disagree by {ratio:.1f}×. The ele -> pass` | no_tests |
| `754d4b16d0` | `spectre/astro/dv_estimation.py:1027` | number | `1.0 -> (1.5)` | survived |
| `b53971170d` | `spectre/astro/dv_estimation.py:1028` | number | `86400.0 -> (129600.0)` | survived |
| `f4fa9ca718` | `spectre/astro/dv_estimation.py:1049` | binop | `a.sma_km - b.sma_km -> (a.sma_km + b.sma_km)` | survived |
| `810a86103d` | `spectre/astro/dv_estimation.py:1049` | number | `2 -> (3)` | survived |
| `8eb0e2d903` | `spectre/astro/dv_estimation.py:1050` | number | `2 -> (3)` | survived |
| `4dd49512c3` | `spectre/astro/dv_estimation.py:1050` | binop | `(b.sma_km * math.radians(theta_deg)) ** 2 -> (b.sma_km * math.radians(theta_deg) * 2)` | survived |
| `5a0cd09004` | `spectre/astro/dv_estimation.py:1051` | number | `2 -> (3)` | survived |
| `de1409622b` | `spectre/astro/dv_estimation.py:1057` | binop | `_SWEPT_MISS_FLOOR_FRACTION * b.sma_km -> (_SWEPT_MISS_FLOOR_FRACTION / b.sma_km)` | survived |
| `a48a78bee4` | `spectre/astro/dv_estimation.py:1057` | compare | `miss <= max(_SWEPT_MISS_FLOOR_FRACTION * b.sma_km, _SWEPT_MISS_TOLERAN -> (miss < max(_SWEPT_MISS_FLOOR_FRACTION * b.sma_km, _SWEPT_MISS_TOLERAN` | survived |
| `71e510b021` | `spectre/astro/dv_estimation.py:1076` | unary | `not legacy.failed -> (legacy.failed)` | survived |
| `f4134527fb` | `spectre/astro/dv_estimation.py:1076` | boolop | `not legacy.failed and dv > 0 and legacy.dv_km_s / dv > _LEGACY_PHASE_I -> (not legacy.failed or dv > 0 or legacy.dv_km_s / dv > _LEGACY_PHASE_IN` | survived |
| `9dcffd931a` | `spectre/astro/dv_estimation.py:1076` | compare | `dv > 0 -> (dv >= 0)` | survived |
| `7795c337f5` | `spectre/astro/dv_estimation.py:1076` | number | `0 -> (1)` | survived |
| `c3756f1e58` | `spectre/astro/dv_estimation.py:1076` | binop | `legacy.dv_km_s / dv -> (legacy.dv_km_s * dv)` | survived |
| `25b8b90491` | `spectre/astro/dv_estimation.py:1076` | compare | `legacy.dv_km_s / dv > _LEGACY_PHASE_INFLATION -> (legacy.dv_km_s / dv >= _LEGACY_PHASE_INFLATION)` | survived |
| `ca4fee47d5` | `spectre/astro/dv_estimation.py:1123` | compare | `dv_km_s < noise.floor_km_s -> (dv_km_s <= noise.floor_km_s)` | survived |
| `8cbe41e1d5` | `spectre/astro/dv_estimation.py:1126` | compare | `snr < _SNR_REJECT -> (snr <= _SNR_REJECT)` | survived |
| `851ff3d057` | `spectre/astro/dv_estimation.py:1127` | return | `return "REJECT", (f"Signal-to-noise {snr:.1f} against this object's ow -> return None` | no_tests |
| `fc401db567` | `spectre/astro/dv_estimation.py:1131` | compare | `"different sources" in w -> ('different sources' not in w)` | survived |
| `6b279794af` | `spectre/astro/dv_estimation.py:1131` | compare | `"Non-positive epoch gap" in w -> ('Non-positive epoch gap' not in w)` | survived |
| `733c72acd7` | `spectre/astro/dv_estimation.py:1131` | boolop | `"different sources" in w or "Non-positive epoch gap" in w or "set asid -> ('different sources' in w and 'Non-positive epoch gap' in w and ('set ` | survived |
| `5afe99ecbc` | `spectre/astro/dv_estimation.py:1132` | compare | `"set aside" in w -> ('set aside' not in w)` | survived |
| `a5b06d781e` | `spectre/astro/dv_estimation.py:1134` | return | `return "LOW", blocking[0] -> return None` | survived |
| `819f1437b0` | `spectre/astro/dv_estimation.py:1135` | compare | `ratio > _AGREEMENT_POOR -> (ratio >= _AGREEMENT_POOR)` | survived |
| `b9d889a119` | `spectre/astro/dv_estimation.py:1136` | return | `return "LOW", f"Independent estimators disagree by {ratio:.1f}×." -> return None` | no_tests |
| `d4137d789a` | `spectre/astro/dv_estimation.py:1137` | compare | `snr < _SNR_LOW -> (snr <= _SNR_LOW)` | survived |
| `90ce766985` | `spectre/astro/dv_estimation.py:1138` | return | `return "LOW", f"Signal-to-noise {snr:.1f} - close to this object's fit -> return None` | no_tests |
| `4c4ede04a9` | `spectre/astro/dv_estimation.py:1144` | compare | `ratio <= _AGREEMENT_HIGH -> (ratio < _AGREEMENT_HIGH)` | survived |
| `67be6ece97` | `spectre/astro/dv_estimation.py:1145` | compare | `snr >= _SNR_HIGH -> (snr > _SNR_HIGH)` | survived |
| `92308bbc1f` | `spectre/astro/dv_estimation.py:1158` | boolop | `agree and strong -> (agree or strong)` | survived |
| `ab5e7828db` | `spectre/astro/dv_estimation.py:1162` | return | `return "MODERATE", (f"Well above noise ({snr:.0f}×), but the estimator -> return None` | no_tests |
| `a698633863` | `spectre/astro/dv_estimation.py:1163` | compare | `ratio is not None -> (ratio is None)` | no_tests |
| `6997341157` | `spectre/astro/dv_estimation.py:1165` | return | `return "MODERATE", (f"Estimators agree within {ratio:.2f}×." if ratio  -> return None` | no_tests |
| `b94f627fc1` | `spectre/astro/dv_estimation.py:1166` | compare | `ratio is not None -> (ratio is None)` | no_tests |
| `6c78a3aa14` | `spectre/astro/elset_approach.py:66` | call | `super().__init__(side) -> pass` | survived |
| `237769a3d2` | `spectre/astro/events.py:40` | number | `7 -> (8)` | survived |
| `ee5f5fc707` | `spectre/astro/events.py:40` | number | `86400.0 -> (129600.0)` | survived |
| `08351163c7` | `spectre/astro/events.py:48` | number | `30.0 -> (45.0)` | survived |
| `6ab9709241` | `spectre/astro/events.py:79` | number | `2 -> (3)` | survived |
| `1a791bb3e5` | `spectre/astro/events.py:82` | binop | `n_steps + 1 -> (n_steps - 1)` | survived |
| `1972a50b5d` | `spectre/astro/events.py:82` | number | `1 -> (2)` | survived |
| `29efe9be3d` | `spectre/astro/events.py:96` | call | `events.sort(key=lambda ev: ev.epoch) -> pass` | survived |
| `7f16867d20` | `spectre/astro/events.py:101` | number | `1e-10 -> (1.5e-10)` | survived |
| `ea55046048` | `spectre/astro/events.py:104` | number | `180.0 -> (270.0)` | survived |
| `316e9f08e4` | `spectre/astro/events.py:106` | number | `60.0 -> (90.0)` | survived |
| `bd8a363007` | `spectre/astro/events.py:118` | binop | `v_mag ** 2 - mu / r_mag -> (v_mag ** 2 + mu / r_mag)` | survived |
| `608762ae1d` | `spectre/astro/events.py:118` | number | `2 -> (3)` | survived |
| `a333f43598` | `spectre/astro/events.py:118` | binop | `((v_mag ** 2 - mu / r_mag) * r - r_mag * v_r * v) / mu -> (((v_mag ** 2 - mu / r_mag) * r - r_mag * v_r * v) * mu)` | survived |
| `96cabbf3da` | `spectre/astro/events.py:118` | binop | `(v_mag ** 2 - mu / r_mag) * r - r_mag * v_r * v -> ((v_mag ** 2 - mu / r_mag) * r + r_mag * v_r * v)` | survived |
| `f05d26137f` | `spectre/astro/events.py:118` | binop | `r_mag * v_r * v -> (r_mag * v_r / v)` | survived |
| `1b7e6e2d27` | `spectre/astro/events.py:120` | number | `0.0 -> (1.0)` | survived |
| `e99b385415` | `spectre/astro/events.py:121` | compare | `ecc > _CIRCULAR_ECC -> (ecc >= _CIRCULAR_ECC)` | survived |
| `12e9d58632` | `spectre/astro/events.py:122` | unary | `-1.0 -> (1.0)` | survived |
| `61a4b21684` | `spectre/astro/events.py:122` | number | `1.0 -> (1.5)` | survived |
| `0cdc4ba773` | `spectre/astro/events.py:122` | binop | `float(np.dot(e_vec, r)) / (ecc * r_mag) -> (float(np.dot(e_vec, r)) * (ecc * r_mag))` | survived |
| `fa0370f7ed` | `spectre/astro/events.py:122` | number | `1.0 -> (1.5)` | survived |
| `162eb73d8d` | `spectre/astro/events.py:122` | binop | `ecc * r_mag -> (ecc / r_mag)` | survived |
| `70fe2e6cbc` | `spectre/astro/events.py:124` | compare | `v_r < 0 -> (v_r <= 0)` | survived |
| `46b356bedc` | `spectre/astro/events.py:125` | number | `360.0 -> (540.0)` | survived |
| `7d3d5fc76b` | `spectre/astro/events.py:125` | binop | `360.0 - ta -> (360.0 + ta)` | survived |
| `09f2c43107` | `spectre/astro/events.py:126` | number | `0.0 -> (1.0)` | survived |
| `accc64ce81` | `spectre/astro/events.py:126` | number | `0 -> (1)` | survived |
| `db40c0cdb6` | `spectre/astro/events.py:126` | compare | `r_mag > 0 -> (r_mag >= 0)` | survived |
| `c0d529c6ad` | `spectre/astro/events.py:134` | compare | `prev_ta < _APOGEE_TA <= ta -> (prev_ta < _APOGEE_TA < ta)` | survived |
| `3810ff07f3` | `spectre/astro/events.py:134` | compare | `prev_ta < _APOGEE_TA <= ta -> (prev_ta <= _APOGEE_TA <= ta)` | survived |
| `2d598dfcbc` | `spectre/astro/events.py:135` | boolop | `prev_ta > _WRAP_FROM_TA and ta < _WRAP_TO_TA -> (prev_ta > _WRAP_FROM_TA or ta < _WRAP_TO_TA)` | survived |
| `fc10f5d3f2` | `spectre/astro/events.py:135` | compare | `ta < _WRAP_TO_TA -> (ta <= _WRAP_TO_TA)` | survived |
| `a3a6926507` | `spectre/astro/events.py:135` | compare | `prev_ta > _WRAP_FROM_TA -> (prev_ta >= _WRAP_FROM_TA)` | survived |
| `cb4b585ef9` | `spectre/astro/events.py:136` | number | `0.0 -> (1.0)` | survived |
| `66eb4a3a8f` | `spectre/astro/events.py:136` | compare | `prev_lat < 0.0 <= lat -> (prev_lat < 0.0 < lat)` | survived |
| `87fa1ff992` | `spectre/astro/events.py:136` | compare | `prev_lat < 0.0 <= lat -> (prev_lat <= 0.0 <= lat)` | survived |
| `9ce1e8f000` | `spectre/astro/events.py:137` | boolop | `prev_lat >= 0.0 and lat < 0.0 -> (prev_lat >= 0.0 or lat < 0.0)` | survived |
| `6df9772982` | `spectre/astro/events.py:137` | compare | `prev_lat >= 0.0 -> (prev_lat > 0.0)` | survived |
| `a48fe85c34` | `spectre/astro/events.py:137` | number | `0.0 -> (1.0)` | survived |
| `b4bcddc6bf` | `spectre/astro/events.py:137` | number | `0.0 -> (1.0)` | survived |
| `897a6f7dd0` | `spectre/astro/events.py:137` | compare | `lat < 0.0 -> (lat <= 0.0)` | survived |
| `db29687c87` | `spectre/astro/events.py:149` | compare | `counts.get(etype, 0) >= max_per_type -> (counts.get(etype, 0) > max_per_type)` | survived |
| `3ad389d186` | `spectre/astro/kepler.py:22` | number | `100 -> (101)` | survived |
| `459b053ea2` | `spectre/astro/kepler.py:23` | number | `1e-10 -> (1.5e-10)` | survived |
| `7f70b56cca` | `spectre/astro/kepler.py:26` | number | `1e-12 -> (1.5e-12)` | survived |
| `59dd449078` | `spectre/astro/kepler.py:36` | compare | `abs(alpha) > _PARABOLIC_ALPHA -> (abs(alpha) >= _PARABOLIC_ALPHA)` | survived |
| `760b20e7cb` | `spectre/astro/kepler.py:36` | binop | `sqrt_mu * dt -> (sqrt_mu / dt)` | survived |
| `dd8a3e19f6` | `spectre/astro/kepler.py:36` | binop | `sqrt_mu * dt / r0 -> (sqrt_mu * dt * r0)` | survived |
| `1cfc0b4d1e` | `spectre/astro/kepler.py:45` | compare | `abs(step) < _CHI_TOLERANCE -> (abs(step) <= _CHI_TOLERANCE)` | survived |
| `6e027fd567` | `spectre/astro/lambert.py:52` | number | `0 -> (1)` | survived |
| `517c640caa` | `spectre/astro/lambert.py:88` | number | `0 -> (1)` | survived |
| `9728b107ef` | `spectre/astro/lambert.py:116` | binop | `_MAX_REVOLUTIONS + 1 -> (_MAX_REVOLUTIONS - 1)` | survived |
| `4a338d1e16` | `spectre/astro/lambert.py:116` | number | `1 -> (2)` | survived |
| `6658046154` | `spectre/astro/lambert.py:162` | number | `0 -> (1)` | survived |
| `cabe7739c2` | `spectre/astro/lambert.py:162` | compare | `tof <= 0 -> (tof < 0)` | survived |
| `b3126ab82a` | `spectre/astro/lambert.py:168` | compare | `r2_mag < 1e-10 -> (r2_mag <= 1e-10)` | survived |
| `d9496f6e0a` | `spectre/astro/lambert.py:168` | compare | `r1_mag < 1e-10 -> (r1_mag <= 1e-10)` | survived |
| `4796643f7e` | `spectre/astro/lambert.py:168` | boolop | `r1_mag < 1e-10 or r2_mag < 1e-10 -> (r1_mag < 1e-10 and r2_mag < 1e-10)` | survived |
| `50de628cdf` | `spectre/astro/lambert.py:168` | number | `1e-10 -> (1.5e-10)` | survived |
| `d3d8b9313a` | `spectre/astro/lambert.py:168` | number | `1e-10 -> (1.5e-10)` | survived |
| `5e82ab0c94` | `spectre/astro/lambert.py:176` | number | `1.0 -> (1.5)` | survived |
| `209c276a38` | `spectre/astro/lambert.py:176` | number | `1.0 -> (1.5)` | survived |
| `9518229fff` | `spectre/astro/lambert.py:199` | compare | `dnu < _DEGENERATE_ANGLE_TOL_RAD -> (dnu <= _DEGENERATE_ANGLE_TOL_RAD)` | survived |
| `f4b86fd512` | `spectre/astro/lambert.py:199` | compare | `abs(dnu - math.pi) < _DEGENERATE_ANGLE_TOL_RAD -> (abs(dnu - math.pi) <= _DEGENERATE_ANGLE_TOL_RAD)` | survived |
| `7b6df9bfbf` | `spectre/astro/lambert.py:206` | compare | `abs(2.0 * math.pi - dnu) < _DEGENERATE_ANGLE_TOL_RAD -> (abs(2.0 * math.pi - dnu) <= _DEGENERATE_ANGLE_TOL_RAD)` | survived |
| `db6a89de21` | `spectre/astro/lambert.py:206` | number | `2.0 -> (3.0)` | survived |
| `d64475dd74` | `spectre/astro/lambert.py:206` | binop | `2.0 * math.pi - dnu -> (2.0 * math.pi + dnu)` | survived |
| `d7bda2ab9a` | `spectre/astro/lambert.py:216` | compare | `abs(A) < 1e-14 -> (abs(A) <= 1e-14)` | survived |
| `165691bf49` | `spectre/astro/lambert.py:216` | number | `1e-14 -> (1.5e-14)` | survived |
| `4c81bab9bf` | `spectre/astro/lambert.py:248` | number | `3 -> (4)` | survived |
| `391356dcde` | `spectre/astro/lambert.py:249` | number | `3 -> (4)` | survived |
| `61a2da9208` | `spectre/astro/lambert.py:282` | compare | `float(np.dot(cross, h_departure)) < 0.0 -> (float(np.dot(cross, h_departure)) <= 0.0)` | survived |
| `ff0db40b2b` | `spectre/astro/lambert.py:282` | number | `0.0 -> (1.0)` | survived |
| `cbc48eea0e` | `spectre/astro/lambert.py:284` | compare | `cross[2] < 0 -> (cross[2] <= 0)` | survived |
| `5507900359` | `spectre/astro/lambert.py:284` | number | `0 -> (1)` | survived |
| `366df2548d` | `spectre/astro/lambert.py:284` | compare | `cross[2] >= 0 -> (cross[2] > 0)` | survived |
| `2757eed8fa` | `spectre/astro/lambert.py:284` | number | `0 -> (1)` | survived |
| `328c2365af` | `spectre/astro/lambert.py:291` | compare | `z > 1e-6 -> (z >= 1e-06)` | survived |
| `8f48429120` | `spectre/astro/lambert.py:291` | number | `1e-6 -> (1.5e-06)` | survived |
| `7f738cfd2b` | `spectre/astro/lambert.py:294` | number | `1e-6 -> (1.5e-06)` | survived |
| `aadd8a220d` | `spectre/astro/lambert.py:294` | compare | `z < -1e-6 -> (z <= -1e-06)` | survived |
| `29ab8bad44` | `spectre/astro/lambert.py:302` | number | `1e-6 -> (1.5e-06)` | survived |
| `67abe78111` | `spectre/astro/lambert.py:302` | compare | `z > 1e-6 -> (z >= 1e-06)` | survived |
| `2c9ff95756` | `spectre/astro/lambert.py:305` | compare | `z < -1e-6 -> (z <= -1e-06)` | survived |
| `8960c8773d` | `spectre/astro/lambert.py:305` | number | `1e-6 -> (1.5e-06)` | survived |
| `3617c02dd5` | `spectre/astro/lambert.py:308` | number | `1.0 -> (1.5)` | survived |
| `faac12abe0` | `spectre/astro/lambert.py:324` | number | `0.5 -> (0.75)` | survived |
| `6e43b7182a` | `spectre/astro/lambert.py:328` | number | `5.0e5 -> (750000.0)` | survived |
| `85f609ddf1` | `spectre/astro/lambert.py:331` | number | `1e-12 -> (1.5e-12)` | survived |
| `5b79ac8fe7` | `spectre/astro/lambert.py:335` | number | `256 -> (257)` | survived |
| `a644201a54` | `spectre/astro/lambert.py:336` | number | `200 -> (201)` | survived |
| `ab88b5f261` | `spectre/astro/lambert.py:337` | number | `100 -> (101)` | survived |
| `ef57745e96` | `spectre/astro/lambert.py:338` | number | `60 -> (61)` | survived |
| `e1c204afc4` | `spectre/astro/lambert.py:376` | number | `0.0 -> (1.0)` | survived |
| `d9a20b3633` | `spectre/astro/lambert.py:376` | compare | `y <= 0.0 -> (y < 0.0)` | survived |
| `f742ae3aef` | `spectre/astro/lambert.py:377` | unary | `-math.inf -> (math.inf)` | survived |
| `dcdcaedec8` | `spectre/astro/lambert.py:386` | unary | `-math.inf -> (math.inf)` | survived |
| `2512289fc6` | `spectre/astro/lambert.py:386` | return | `return -math.inf -> return None` | survived |
| `05f55b18aa` | `spectre/astro/lambert.py:393` | number | `1e-8 -> (1.5000000000000002e-08)` | survived |
| `ee913e033a` | `spectre/astro/lambert.py:394` | number | `200 -> (201)` | survived |
| `a54bba6e5c` | `spectre/astro/lambert.py:413` | number | `1e-6 -> (1.5e-06)` | survived |
| `6e8e347e90` | `spectre/astro/lambert.py:415` | boolop | `not math.isfinite(f_hi) or f_hi < 0.0 -> (not math.isfinite(f_hi) and f_hi < 0.0)` | survived |
| `05541d6faf` | `spectre/astro/lambert.py:415` | compare | `f_hi < 0.0 -> (f_hi <= 0.0)` | survived |
| `2a07fd3cb5` | `spectre/astro/lambert.py:415` | number | `0.0 -> (1.0)` | survived |
| `1485f2ec69` | `spectre/astro/lambert.py:423` | number | `0.0 -> (1.0)` | survived |
| `0c34f1caa5` | `spectre/astro/lambert.py:425` | number | `1.0 -> (1.5)` | survived |
| `946c053006` | `spectre/astro/lambert.py:426` | compare | `f_lo >= 0.0 -> (f_lo > 0.0)` | survived |
| `dea94dfbaa` | `spectre/astro/lambert.py:426` | number | `0.0 -> (1.0)` | survived |
| `88e8578054` | `spectre/astro/lambert.py:433` | compare | `z_lo < _Z_HYPERBOLIC_FLOOR -> (z_lo <= _Z_HYPERBOLIC_FLOOR)` | survived |
| `04354520a3` | `spectre/astro/lambert.py:442` | binop | `math.sqrt(mu) * tof -> (math.sqrt(mu) / tof)` | survived |
| `b7150190b1` | `spectre/astro/lambert.py:442` | binop | `tol * max(1.0, math.sqrt(mu) * tof) -> (tol / max(1.0, math.sqrt(mu) * tof))` | survived |
| `bc975b3235` | `spectre/astro/lambert.py:442` | compare | `abs(f_mid) < tol * max(1.0, math.sqrt(mu) * tof) -> (abs(f_mid) <= tol * max(1.0, math.sqrt(mu) * tof))` | survived |
| `db834b1b6f` | `spectre/astro/lambert.py:442` | compare | `(z_hi - z_lo) < _Z_BRACKET_EPSILON -> (z_hi - z_lo <= _Z_BRACKET_EPSILON)` | survived |
| `19107b3a61` | `spectre/astro/lambert.py:442` | number | `1.0 -> (1.5)` | survived |
| `d4071ec5e8` | `spectre/astro/lambert.py:442` | boolop | `abs(f_mid) < tol * max(1.0, math.sqrt(mu) * tof) or (z_hi - z_lo) < _Z -> (abs(f_mid) < tol * max(1.0, math.sqrt(mu) * tof) and z_hi - z_lo < _Z` | survived |
| `1ea0c895e8` | `spectre/astro/lambert.py:444` | compare | `f_mid < 0.0 -> (f_mid <= 0.0)` | survived |
| `8faf49fded` | `spectre/astro/lambert.py:470` | number | `1 -> (2)` | survived |
| `a6d20878b6` | `spectre/astro/lambert.py:473` | compare | `f <= 0.0 -> (f < 0.0)` | survived |
| `9cf684b6d7` | `spectre/astro/lambert.py:473` | number | `0.0 -> (1.0)` | survived |
| `97d32c5093` | `spectre/astro/lambert.py:475` | number | `1 -> (2)` | survived |
| `c7b483d4c3` | `spectre/astro/lambert.py:475` | unary | `-1 -> (1)` | survived |
| `a1c08fbe8b` | `spectre/astro/lambert.py:477` | compare | `f_in < 0.0 -> (f_in <= 0.0)` | survived |
| `dd0e99b6d3` | `spectre/astro/lambert.py:477` | number | `0.0 -> (1.0)` | survived |
| `68cedb22bc` | `spectre/astro/lambert.py:480` | number | `0 -> (1)` | survived |
| `3f80df4ad3` | `spectre/astro/lambert.py:482` | compare | `f_a < 0.0 -> (f_a <= 0.0)` | survived |
| `7fd13635e0` | `spectre/astro/lambert.py:482` | number | `0.0 -> (1.0)` | survived |
| `0da358869b` | `spectre/astro/lambert.py:484` | compare | `f_a < 0.0 -> (f_a <= 0.0)` | survived |
| `80f2fb4689` | `spectre/astro/lambert.py:484` | number | `0.0 -> (1.0)` | survived |
| `2b918919b3` | `spectre/astro/lambert.py:484` | compare | `f_b < 0.0 -> (f_b <= 0.0)` | survived |
| `888fc84e12` | `spectre/astro/lambert.py:484` | number | `0.0 -> (1.0)` | survived |
| `7156fb315e` | `spectre/astro/lambert.py:490` | binop | `edge - z_in -> (edge + z_in)` | survived |
| `afcb558cc3` | `spectre/astro/lambert.py:492` | number | `0.5 -> (0.75)` | survived |
| `4851e9784a` | `spectre/astro/lambert.py:493` | binop | `edge - gap -> (edge + gap)` | survived |
| `0e6c0cec2b` | `spectre/astro/lambert.py:494` | compare | `f > 0.0 -> (f >= 0.0)` | survived |
| `d720d2aec3` | `spectre/astro/lambert.py:494` | number | `0.0 -> (1.0)` | survived |
| `4be699b38a` | `spectre/astro/lambert.py:494` | boolop | `math.isfinite(f) and f > 0.0 -> (math.isfinite(f) or f > 0.0)` | survived |
| `170aebc920` | `spectre/astro/lambert.py:495` | binop | `edge - gap -> (edge + gap)` | survived |
| `a344022515` | `spectre/astro/lambert.py:504` | number | `0.0 -> (1.0)` | survived |
| `4b42f2b0de` | `spectre/astro/lambert.py:504` | compare | `_time_residual(z_mid, geom, tof, mu) < 0.0 -> (_time_residual(z_mid, geom, tof, mu) <= 0.0)` | survived |
| `d095470264` | `spectre/astro/lambert.py:508` | binop | `_Z_BRACKET_EPSILON * max(1.0, z_a) -> (_Z_BRACKET_EPSILON / max(1.0, z_a))` | survived |
| `ef3d20b22a` | `spectre/astro/lambert.py:508` | compare | `z_b - z_a < _Z_BRACKET_EPSILON * max(1.0, z_a) -> (z_b - z_a <= _Z_BRACKET_EPSILON * max(1.0, z_a))` | survived |
| `f6a62aaf26` | `spectre/astro/lambert.py:508` | binop | `z_b - z_a -> (z_b + z_a)` | survived |
| `13ce900edd` | `spectre/astro/lambert.py:508` | number | `1.0 -> (1.5)` | survived |
| `5e366aab6b` | `spectre/astro/maneuvers.py:45` | number | `0.10 -> (0.15000000000000002)` | survived |
| `90f9301ae1` | `spectre/astro/maneuvers.py:46` | number | `2000 -> (2001)` | survived |
| `ac358fcced` | `spectre/astro/maneuvers.py:72` | number | `0.0 -> (1.0)` | survived |
| `8fba2927fb` | `spectre/astro/maneuvers.py:75` | number | `0.0 -> (1.0)` | survived |
| `854b3da424` | `spectre/astro/maneuvers.py:92` | number | `0.0 -> (1.0)` | survived |
| `74cbf51e51` | `spectre/astro/maneuvers.py:132` | number | `0 -> (1)` | survived |
| `73c733c5cc` | `spectre/astro/maneuvers.py:132` | compare | `target_distance_km > 0 -> (target_distance_km >= 0)` | survived |
| `d18d057379` | `spectre/astro/maneuvers.py:133` | binop | `sv_blue.r / np.linalg.norm(sv_blue.r) -> (sv_blue.r * np.linalg.norm(sv_blue.r))` | no_tests |
| `431ab705ef` | `spectre/astro/maneuvers.py:134` | binop | `r_hat * target_distance_km -> (r_hat / target_distance_km)` | no_tests |
| `958886953d` | `spectre/astro/maneuvers.py:134` | binop | `sv_blue.r - r_hat * target_distance_km -> (sv_blue.r + r_hat * target_distance_km)` | no_tests |
| `f98c666e56` | `spectre/astro/maneuvers.py:147` | number | `1 -> (2)` | survived |
| `3df88ee453` | `spectre/astro/maneuvers.py:148` | number | `2 -> (3)` | survived |
| `2c7d34ca49` | `spectre/astro/maneuvers.py:151` | number | `0.0 -> (1.0)` | survived |
| `0233e3f965` | `spectre/astro/maneuvers.py:151` | compare | `target_distance_km > 0 -> (target_distance_km >= 0)` | survived |
| `32f98b82dd` | `spectre/astro/maneuvers.py:151` | number | `0 -> (1)` | survived |
| `91111e142e` | `spectre/astro/maneuvers.py:151` | binop | `r_target - sv_blue.r -> (r_target + sv_blue.r)` | survived |
| `76588a69d2` | `spectre/astro/maneuvers.py:189` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `ab42f6e78b` | `spectre/astro/maneuvers.py:202` | compare | `r2 >= r1 -> (r2 > r1)` | survived |
| `479e9216a2` | `spectre/astro/maneuvers.py:204` | number | `1 -> (2)` | survived |
| `df245a24c5` | `spectre/astro/maneuvers.py:208` | number | `2 -> (3)` | survived |
| `aa5a137bb8` | `spectre/astro/maneuvers.py:226` | number | `0.0 -> (1.0)` | survived |
| `ae424014c8` | `spectre/astro/maneuvers.py:246` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `f5019eec36` | `spectre/astro/maneuvers.py:252` | compare | `rb_km is None -> (rb_km is not None)` | survived |
| `97be563a3a` | `spectre/astro/maneuvers.py:253` | binop | `1.5 * max(r1, r2) -> (1.5 / max(r1, r2))` | survived |
| `f4667d97b9` | `spectre/astro/maneuvers.py:253` | number | `1.5 -> (2.25)` | survived |
| `a66744a1dc` | `spectre/astro/maneuvers.py:264` | number | `1 -> (2)` | survived |
| `42def5ac8c` | `spectre/astro/maneuvers.py:270` | compare | `r2 >= r1 -> (r2 > r1)` | survived |
| `b98fd86ddb` | `spectre/astro/maneuvers.py:270` | number | `1.0 -> (1.5)` | survived |
| `da6ce7a106` | `spectre/astro/maneuvers.py:272` | number | `2 -> (3)` | survived |
| `45be82a573` | `spectre/astro/maneuvers.py:276` | number | `3 -> (4)` | survived |
| `37b26b773d` | `spectre/astro/maneuvers.py:293` | number | `1 -> (2)` | survived |
| `4c6da2092e` | `spectre/astro/maneuvers.py:294` | number | `0.0 -> (1.0)` | survived |
| `025832ee30` | `spectre/astro/maneuvers.py:313` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `e87996052e` | `spectre/astro/maneuvers.py:321` | binop | `np.dot(sv_red.r, sv_blue.r) / (r_red * r_blue) -> (np.dot(sv_red.r, sv_blue.r) * (r_red * r_blue))` | survived |
| `ab36a1cb19` | `spectre/astro/maneuvers.py:321` | binop | `r_red * r_blue -> (r_red / r_blue)` | survived |
| `1c5214af10` | `spectre/astro/maneuvers.py:322` | number | `1.0 -> (1.5)` | survived |
| `2d3ccb39c7` | `spectre/astro/maneuvers.py:322` | number | `1.0 -> (1.5)` | survived |
| `1df77f2282` | `spectre/astro/maneuvers.py:322` | unary | `-1.0 -> (1.0)` | survived |
| `0e38ebb324` | `spectre/astro/maneuvers.py:328` | compare | `float(np.dot(cross, h_red)) < 0 -> (float(np.dot(cross, h_red)) <= 0)` | survived |
| `aa4d1182b9` | `spectre/astro/maneuvers.py:328` | number | `0 -> (1)` | survived |
| `1105e6d384` | `spectre/astro/maneuvers.py:329` | number | `360.0 -> (540.0)` | survived |
| `209a85690c` | `spectre/astro/maneuvers.py:329` | binop | `360.0 - phase_deg -> (360.0 + phase_deg)` | survived |
| `5f2e90e508` | `spectre/astro/maneuvers.py:335` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `fe630e63f6` | `spectre/astro/maneuvers.py:336` | compare | `result.phasing_sma_km < r_red -> (result.phasing_sma_km <= r_red)` | survived |
| `6c237d6322` | `spectre/astro/maneuvers.py:336` | binop | `v_hat * (-result.delta_v_1 if result.phasing_sma_km < r_red else resul -> (v_hat / (-result.delta_v_1 if result.phasing_sma_km < r_red else resu` | survived |
| `a0ff7dd57a` | `spectre/astro/maneuvers.py:336` | unary | `-result.delta_v_1 -> (result.delta_v_1)` | survived |
| `aa82aab33a` | `spectre/astro/maneuvers.py:337` | number | `1 -> (2)` | survived |
| `9423ce5eec` | `spectre/astro/maneuvers.py:341` | binop | `sv_red_arr.v / sv_red_arr.v_mag -> (sv_red_arr.v * sv_red_arr.v_mag)` | survived |
| `a79fe9826d` | `spectre/astro/maneuvers.py:342` | compare | `result.phasing_sma_km < r_red -> (result.phasing_sma_km <= r_red)` | survived |
| `47090305e2` | `spectre/astro/maneuvers.py:342` | unary | `-result.delta_v_2 -> (result.delta_v_2)` | survived |
| `87b397c612` | `spectre/astro/maneuvers.py:342` | binop | `v_hat_arr * (result.delta_v_2 if result.phasing_sma_km < r_red else -r -> (v_hat_arr / (result.delta_v_2 if result.phasing_sma_km < r_red else -` | survived |
| `19efb0c5a3` | `spectre/astro/maneuvers.py:343` | number | `2 -> (3)` | survived |
| `8958308471` | `spectre/astro/maneuvers.py:345` | return | `return InterceptSolution( method="phasing", burns=[burn1, burn2], tota -> return None` | survived |
| `d5293ce635` | `spectre/astro/maneuvers.py:352` | binop | `r_red - r_blue -> (r_red + r_blue)` | survived |
| `0ad173ef71` | `spectre/astro/maneuvers.py:360` | number | `5.0 -> (7.5)` | survived |
| `f2966c442f` | `spectre/astro/maneuvers.py:361` | number | `1800.0 -> (2700.0)` | survived |
| `2fe3c972dc` | `spectre/astro/maneuvers.py:362` | number | `0.0 -> (1.0)` | survived |
| `bebe219580` | `spectre/astro/maneuvers.py:382` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `a7b12752fc` | `spectre/astro/maneuvers.py:386` | number | `2.0 -> (3.0)` | survived |
| `b9d3aebae2` | `spectre/astro/maneuvers.py:386` | binop | `sv_red.r_mag + sv_blue.r_mag -> (sv_red.r_mag - sv_blue.r_mag)` | survived |
| `8c8dd28a9c` | `spectre/astro/maneuvers.py:386` | binop | `(sv_red.r_mag + sv_blue.r_mag) / 2.0 -> ((sv_red.r_mag + sv_blue.r_mag) * 2.0)` | survived |
| `0d152fd218` | `spectre/astro/maneuvers.py:389` | binop | `t_departure + timedelta(seconds=time_s) -> (t_departure - timedelta(seconds=time_s))` | survived |
| `bb6df2d6e2` | `spectre/astro/maneuvers.py:392` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `23453b1256` | `spectre/astro/maneuvers.py:395` | number | `1 -> (2)` | survived |
| `12911aa2bf` | `spectre/astro/maneuvers.py:395` | number | `0 -> (1)` | survived |
| `adfc070e87` | `spectre/astro/maneuvers.py:395` | binop | `h / h_mag -> (h * h_mag)` | survived |
| `ddcf6884c5` | `spectre/astro/maneuvers.py:395` | number | `0 -> (1)` | survived |
| `5e2175a1fd` | `spectre/astro/maneuvers.py:395` | number | `1e-10 -> (1.5e-10)` | survived |
| `df1440029f` | `spectre/astro/maneuvers.py:395` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `55d5c527a4` | `spectre/astro/maneuvers.py:398` | binop | `b_hat * cw.delta_v_radial -> (b_hat / cw.delta_v_radial)` | survived |
| `1dcaa52ae4` | `spectre/astro/maneuvers.py:399` | number | `1 -> (2)` | survived |
| `80787c6f61` | `spectre/astro/maneuvers.py:406` | return | `return InterceptSolution( method="rbar_hop", burns=[burn1], total_delt -> return None` | survived |
| `7f635cb006` | `spectre/astro/maneuvers.py:420` | number | `10.0 -> (15.0)` | survived |
| `02b479a507` | `spectre/astro/maneuvers.py:421` | number | `3600.0 -> (5400.0)` | survived |
| `aeb7b4fcf4` | `spectre/astro/maneuvers.py:422` | number | `0.0 -> (1.0)` | survived |
| `8ae9700677` | `spectre/astro/maneuvers.py:442` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `d658566193` | `spectre/astro/maneuvers.py:446` | binop | `(sv_red.r_mag + sv_blue.r_mag) / 2.0 -> ((sv_red.r_mag + sv_blue.r_mag) * 2.0)` | survived |
| `6b61d8acc5` | `spectre/astro/maneuvers.py:446` | number | `2.0 -> (3.0)` | survived |
| `a26d0a82aa` | `spectre/astro/maneuvers.py:446` | binop | `sv_red.r_mag + sv_blue.r_mag -> (sv_red.r_mag - sv_blue.r_mag)` | survived |
| `4a93ec1fdd` | `spectre/astro/maneuvers.py:449` | binop | `t_departure + timedelta(seconds=time_s) -> (t_departure - timedelta(seconds=time_s))` | survived |
| `eaed081321` | `spectre/astro/maneuvers.py:452` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `4a767259dd` | `spectre/astro/maneuvers.py:453` | binop | `v_hat * cw.delta_v_along_track -> (v_hat / cw.delta_v_along_track)` | survived |
| `ed086cb22e` | `spectre/astro/maneuvers.py:454` | number | `1 -> (2)` | survived |
| `c9585ad6e5` | `spectre/astro/maneuvers.py:456` | return | `return InterceptSolution( method="cw_drift", burns=[burn1], total_delt -> return None` | survived |
| `1f69bfd4ec` | `spectre/astro/maneuvers.py:470` | number | `3 -> (4)` | survived |
| `5c40fb2e31` | `spectre/astro/maneuvers.py:472` | number | `0.0 -> (1.0)` | survived |
| `d0b9e21df6` | `spectre/astro/maneuvers.py:493` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `22dfc56932` | `spectre/astro/maneuvers.py:497` | binop | `(sv_red.r_mag + sv_blue.r_mag) / 2.0 -> ((sv_red.r_mag + sv_blue.r_mag) * 2.0)` | survived |
| `9f990e9eac` | `spectre/astro/maneuvers.py:497` | binop | `sv_red.r_mag + sv_blue.r_mag -> (sv_red.r_mag - sv_blue.r_mag)` | survived |
| `d2af33510f` | `spectre/astro/maneuvers.py:497` | number | `2.0 -> (3.0)` | survived |
| `20ba2d0f2f` | `spectre/astro/maneuvers.py:499` | compare | `hop_distance_km is None -> (hop_distance_km is not None)` | survived |
| `89d7ca2883` | `spectre/astro/maneuvers.py:500` | binop | `np.array(sv_blue.r) - np.array(sv_red.r) -> (np.array(sv_blue.r) + np.array(sv_red.r))` | survived |
| `2f93144714` | `spectre/astro/maneuvers.py:501` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `dc8f98c417` | `spectre/astro/maneuvers.py:503` | binop | `along_track_sep / n_hops -> (along_track_sep * n_hops)` | survived |
| `766f4c631d` | `spectre/astro/maneuvers.py:503` | number | `1.0 -> (1.5)` | survived |
| `5ba6ee20b5` | `spectre/astro/maneuvers.py:509` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `cd7a63189a` | `spectre/astro/maneuvers.py:512` | number | `0.0 -> (1.0)` | survived |
| `abc6dac23a` | `spectre/astro/maneuvers.py:512` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `12dec6fd38` | `spectre/astro/maneuvers.py:512` | binop | `h_vec / h_mag -> (h_vec * h_mag)` | survived |
| `409f526d32` | `spectre/astro/maneuvers.py:512` | number | `1.0 -> (1.5)` | survived |
| `2ac7955377` | `spectre/astro/maneuvers.py:512` | number | `1e-10 -> (1.5e-10)` | survived |
| `b548551dd8` | `spectre/astro/maneuvers.py:512` | number | `0.0 -> (1.0)` | survived |
| `cda9e5a7eb` | `spectre/astro/maneuvers.py:514` | binop | `result.delta_v_per_hop / 2.0 -> (result.delta_v_per_hop * 2.0)` | survived |
| `5c1c49d005` | `spectre/astro/maneuvers.py:514` | number | `2.0 -> (3.0)` | survived |
| `5052e17bc9` | `spectre/astro/maneuvers.py:515` | number | `1 -> (2)` | survived |
| `d5c91f9431` | `spectre/astro/maneuvers.py:515` | binop | `b_hat * dv_mag -> (b_hat / dv_mag)` | survived |
| `3be1abc9b3` | `spectre/astro/maneuvers.py:519` | binop | `sv_red_arr.v / sv_red_arr.v_mag -> (sv_red_arr.v * sv_red_arr.v_mag)` | survived |
| `692ad834f1` | `spectre/astro/maneuvers.py:522` | binop | `h_a / h_a_mag -> (h_a * h_a_mag)` | survived |
| `cbf2dd8aa1` | `spectre/astro/maneuvers.py:522` | number | `0.0 -> (1.0)` | survived |
| `4f6ada591d` | `spectre/astro/maneuvers.py:522` | number | `0.0 -> (1.0)` | survived |
| `acf918b260` | `spectre/astro/maneuvers.py:522` | number | `1e-10 -> (1.5e-10)` | survived |
| `6cba21d49a` | `spectre/astro/maneuvers.py:522` | number | `1.0 -> (1.5)` | survived |
| `ceb4bfb402` | `spectre/astro/maneuvers.py:522` | compare | `h_a_mag > 1e-10 -> (h_a_mag >= 1e-10)` | survived |
| `cee14f8ba5` | `spectre/astro/maneuvers.py:524` | unary | `-b_hat_a -> (b_hat_a)` | survived |
| `b333b7e151` | `spectre/astro/maneuvers.py:524` | binop | `-b_hat_a * dv_mag -> (-b_hat_a / dv_mag)` | survived |
| `c10d884d59` | `spectre/astro/maneuvers.py:524` | number | `2 -> (3)` | survived |
| `708e7d26bd` | `spectre/astro/maneuvers.py:526` | return | `return InterceptSolution( method="vbar_hop", burns=[burn1, burn2], tot -> return None` | survived |
| `bfa0f5bfc1` | `spectre/astro/maneuvers.py:540` | number | `3 -> (4)` | survived |
| `944802c049` | `spectre/astro/maneuvers.py:542` | number | `0.0 -> (1.0)` | survived |
| `a8eb5571c5` | `spectre/astro/maneuvers.py:563` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `ffff1ce079` | `spectre/astro/maneuvers.py:567` | number | `2.0 -> (3.0)` | survived |
| `cc55d1c0f6` | `spectre/astro/maneuvers.py:567` | binop | `sv_red.r_mag + sv_blue.r_mag -> (sv_red.r_mag - sv_blue.r_mag)` | survived |
| `1bd4212215` | `spectre/astro/maneuvers.py:567` | binop | `(sv_red.r_mag + sv_blue.r_mag) / 2.0 -> ((sv_red.r_mag + sv_blue.r_mag) * 2.0)` | survived |
| `9b3cfbae3f` | `spectre/astro/maneuvers.py:569` | compare | `hop_distance_km is None -> (hop_distance_km is not None)` | survived |
| `922ae2317b` | `spectre/astro/maneuvers.py:570` | binop | `np.array(sv_blue.r) - np.array(sv_red.r) -> (np.array(sv_blue.r) + np.array(sv_red.r))` | survived |
| `e8eec29d27` | `spectre/astro/maneuvers.py:573` | number | `0.0 -> (1.0)` | survived |
| `e58da8966f` | `spectre/astro/maneuvers.py:573` | compare | `h_mag0 > 1e-10 -> (h_mag0 >= 1e-10)` | survived |
| `6a52ff8082` | `spectre/astro/maneuvers.py:573` | number | `1.0 -> (1.5)` | survived |
| `6422f9a98e` | `spectre/astro/maneuvers.py:573` | binop | `h_vec0 / h_mag0 -> (h_vec0 * h_mag0)` | survived |
| `695d4128b9` | `spectre/astro/maneuvers.py:573` | number | `0.0 -> (1.0)` | survived |
| `c782749d6e` | `spectre/astro/maneuvers.py:573` | number | `1e-10 -> (1.5e-10)` | survived |
| `58f7ebf564` | `spectre/astro/maneuvers.py:575` | binop | `cross_track_sep / n_hops -> (cross_track_sep * n_hops)` | survived |
| `9a4d62ec07` | `spectre/astro/maneuvers.py:575` | number | `1.0 -> (1.5)` | survived |
| `3e7d733460` | `spectre/astro/maneuvers.py:583` | binop | `h_vec / h_mag -> (h_vec * h_mag)` | survived |
| `2386cef0d5` | `spectre/astro/maneuvers.py:583` | number | `0.0 -> (1.0)` | survived |
| `82dce7c45b` | `spectre/astro/maneuvers.py:583` | number | `0.0 -> (1.0)` | survived |
| `d2f984e92f` | `spectre/astro/maneuvers.py:583` | number | `1.0 -> (1.5)` | survived |
| `cdf431eacd` | `spectre/astro/maneuvers.py:583` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `d9a3e6cd03` | `spectre/astro/maneuvers.py:583` | number | `1e-10 -> (1.5e-10)` | survived |
| `0a7f68fcbb` | `spectre/astro/maneuvers.py:584` | number | `1 -> (2)` | survived |
| `5dc1bd5c5f` | `spectre/astro/maneuvers.py:584` | binop | `n_hat * result.delta_v_per_hop -> (n_hat / result.delta_v_per_hop)` | survived |
| `414f73e1ab` | `spectre/astro/maneuvers.py:590` | compare | `h_arr_mag > 1e-10 -> (h_arr_mag >= 1e-10)` | survived |
| `aa5f9dc605` | `spectre/astro/maneuvers.py:590` | number | `0.0 -> (1.0)` | survived |
| `dc88a85ed9` | `spectre/astro/maneuvers.py:590` | number | `1e-10 -> (1.5e-10)` | survived |
| `46edf596ba` | `spectre/astro/maneuvers.py:590` | binop | `h_arr / h_arr_mag -> (h_arr * h_arr_mag)` | survived |
| `0dd76dab9d` | `spectre/astro/maneuvers.py:590` | number | `1.0 -> (1.5)` | survived |
| `a69c9ccd3d` | `spectre/astro/maneuvers.py:590` | number | `0.0 -> (1.0)` | survived |
| `70ac374fa7` | `spectre/astro/maneuvers.py:591` | number | `2 -> (3)` | survived |
| `1f4dabeb96` | `spectre/astro/maneuvers.py:591` | binop | `n_hat_arr * result.delta_v_per_hop -> (n_hat_arr / result.delta_v_per_hop)` | survived |
| `feeafc3c6c` | `spectre/astro/maneuvers.py:593` | return | `return InterceptSolution( method="hbar_hop", burns=[burn1, burn2], tot -> return None` | survived |
| `dbfe120d4c` | `spectre/astro/maneuvers.py:604` | number | `1e-10 -> (1.5e-10)` | survived |
| `484ca5e62a` | `spectre/astro/maneuvers.py:606` | number | `1e-6 -> (1.5e-06)` | survived |
| `f8056227f0` | `spectre/astro/maneuvers.py:608` | number | `0.1 -> (0.15000000000000002)` | survived |
| `f0d6595d0f` | `spectre/astro/maneuvers.py:615` | number | `0.0 -> (1.0)` | survived |
| `b7baf2e43e` | `spectre/astro/maneuvers.py:615` | number | `1.0 -> (1.5)` | survived |
| `192963dd1b` | `spectre/astro/maneuvers.py:615` | compare | `h_mag > _DEGENERATE_ANGULAR_MOMENTUM -> (h_mag >= _DEGENERATE_ANGULAR_MOMENTUM)` | survived |
| `7448725797` | `spectre/astro/maneuvers.py:615` | number | `0.0 -> (1.0)` | survived |
| `6a6ef9e7dc` | `spectre/astro/maneuvers.py:630` | number | `60.0 -> (90.0)` | survived |
| `7cc27183dd` | `spectre/astro/maneuvers.py:632` | compare | `abs(f0) < _ON_PLANE_KM -> (abs(f0) <= _ON_PLANE_KM)` | survived |
| `9490a2e953` | `spectre/astro/maneuvers.py:633` | return | `return start -> return None` | survived |
| `8f847bfc6d` | `spectre/astro/maneuvers.py:635` | compare | `t0 < end -> (t0 <= end)` | survived |
| `0a7a25c625` | `spectre/astro/maneuvers.py:638` | number | `0.0 -> (1.0)` | survived |
| `5197f90776` | `spectre/astro/maneuvers.py:638` | binop | `f0 * f1 -> (f0 / f1)` | survived |
| `05652384b9` | `spectre/astro/maneuvers.py:638` | compare | `f0 * f1 <= 0.0 -> (f0 * f1 < 0.0)` | survived |
| `aceed9b8a4` | `spectre/astro/maneuvers.py:639` | compare | `(t1 - t0).total_seconds() > _CROSSING_RESOLUTION_S -> ((t1 - t0).total_seconds() >= _CROSSING_RESOLUTION_S)` | survived |
| `12d77a5d2c` | `spectre/astro/maneuvers.py:640` | number | `2 -> (3)` | survived |
| `477a4695fd` | `spectre/astro/maneuvers.py:642` | compare | `f0 * fm <= 0.0 -> (f0 * fm < 0.0)` | survived |
| `25974b1be5` | `spectre/astro/maneuvers.py:642` | number | `0.0 -> (1.0)` | survived |
| `225b8f294e` | `spectre/astro/maneuvers.py:642` | binop | `f0 * fm -> (f0 / fm)` | survived |
| `4e5b8a3503` | `spectre/astro/maneuvers.py:648` | return | `return start -> return None` | no_tests |
| `d3af4c421b` | `spectre/astro/maneuvers.py:655` | number | `0.0 -> (1.0)` | survived |
| `ac59104ba4` | `spectre/astro/maneuvers.py:673` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `5732658cab` | `spectre/astro/maneuvers.py:685` | number | `50.0 -> (75.0)` | survived |
| `3abd871d75` | `spectre/astro/maneuvers.py:685` | compare | `alt_diff < 50.0 -> (alt_diff <= 50.0)` | survived |
| `a5c5532b4b` | `spectre/astro/maneuvers.py:688` | binop | `kep_red.a**3 / mu -> (kep_red.a ** 3 * mu)` | survived |
| `7900787fda` | `spectre/astro/maneuvers.py:688` | number | `3 -> (4)` | survived |
| `55c7835af4` | `spectre/astro/maneuvers.py:688` | number | `2.0 -> (3.0)` | survived |
| `21b4d0d797` | `spectre/astro/maneuvers.py:697` | binop | `v_radial * r_hat -> (v_radial / r_hat)` | survived |
| `a53302f079` | `spectre/astro/maneuvers.py:699` | number | `1 -> (2)` | survived |
| `c9ac0ffc4e` | `spectre/astro/maneuvers.py:708` | number | `0.0 -> (1.0)` | survived |
| `981820edc5` | `spectre/astro/maneuvers.py:712` | binop | `kep_red.a**3 / mu -> (kep_red.a ** 3 * mu)` | survived |
| `8544ca2faf` | `spectre/astro/maneuvers.py:712` | number | `3 -> (4)` | survived |
| `4c546c48dd` | `spectre/astro/maneuvers.py:712` | number | `2.0 -> (3.0)` | survived |
| `ad7df67931` | `spectre/astro/maneuvers.py:741` | unary | `-1.0 -> (1.0)` | survived |
| `412e50e8d4` | `spectre/astro/maneuvers.py:741` | number | `1.0 -> (1.5)` | survived |
| `1bb2db432b` | `spectre/astro/maneuvers.py:741` | number | `1.0 -> (1.5)` | survived |
| `6e688eef0e` | `spectre/astro/maneuvers.py:749` | compare | `r2 > r1 -> (r2 >= r1)` | survived |
| `089456a7c3` | `spectre/astro/maneuvers.py:752` | number | `1 -> (2)` | survived |
| `8dd8a06b04` | `spectre/astro/maneuvers.py:754` | binop | `t_departure + timedelta(seconds=cpc.transfer_time_s) -> (t_departure - timedelta(seconds=cpc.transfer_time_s))` | survived |
| `1259fc9ff5` | `spectre/astro/maneuvers.py:758` | number | `2 -> (3)` | survived |
| `fa3348c828` | `spectre/astro/maneuvers.py:774` | number | `0.0 -> (1.0)` | survived |
| `4cf9e822cd` | `spectre/astro/maneuvers.py:797` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `a8ec1ffc76` | `spectre/astro/maneuvers.py:806` | compare | `delta_raan > 180.0 -> (delta_raan >= 180.0)` | survived |
| `17844c3848` | `spectre/astro/maneuvers.py:806` | number | `180.0 -> (270.0)` | survived |
| `a9fe14a19c` | `spectre/astro/maneuvers.py:807` | augassign | `delta_raan -= 360.0 -> delta_raan += 360.0` | no_tests |
| `4b9a8d476e` | `spectre/astro/maneuvers.py:807` | number | `360.0 -> (540.0)` | no_tests |
| `5f496611e6` | `spectre/astro/maneuvers.py:808` | compare | `delta_raan < -180.0 -> (delta_raan <= -180.0)` | survived |
| `8fcef25ead` | `spectre/astro/maneuvers.py:808` | number | `180.0 -> (270.0)` | survived |
| `112a529106` | `spectre/astro/maneuvers.py:809` | number | `360.0 -> (540.0)` | no_tests |
| `1e2737b779` | `spectre/astro/maneuvers.py:809` | augassign | `delta_raan += 360.0 -> delta_raan -= 360.0` | no_tests |
| `2e133af23b` | `spectre/astro/maneuvers.py:827` | binop | `sv_red.r_mag + result.accel_altitude_change_km -> (sv_red.r_mag - result.accel_altitude_change_km)` | survived |
| `0748a12eac` | `spectre/astro/maneuvers.py:829` | number | `0 -> (1)` | survived |
| `7a90db5189` | `spectre/astro/maneuvers.py:829` | unary | `-1.0 -> (1.0)` | survived |
| `452d2cc5e4` | `spectre/astro/maneuvers.py:829` | number | `1.0 -> (1.5)` | survived |
| `eb5faa7c9b` | `spectre/astro/maneuvers.py:829` | compare | `result.accel_altitude_change_km > 0 -> (result.accel_altitude_change_km >= 0)` | survived |
| `9882aa60a1` | `spectre/astro/maneuvers.py:829` | number | `1.0 -> (1.5)` | survived |
| `d61bd3402a` | `spectre/astro/maneuvers.py:830` | binop | `sense * hop.delta_v_1 * sv_red.v -> (sense * hop.delta_v_1 / sv_red.v)` | survived |
| `d54a07f21f` | `spectre/astro/maneuvers.py:830` | binop | `sense * hop.delta_v_1 * sv_red.v / sv_red.v_mag -> (sense * hop.delta_v_1 * sv_red.v * sv_red.v_mag)` | survived |
| `c3d224e259` | `spectre/astro/maneuvers.py:831` | binop | `t_epoch + timedelta(seconds=hop.transfer_time_s) -> (t_epoch - timedelta(seconds=hop.transfer_time_s))` | survived |
| `01961e1c20` | `spectre/astro/maneuvers.py:832` | binop | `sense * hop.delta_v_2 * sv_top.v -> (sense * hop.delta_v_2 / sv_top.v)` | survived |
| `6c95a90483` | `spectre/astro/maneuvers.py:832` | binop | `sense * hop.delta_v_2 * sv_top.v / sv_top.v_mag -> (sense * hop.delta_v_2 * sv_top.v * sv_top.v_mag)` | survived |
| `e261228d05` | `spectre/astro/maneuvers.py:832` | binop | `sense * hop.delta_v_2 -> (sense / hop.delta_v_2)` | survived |
| `3f1b57f9de` | `spectre/astro/maneuvers.py:833` | number | `1 -> (2)` | survived |
| `826a1b669c` | `spectre/astro/maneuvers.py:833` | number | `2 -> (3)` | survived |
| `5ae93eaca4` | `spectre/astro/maneuvers.py:860` | number | `1.0 -> (1.5)` | survived |
| `a96502f764` | `spectre/astro/maneuvers.py:861` | number | `3600.0 -> (5400.0)` | survived |
| `01271c006c` | `spectre/astro/maneuvers.py:862` | number | `0.0 -> (1.0)` | survived |
| `4db2dc2ff2` | `spectre/astro/maneuvers.py:882` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `78ad9f2a00` | `spectre/astro/maneuvers.py:886` | binop | `(sv_red.r_mag + sv_blue.r_mag) / 2.0 -> ((sv_red.r_mag + sv_blue.r_mag) * 2.0)` | survived |
| `d7c48945d2` | `spectre/astro/maneuvers.py:886` | binop | `sv_red.r_mag + sv_blue.r_mag -> (sv_red.r_mag - sv_blue.r_mag)` | survived |
| `6fefd8c5ac` | `spectre/astro/maneuvers.py:886` | number | `2.0 -> (3.0)` | survived |
| `073e18d1de` | `spectre/astro/maneuvers.py:889` | binop | `t_tca - timedelta(seconds=time_before_tca_s) -> (t_tca + timedelta(seconds=time_before_tca_s))` | survived |
| `fddd1800e8` | `spectre/astro/maneuvers.py:893` | binop | `sv_red_burn.v / sv_red_burn.v_mag -> (sv_red_burn.v * sv_red_burn.v_mag)` | survived |
| `ac54ba8777` | `spectre/astro/maneuvers.py:896` | number | `1e-10 -> (1.5e-10)` | survived |
| `c466641af7` | `spectre/astro/maneuvers.py:896` | number | `0 -> (1)` | survived |
| `444bfe7826` | `spectre/astro/maneuvers.py:896` | number | `1 -> (2)` | survived |
| `84ac28837d` | `spectre/astro/maneuvers.py:896` | number | `0 -> (1)` | survived |
| `7a472668ae` | `spectre/astro/maneuvers.py:896` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `c423baa73d` | `spectre/astro/maneuvers.py:896` | binop | `h / h_mag -> (h * h_mag)` | survived |
| `38bc8d4a64` | `spectre/astro/maneuvers.py:900` | compare | `best.strategy == "radial" -> (best.strategy != 'radial')` | survived |
| `19c12c21b1` | `spectre/astro/maneuvers.py:901` | binop | `b_hat * best.delta_v -> (b_hat / best.delta_v)` | no_tests |
| `d9d5a39818` | `spectre/astro/maneuvers.py:902` | compare | `best.strategy == "along_track" -> (best.strategy != 'along_track')` | survived |
| `774f615681` | `spectre/astro/maneuvers.py:903` | binop | `v_hat * best.delta_v -> (v_hat / best.delta_v)` | survived |
| `1b22bda4d9` | `spectre/astro/maneuvers.py:905` | binop | `n_hat * best.delta_v -> (n_hat / best.delta_v)` | no_tests |
| `626764b5ca` | `spectre/astro/maneuvers.py:907` | number | `1 -> (2)` | survived |
| `799ea53054` | `spectre/astro/maneuvers.py:918` | return | `return InterceptSolution( method="cola", burns=[burn1], total_delta_v= -> return None` | survived |
| `0b6cec7017` | `spectre/astro/maneuvers.py:933` | number | `0.0 -> (1.0)` | survived |
| `e65181ca91` | `spectre/astro/maneuvers.py:952` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `3af9aafd37` | `spectre/astro/maneuvers.py:959` | number | `1 -> (2)` | survived |
| `f629325655` | `spectre/astro/maneuvers.py:959` | number | `0 -> (1)` | survived |
| `b136c9d86c` | `spectre/astro/maneuvers.py:960` | number | `1 -> (2)` | survived |
| `d68e49f6a9` | `spectre/astro/maneuvers.py:960` | number | `0 -> (1)` | survived |
| `45a61f8b97` | `spectre/astro/maneuvers.py:961` | binop | `lon_blue - lon_red -> (lon_blue + lon_red)` | survived |
| `7c8dd672e7` | `spectre/astro/maneuvers.py:962` | compare | `gap > 180 -> (gap >= 180)` | survived |
| `8b350bb187` | `spectre/astro/maneuvers.py:962` | number | `180 -> (181)` | survived |
| `6da6324d21` | `spectre/astro/maneuvers.py:963` | number | `360 -> (361)` | no_tests |
| `8fc5f4c1c1` | `spectre/astro/maneuvers.py:963` | augassign | `gap -= 360 -> gap += 360` | no_tests |
| `77854c6af2` | `spectre/astro/maneuvers.py:964` | compare | `gap < -180 -> (gap <= -180)` | survived |
| `eb95eaad94` | `spectre/astro/maneuvers.py:964` | number | `180 -> (181)` | survived |
| `814ef227a4` | `spectre/astro/maneuvers.py:964` | unary | `-180 -> (180)` | survived |
| `3bc40ff48f` | `spectre/astro/maneuvers.py:965` | number | `360 -> (361)` | no_tests |
| `afd6898c32` | `spectre/astro/maneuvers.py:965` | augassign | `gap += 360 -> gap -= 360` | no_tests |
| `6bf1c42cf9` | `spectre/astro/maneuvers.py:974` | binop | `sv_red.v / sv_red.v_mag -> (sv_red.v * sv_red.v_mag)` | survived |
| `8bdce47b43` | `spectre/astro/maneuvers.py:975` | number | `1.0 -> (1.5)` | survived |
| `03d312af7c` | `spectre/astro/maneuvers.py:975` | number | `0 -> (1)` | survived |
| `fb8cc576ff` | `spectre/astro/maneuvers.py:975` | number | `1.0 -> (1.5)` | survived |
| `af8499226a` | `spectre/astro/maneuvers.py:975` | compare | `gap > 0 -> (gap >= 0)` | survived |
| `a4c64da17a` | `spectre/astro/maneuvers.py:975` | unary | `-1.0 -> (1.0)` | survived |
| `6f0ef24e1c` | `spectre/astro/maneuvers.py:976` | binop | `v_hat * result.delta_v_start * sign -> (v_hat * result.delta_v_start / sign)` | survived |
| `a90fa2c1c1` | `spectre/astro/maneuvers.py:976` | binop | `v_hat * result.delta_v_start -> (v_hat / result.delta_v_start)` | survived |
| `ade4d4f50a` | `spectre/astro/maneuvers.py:977` | number | `1 -> (2)` | survived |
| `69bed4d3ab` | `spectre/astro/maneuvers.py:981` | binop | `sv_red_arr.v / sv_red_arr.v_mag -> (sv_red_arr.v * sv_red_arr.v_mag)` | survived |
| `6542085167` | `spectre/astro/maneuvers.py:982` | binop | `v_hat_arr * result.delta_v_stop * (-sign) -> (v_hat_arr * result.delta_v_stop / -sign)` | survived |
| `d92ecb2256` | `spectre/astro/maneuvers.py:982` | binop | `v_hat_arr * result.delta_v_stop -> (v_hat_arr / result.delta_v_stop)` | survived |
| `3cb2f335ca` | `spectre/astro/maneuvers.py:982` | unary | `-sign -> (sign)` | survived |
| `4560c3189f` | `spectre/astro/maneuvers.py:983` | number | `2 -> (3)` | survived |
| `9e7f9e52f0` | `spectre/astro/maneuvers.py:1000` | number | `0.0 -> (1.0)` | survived |
| `70d3f1b8d2` | `spectre/astro/maneuvers.py:1019` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `86e416c44e` | `spectre/astro/maneuvers.py:1038` | number | `0.0 -> (1.0)` | survived |
| `756c9bec53` | `spectre/astro/maneuvers.py:1042` | binop | `sv_before.v / sv_before.v_mag -> (sv_before.v * sv_before.v_mag)` | survived |
| `c08f2352a7` | `spectre/astro/maneuvers.py:1043` | binop | `v_hat * result.estimated_delta_v -> (v_hat / result.estimated_delta_v)` | survived |
| `094ae6555a` | `spectre/astro/maneuvers.py:1044` | number | `1 -> (2)` | survived |
| `f602f8b27e` | `spectre/astro/maneuvers.py:1048` | number | `1e-6 -> (1.5e-06)` | survived |
| `58111c1651` | `spectre/astro/maneuvers.py:1048` | compare | `result.estimated_delta_v > 1e-6 -> (result.estimated_delta_v >= 1e-06)` | survived |
| `a536acaa87` | `spectre/astro/maneuvers.py:1052` | binop | `result.branch_score * 100.0 -> (result.branch_score / 100.0)` | survived |
| `1682f95e27` | `spectre/astro/maneuvers.py:1052` | number | `100.0 -> (150.0)` | survived |
| `a4ab07293d` | `spectre/astro/maneuvers.py:1062` | number | `2.0 -> (3.0)` | survived |
| `64bb8ef14b` | `spectre/astro/maneuvers.py:1063` | number | `0.0 -> (1.0)` | survived |
| `45165ff027` | `spectre/astro/maneuvers.py:1095` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `494b2f7c4b` | `spectre/astro/maneuvers.py:1098` | binop | `state.y / 2.0 -> (state.y * 2.0)` | survived |
| `0189297abd` | `spectre/astro/maneuvers.py:1098` | number | `2.0 -> (3.0)` | survived |
| `c21b8122fc` | `spectre/astro/maneuvers.py:1099` | binop | `_NMC_SIZE_TOLERANCE * along_track_km -> (_NMC_SIZE_TOLERANCE / along_track_km)` | survived |
| `a0e64c6f79` | `spectre/astro/maneuvers.py:1099` | compare | `abs(along_amp - along_track_km) > _NMC_SIZE_TOLERANCE * along_track_km -> (abs(along_amp - along_track_km) >= _NMC_SIZE_TOLERANCE * along_track_` | survived |
| `8ad79a21f7` | `spectre/astro/maneuvers.py:1109` | number | `2.0 -> (3.0)` | survived |
| `b9d5e2990b` | `spectre/astro/maneuvers.py:1109` | binop | `n * state.y / 2.0 -> (n * state.y * 2.0)` | survived |
| `b61c81c5d5` | `spectre/astro/maneuvers.py:1110` | binop | `-2.0 * n * state.x -> (-2.0 * n / state.x)` | survived |
| `6b788cc4e0` | `spectre/astro/maneuvers.py:1111` | number | `2 -> (3)` | survived |
| `e5744145f8` | `spectre/astro/maneuvers.py:1111` | binop | `cross_amp**2 -> (cross_amp * 2)` | survived |
| `0cf8f842e8` | `spectre/astro/maneuvers.py:1111` | number | `2 -> (3)` | survived |
| `c68866ad52` | `spectre/astro/maneuvers.py:1111` | binop | `state.z**2 -> (state.z * 2)` | survived |
| `e7fff45981` | `spectre/astro/maneuvers.py:1111` | binop | `cross_amp**2 - state.z**2 -> (cross_amp ** 2 + state.z ** 2)` | survived |
| `46a08123fb` | `spectre/astro/maneuvers.py:1113` | binop | `target.zd - state.zd -> (target.zd + state.zd)` | survived |
| `b676d00e38` | `spectre/astro/maneuvers.py:1113` | binop | `target.xd - state.xd -> (target.xd + state.xd)` | survived |
| `4927bbce7f` | `spectre/astro/maneuvers.py:1118` | number | `1 -> (2)` | survived |
| `384632c523` | `spectre/astro/maneuvers.py:1120` | number | `2.0 -> (3.0)` | survived |
| `cb0885d61c` | `spectre/astro/maneuvers.py:1120` | binop | `2.0 * math.pi -> (2.0 / math.pi)` | survived |
| `9d49e13366` | `spectre/astro/maneuvers.py:1120` | binop | `2.0 * math.pi / n -> (2.0 * math.pi * n)` | survived |
| `6dccbd07e7` | `spectre/astro/maneuvers.py:1122` | number | `2 -> (3)` | survived |
| `370d0ee4af` | `spectre/astro/maneuvers.py:1122` | binop | `p.x**2 + p.y**2 + p.z**2 -> (p.x ** 2 + p.y ** 2 - p.z ** 2)` | survived |
| `2f500c6f70` | `spectre/astro/maneuvers.py:1123` | binop | `period_s * k / _NMC_SAMPLES -> (period_s * k * _NMC_SAMPLES)` | survived |
| `63004da652` | `spectre/astro/maneuvers.py:1131` | binop | `t_departure + timedelta(seconds=period_s) -> (t_departure - timedelta(seconds=period_s))` | survived |
| `7bd4c8eb11` | `spectre/astro/maneuvers.py:1140` | number | `21600.0 -> (32400.0)` | survived |
| `97d7e3f493` | `spectre/astro/maneuvers.py:1141` | number | `0.0 -> (1.0)` | survived |
| `65e94c8559` | `spectre/astro/maneuvers.py:1164` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `e0552d13e1` | `spectre/astro/maneuvers.py:1166` | binop | `sv.r_mag - R_EARTH -> (sv.r_mag + R_EARTH)` | survived |
| `04d668c3ec` | `spectre/astro/maneuvers.py:1171` | binop | `det.observability_score * 100.0 -> (det.observability_score / 100.0)` | survived |
| `13fe072f8a` | `spectre/astro/maneuvers.py:1182` | number | `10.0 -> (15.0)` | survived |
| `2989047ed4` | `spectre/astro/maneuvers.py:1183` | number | `3600.0 -> (5400.0)` | survived |
| `ea42bb74fd` | `spectre/astro/maneuvers.py:1184` | number | `0.5 -> (0.75)` | survived |
| `59804a80be` | `spectre/astro/maneuvers.py:1212` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `5f3206179d` | `spectre/astro/maneuvers.py:1221` | unary | `-1.0 -> (1.0)` | survived |
| `db626c2d5e` | `spectre/astro/maneuvers.py:1221` | number | `1.0 -> (1.5)` | survived |
| `c8c0ca3d74` | `spectre/astro/maneuvers.py:1221` | number | `1.0 -> (1.5)` | survived |
| `10ed21c521` | `spectre/astro/maneuvers.py:1223` | compare | `f[1] >= desired_miss_km -> (f[1] > desired_miss_km)` | survived |
| `2b78278df8` | `spectre/astro/maneuvers.py:1250` | binop | `t_tca - timedelta(seconds=candidate.burn_epoch_offset_s) -> (t_tca + timedelta(seconds=candidate.burn_epoch_offset_s))` | survived |
| `d5647edc96` | `spectre/astro/maneuvers.py:1252` | binop | `sv.v / sv.v_mag -> (sv.v * sv.v_mag)` | survived |
| `2b7aca699c` | `spectre/astro/maneuvers.py:1256` | binop | `v_hat * candidate.prograde_dv + n_hat * candidate.normal_dv + b_hat *  -> (v_hat * candidate.prograde_dv + n_hat * candidate.normal_dv - b_hat *` | survived |
| `e7e4ebd436` | `spectre/astro/maneuvers.py:1256` | binop | `v_hat * candidate.prograde_dv + n_hat * candidate.normal_dv -> (v_hat * candidate.prograde_dv - n_hat * candidate.normal_dv)` | survived |
| `29c0693d61` | `spectre/astro/maneuvers.py:1260` | number | `1 -> (2)` | survived |
| `f5136872c1` | `spectre/astro/maneuvers.py:1267` | number | `0.0 -> (1.0)` | survived |
| `61bfdec464` | `spectre/astro/maneuvers.py:1279` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `ba00e7fb0b` | `spectre/astro/maneuvers.py:1286` | binop | `kep_blue.a - kep_red.a -> (kep_blue.a + kep_red.a)` | survived |
| `6cc767ec4e` | `spectre/astro/maneuvers.py:1288` | binop | `kep_blue.raan - kep_red.raan -> (kep_blue.raan + kep_red.raan)` | survived |
| `d724ad5371` | `spectre/astro/maneuvers.py:1289` | compare | `delta_raan > 180 -> (delta_raan >= 180)` | survived |
| `5464a2113f` | `spectre/astro/maneuvers.py:1289` | number | `180 -> (181)` | survived |
| `25e7de02eb` | `spectre/astro/maneuvers.py:1290` | augassign | `delta_raan -= 360 -> delta_raan += 360` | no_tests |
| `fbfdec7997` | `spectre/astro/maneuvers.py:1290` | number | `360 -> (361)` | no_tests |
| `6fd97acb91` | `spectre/astro/maneuvers.py:1291` | compare | `delta_raan < -180 -> (delta_raan <= -180)` | survived |
| `f5ed88c7d4` | `spectre/astro/maneuvers.py:1291` | number | `180 -> (181)` | survived |
| `9739e59bf8` | `spectre/astro/maneuvers.py:1291` | unary | `-180 -> (180)` | survived |
| `9ff6d8a730` | `spectre/astro/maneuvers.py:1292` | augassign | `delta_raan += 360 -> delta_raan -= 360` | no_tests |
| `d30d358fcf` | `spectre/astro/maneuvers.py:1292` | number | `360 -> (361)` | no_tests |
| `90ac6fdc7c` | `spectre/astro/maneuvers.py:1294` | binop | `sv_blue.r - sv_red.r -> (sv_blue.r + sv_red.r)` | survived |
| `f080fc4dd8` | `spectre/astro/maneuvers.py:1297` | number | `1e-10 -> (1.5e-10)` | survived |
| `04c7e57e5c` | `spectre/astro/maneuvers.py:1297` | binop | `float(np.dot(rel_r, rel_v)) / max(relative_range, 1e-10) -> (float(np.dot(rel_r, rel_v)) * max(relative_range, 1e-10))` | survived |
| `1e30777118` | `spectre/astro/maneuvers.py:1299` | compare | `abs(delta_raan) < 5.0 -> (abs(delta_raan) <= 5.0)` | survived |
| `f20c66e091` | `spectre/astro/maneuvers.py:1299` | number | `1.0 -> (1.5)` | survived |
| `5db3635f0f` | `spectre/astro/maneuvers.py:1299` | compare | `abs(delta_inc) < 1.0 -> (abs(delta_inc) <= 1.0)` | survived |
| `35b6082931` | `spectre/astro/maneuvers.py:1299` | number | `5.0 -> (7.5)` | survived |
| `9f9255c4da` | `spectre/astro/maneuvers.py:1368` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `53821a9f30` | `spectre/astro/maneuvers.py:1383` | number | `3600.0 -> (5400.0)` | survived |
| `2dfe64ba2c` | `spectre/astro/maneuvers.py:1437` | number | `0.0 -> (1.0)` | survived |
| `b193aa77e5` | `spectre/astro/maneuvers.py:1445` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `423688dbd2` | `spectre/astro/maneuvers.py:1462` | number | `0.0 -> (1.0)` | survived |
| `f7f653caba` | `spectre/astro/maneuvers.py:1475` | number | `0.0 -> (1.0)` | survived |
| `fbf7052792` | `spectre/astro/maneuvers.py:1487` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `f084e0b9fc` | `spectre/astro/maneuvers.py:1497` | binop | `abs(da) * math.sqrt(mu / kep_before.a**3) / 2.0 -> (abs(da) * math.sqrt(mu / kep_before.a ** 3) * 2.0)` | survived |
| `61c0ec9c35` | `spectre/astro/maneuvers.py:1497` | number | `2.0 -> (3.0)` | survived |
| `802d6059c9` | `spectre/astro/maneuvers.py:1497` | number | `3 -> (4)` | survived |
| `34cf0d09e4` | `spectre/astro/maneuvers.py:1497` | binop | `kep_before.a**3 -> (kep_before.a * 3)` | survived |
| `d89698ca37` | `spectre/astro/maneuvers.py:1499` | number | `0.1 -> (0.15000000000000002)` | survived |
| `a2bf626c1d` | `spectre/astro/maneuvers.py:1499` | compare | `abs(di) > 0.1 -> (abs(di) >= 0.1)` | survived |
| `d3c635e05f` | `spectre/astro/maneuvers.py:1501` | number | `0 -> (1)` | survived |
| `fd08da1975` | `spectre/astro/maneuvers.py:1501` | compare | `da > 0 -> (da >= 0)` | survived |
| `29d8a7056b` | `spectre/astro/maneuvers.py:1503` | number | `0 -> (1)` | survived |
| `3a1870fc9b` | `spectre/astro/maneuvers.py:1503` | compare | `da < 0 -> (da <= 0)` | survived |
| `8c57cda069` | `spectre/astro/maneuvers.py:1531` | number | `5.0 -> (7.5)` | survived |
| `1d5fcc75f7` | `spectre/astro/maneuvers.py:1532` | number | `3600.0 -> (5400.0)` | survived |
| `9fbcd0b67d` | `spectre/astro/maneuvers.py:1533` | number | `0.0 -> (1.0)` | survived |
| `f4c12777ad` | `spectre/astro/maneuvers.py:1548` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `5644dca32b` | `spectre/astro/maneuvers.py:1553` | binop | `t_tca - timedelta(seconds=tof_s) -> (t_tca + timedelta(seconds=tof_s))` | survived |
| `a12aaddcf9` | `spectre/astro/maneuvers.py:1557` | binop | `sv_blue_burn.v / sv_blue_burn.v_mag -> (sv_blue_burn.v * sv_blue_burn.v_mag)` | survived |
| `a4ec9c73ed` | `spectre/astro/maneuvers.py:1560` | number | `0 -> (1)` | survived |
| `0df1fcd5c4` | `spectre/astro/maneuvers.py:1560` | number | `1 -> (2)` | survived |
| `2e34d8f26e` | `spectre/astro/maneuvers.py:1560` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `60b8014a21` | `spectre/astro/maneuvers.py:1560` | number | `1e-10 -> (1.5e-10)` | survived |
| `2875baf0f7` | `spectre/astro/maneuvers.py:1560` | binop | `h / h_mag -> (h * h_mag)` | survived |
| `0d3633f91e` | `spectre/astro/maneuvers.py:1560` | number | `0 -> (1)` | survived |
| `6a3e529a21` | `spectre/astro/maneuvers.py:1563` | compare | `result.burn_direction == "along_track" -> (result.burn_direction != 'along_track')` | survived |
| `3069a30f46` | `spectre/astro/maneuvers.py:1564` | binop | `v_hat * result.delta_v -> (v_hat / result.delta_v)` | survived |
| `b608348609` | `spectre/astro/maneuvers.py:1565` | compare | `result.burn_direction == "radial" -> (result.burn_direction != 'radial')` | no_tests |
| `71f75918c9` | `spectre/astro/maneuvers.py:1566` | binop | `b_hat * result.delta_v -> (b_hat / result.delta_v)` | no_tests |
| `9ed8f0b8aa` | `spectre/astro/maneuvers.py:1568` | binop | `n_hat * result.delta_v -> (n_hat / result.delta_v)` | no_tests |
| `e7e69c769e` | `spectre/astro/maneuvers.py:1570` | number | `1 -> (2)` | survived |
| `91f560f7a1` | `spectre/astro/maneuvers.py:1572` | return | `return InterceptSolution( method="formation", burns=[burn1], total_del -> return None` | survived |
| `459c5d7ede` | `spectre/astro/maneuvers.py:1586` | number | `0.0 -> (1.0)` | survived |
| `857f6988e0` | `spectre/astro/maneuvers.py:1595` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `cab7f6da43` | `spectre/astro/maneuvers.py:1618` | number | `3.0 -> (4.5)` | survived |
| `ae4e10fe77` | `spectre/astro/maneuvers.py:1619` | number | `0.0 -> (1.0)` | survived |
| `6b44eedcb7` | `spectre/astro/maneuvers.py:1642` | binop | `manoeuvre_start + timedelta(seconds=coast_s) -> (manoeuvre_start - timedelta(seconds=coast_s))` | survived |
| `9a3227d700` | `spectre/astro/maneuvers.py:1644` | number | `2.0 -> (3.0)` | survived |
| `25c43b7b90` | `spectre/astro/maneuvers.py:1660` | compare | `found[0].total_delta_v <= max_delta_v -> (found[0].total_delta_v < max_delta_v)` | survived |
| `deadea7fc4` | `spectre/astro/maneuvers.py:1662` | number | `96 -> (97)` | survived |
| `82e98768d3` | `spectre/astro/maneuvers.py:1663` | number | `0.0 -> (1.0)` | survived |
| `478cb1034e` | `spectre/astro/maneuvers.py:1665` | number | `1 -> (2)` | survived |
| `953f2575fe` | `spectre/astro/maneuvers.py:1665` | number | `1 -> (2)` | survived |
| `9227986cad` | `spectre/astro/maneuvers.py:1665` | binop | `steps + 1 -> (steps - 1)` | survived |
| `c8c44e56a2` | `spectre/astro/maneuvers.py:1681` | number | `1.0 -> (1.5)` | survived |
| `bf86972149` | `spectre/astro/maneuvers.py:1681` | compare | `hi - lo > 1.0 -> (hi - lo >= 1.0)` | survived |
| `c6e32da1b1` | `spectre/astro/maneuvers.py:1691` | number | `1 -> (2)` | survived |
| `9b31bc2f8c` | `spectre/astro/maneuvers.py:1692` | number | `2 -> (3)` | survived |
| `f2b35db6e1` | `spectre/astro/maneuvers.py:1700` | number | `0.0 -> (1.0)` | survived |
| `10ef79e586` | `spectre/astro/maneuvers.py:1724` | compare | `mag < 1e-14 -> (mag <= 1e-14)` | survived |
| `b51bd50a26` | `spectre/astro/maneuvers.py:1724` | number | `1e-14 -> (1.5e-14)` | survived |
| `e285c1dfae` | `spectre/astro/maneuvers.py:1728` | number | `0 -> (1)` | survived |
| `31d5037563` | `spectre/astro/maneuvers.py:1728` | number | `1 -> (2)` | survived |
| `65b6b63729` | `spectre/astro/maneuvers.py:1728` | number | `1e-10 -> (1.5e-10)` | survived |
| `1edaa35e1f` | `spectre/astro/maneuvers.py:1728` | compare | `sv.v_mag > 1e-10 -> (sv.v_mag >= 1e-10)` | survived |
| `c57f192dd6` | `spectre/astro/maneuvers.py:1728` | number | `0 -> (1)` | survived |
| `ed5c69cdde` | `spectre/astro/maneuvers.py:1731` | number | `0 -> (1)` | survived |
| `943279ad5e` | `spectre/astro/maneuvers.py:1731` | number | `1e-10 -> (1.5e-10)` | survived |
| `a03b8ebc0e` | `spectre/astro/maneuvers.py:1731` | number | `0 -> (1)` | survived |
| `26e6bad5e6` | `spectre/astro/maneuvers.py:1731` | compare | `h_mag > 1e-10 -> (h_mag >= 1e-10)` | survived |
| `4edde8c82e` | `spectre/astro/maneuvers.py:1731` | number | `1 -> (2)` | survived |
| `bb8e99c945` | `spectre/astro/monte_carlo.py:71` | number | `7.249 -> (10.8735)` | no_tests |
| `8010bf8ffa` | `spectre/astro/monte_carlo.py:71` | number | `1.225 -> (1.8375000000000001)` | no_tests |
| `6626a7b1a4` | `spectre/astro/monte_carlo.py:71` | number | `0.0 -> (1.0)` | no_tests |
| `6b9b2ea51f` | `spectre/astro/monte_carlo.py:72` | number | `3.899e-2 -> (0.058484999999999995)` | no_tests |
| `f300a47499` | `spectre/astro/monte_carlo.py:72` | number | `25.0 -> (37.5)` | no_tests |
| `46cf5962d8` | `spectre/astro/monte_carlo.py:72` | number | `6.349 -> (9.5235)` | no_tests |
| `4498fe685b` | `spectre/astro/monte_carlo.py:73` | number | `30.0 -> (45.0)` | no_tests |
| `0116fee0fc` | `spectre/astro/monte_carlo.py:73` | number | `6.682 -> (10.023)` | no_tests |
| `a37e60c05f` | `spectre/astro/monte_carlo.py:73` | number | `1.774e-2 -> (0.026609999999999998)` | no_tests |
| `5f60e2b7b9` | `spectre/astro/monte_carlo.py:74` | number | `3.972e-3 -> (0.005958)` | no_tests |
| `6d17ab1031` | `spectre/astro/monte_carlo.py:74` | number | `40.0 -> (60.0)` | no_tests |
| `4fb5f11eb6` | `spectre/astro/monte_carlo.py:74` | number | `7.554 -> (11.331)` | no_tests |
| `a450a037b0` | `spectre/astro/monte_carlo.py:75` | number | `50.0 -> (75.0)` | no_tests |
| `a73de40719` | `spectre/astro/monte_carlo.py:75` | number | `8.382 -> (12.573)` | no_tests |
| `404ca4bd14` | `spectre/astro/monte_carlo.py:75` | number | `1.057e-3 -> (0.0015855)` | no_tests |
| `d5c1f52299` | `spectre/astro/monte_carlo.py:76` | number | `60.0 -> (90.0)` | no_tests |
| `dd50f672f1` | `spectre/astro/monte_carlo.py:76` | number | `3.206e-4 -> (0.0004809)` | no_tests |
| `8c8800dd46` | `spectre/astro/monte_carlo.py:76` | number | `7.714 -> (11.571000000000002)` | no_tests |
| `7f424052fa` | `spectre/astro/monte_carlo.py:77` | number | `70.0 -> (105.0)` | no_tests |
| `930623e2fd` | `spectre/astro/monte_carlo.py:77` | number | `8.770e-5 -> (0.00013155)` | no_tests |
| `9bcf4d1242` | `spectre/astro/monte_carlo.py:77` | number | `6.549 -> (9.823500000000001)` | no_tests |
| `2117a42411` | `spectre/astro/monte_carlo.py:78` | number | `1.905e-5 -> (2.8574999999999997e-05)` | no_tests |
| `95cc12b9a4` | `spectre/astro/monte_carlo.py:78` | number | `80.0 -> (120.0)` | no_tests |
| `d05d2b9a17` | `spectre/astro/monte_carlo.py:78` | number | `5.799 -> (8.698500000000001)` | no_tests |
| `2d74a84f2d` | `spectre/astro/monte_carlo.py:79` | number | `3.396e-6 -> (5.094000000000001e-06)` | no_tests |
| `38b66a7bfd` | `spectre/astro/monte_carlo.py:79` | number | `90.0 -> (135.0)` | no_tests |
| `d50b08201c` | `spectre/astro/monte_carlo.py:79` | number | `5.382 -> (8.073)` | no_tests |
| `a826396fa7` | `spectre/astro/monte_carlo.py:80` | number | `5.297e-7 -> (7.9455e-07)` | no_tests |
| `afc1ef44e9` | `spectre/astro/monte_carlo.py:80` | number | `100.0 -> (150.0)` | no_tests |
| `d9c139f693` | `spectre/astro/monte_carlo.py:80` | number | `5.877 -> (8.8155)` | no_tests |
| `8d0ef57212` | `spectre/astro/monte_carlo.py:81` | number | `110.0 -> (165.0)` | no_tests |
| `c1cd35e987` | `spectre/astro/monte_carlo.py:81` | number | `9.661e-8 -> (1.44915e-07)` | no_tests |
| `23b882e114` | `spectre/astro/monte_carlo.py:81` | number | `7.263 -> (10.8945)` | no_tests |
| `929116abe4` | `spectre/astro/monte_carlo.py:82` | number | `120.0 -> (180.0)` | no_tests |
| `d24a36e192` | `spectre/astro/monte_carlo.py:82` | number | `2.438e-8 -> (3.657e-08)` | no_tests |
| `bc3c6c0f9b` | `spectre/astro/monte_carlo.py:82` | number | `9.473 -> (14.209500000000002)` | no_tests |
| `48e4edfb12` | `spectre/astro/monte_carlo.py:83` | number | `8.484e-9 -> (1.2726000000000001e-08)` | no_tests |
| `2c5802a80e` | `spectre/astro/monte_carlo.py:83` | number | `12.636 -> (18.954)` | no_tests |
| `689cd1de29` | `spectre/astro/monte_carlo.py:83` | number | `130.0 -> (195.0)` | no_tests |
| `693904b49d` | `spectre/astro/monte_carlo.py:84` | number | `140.0 -> (210.0)` | no_tests |
| `b73442af33` | `spectre/astro/monte_carlo.py:84` | number | `3.845e-9 -> (5.7675e-09)` | no_tests |
| `caf9e03867` | `spectre/astro/monte_carlo.py:84` | number | `16.149 -> (24.2235)` | no_tests |
| `123969ca7b` | `spectre/astro/monte_carlo.py:85` | number | `2.070e-9 -> (3.1050000000000003e-09)` | no_tests |
| `0f9b373477` | `spectre/astro/monte_carlo.py:85` | number | `150.0 -> (225.0)` | no_tests |
| `30312103d1` | `spectre/astro/monte_carlo.py:85` | number | `22.523 -> (33.7845)` | no_tests |
| `3430dc1453` | `spectre/astro/monte_carlo.py:86` | number | `5.464e-10 -> (8.195999999999999e-10)` | no_tests |
| `8df5de2363` | `spectre/astro/monte_carlo.py:86` | number | `180.0 -> (270.0)` | no_tests |
| `f804e6edd1` | `spectre/astro/monte_carlo.py:86` | number | `29.740 -> (44.61)` | no_tests |
| `66cfc3e458` | `spectre/astro/monte_carlo.py:87` | number | `2.789e-10 -> (4.1835e-10)` | no_tests |
| `a09e7d1e9e` | `spectre/astro/monte_carlo.py:87` | number | `200.0 -> (300.0)` | no_tests |
| `b3f3838f5d` | `spectre/astro/monte_carlo.py:87` | number | `37.105 -> (55.6575)` | no_tests |
| `279a23988b` | `spectre/astro/monte_carlo.py:88` | number | `7.248e-11 -> (1.0872000000000001e-10)` | no_tests |
| `234711b2b7` | `spectre/astro/monte_carlo.py:88` | number | `45.546 -> (68.319)` | no_tests |
| `7e1a63ce3b` | `spectre/astro/monte_carlo.py:88` | number | `250.0 -> (375.0)` | no_tests |
| `e61af2b795` | `spectre/astro/monte_carlo.py:89` | number | `300.0 -> (450.0)` | no_tests |
| `0a96c265c7` | `spectre/astro/monte_carlo.py:89` | number | `2.418e-11 -> (3.627e-11)` | no_tests |
| `b4f2c5e669` | `spectre/astro/monte_carlo.py:89` | number | `53.628 -> (80.44200000000001)` | no_tests |
| `2bd775c804` | `spectre/astro/monte_carlo.py:90` | number | `350.0 -> (525.0)` | no_tests |
| `82a5b97673` | `spectre/astro/monte_carlo.py:90` | number | `9.518e-12 -> (1.4277000000000001e-11)` | no_tests |
| `337de7443d` | `spectre/astro/monte_carlo.py:90` | number | `53.298 -> (79.947)` | no_tests |
| `8f39060722` | `spectre/astro/monte_carlo.py:91` | number | `400.0 -> (600.0)` | no_tests |
| `81af347747` | `spectre/astro/monte_carlo.py:91` | number | `58.515 -> (87.77250000000001)` | no_tests |
| `c53fff66e9` | `spectre/astro/monte_carlo.py:91` | number | `3.725e-12 -> (5.5875000000000006e-12)` | no_tests |
| `fc469be3d5` | `spectre/astro/monte_carlo.py:92` | number | `1.585e-12 -> (2.3775e-12)` | no_tests |
| `5bd8a6dde4` | `spectre/astro/monte_carlo.py:92` | number | `450.0 -> (675.0)` | no_tests |
| `2b4687dbbe` | `spectre/astro/monte_carlo.py:92` | number | `60.828 -> (91.242)` | no_tests |
| `db23dd8991` | `spectre/astro/monte_carlo.py:93` | number | `63.822 -> (95.733)` | no_tests |
| `20ecaacef2` | `spectre/astro/monte_carlo.py:93` | number | `6.967e-13 -> (1.04505e-12)` | no_tests |
| `fef75068d4` | `spectre/astro/monte_carlo.py:93` | number | `500.0 -> (750.0)` | no_tests |
| `682e6fab6c` | `spectre/astro/monte_carlo.py:94` | number | `71.835 -> (107.7525)` | no_tests |
| `3591d8fc65` | `spectre/astro/monte_carlo.py:94` | number | `1.454e-13 -> (2.181e-13)` | no_tests |
| `304ea24198` | `spectre/astro/monte_carlo.py:94` | number | `600.0 -> (900.0)` | no_tests |
| `5970079e53` | `spectre/astro/monte_carlo.py:95` | number | `88.667 -> (133.0005)` | no_tests |
| `d72b66d0b0` | `spectre/astro/monte_carlo.py:95` | number | `3.614e-14 -> (5.421e-14)` | no_tests |
| `50717e99dc` | `spectre/astro/monte_carlo.py:95` | number | `700.0 -> (1050.0)` | no_tests |
| `bd722bee25` | `spectre/astro/monte_carlo.py:96` | number | `1.170e-14 -> (1.755e-14)` | no_tests |
| `fb24835d47` | `spectre/astro/monte_carlo.py:96` | number | `800.0 -> (1200.0)` | no_tests |
| `21184aeb68` | `spectre/astro/monte_carlo.py:96` | number | `124.64 -> (186.96)` | no_tests |
| `53457b7a3d` | `spectre/astro/monte_carlo.py:97` | number | `5.245e-15 -> (7.8675e-15)` | no_tests |
| `e1d95a3d3b` | `spectre/astro/monte_carlo.py:97` | number | `181.05 -> (271.57500000000005)` | no_tests |
| `9eae6cb3ab` | `spectre/astro/monte_carlo.py:97` | number | `900.0 -> (1350.0)` | no_tests |
| `ec6088dcc7` | `spectre/astro/monte_carlo.py:98` | number | `268.00 -> (402.0)` | no_tests |
| `f093e5b07c` | `spectre/astro/monte_carlo.py:98` | number | `3.019e-15 -> (4.5285e-15)` | no_tests |
| `26a98fe389` | `spectre/astro/monte_carlo.py:98` | number | `1000.0 -> (1500.0)` | no_tests |
| `0ff6345b49` | `spectre/astro/monte_carlo.py:108` | number | `0.0 -> (1.0)` | survived |
| `d04d4f9425` | `spectre/astro/monte_carlo.py:110` | compare | `h >= h_base -> (h > h_base)` | survived |
| `0b37a56c58` | `spectre/astro/monte_carlo.py:112` | number | `0 -> (1)` | no_tests |
| `41dc014cfd` | `spectre/astro/monte_carlo.py:112` | return | `return _EXPONENTIAL_ATMOSPHERE[0][1] -> return None` | no_tests |
| `1de6d064c6` | `spectre/astro/monte_carlo.py:112` | number | `1 -> (2)` | no_tests |
| `46217a808d` | `spectre/astro/monte_carlo.py:143` | number | `0.002 -> (0.003)` | survived |
| `47e2f6253c` | `spectre/astro/monte_carlo.py:144` | number | `0.10 -> (0.15000000000000002)` | survived |
| `a3ecc7d75a` | `spectre/astro/monte_carlo.py:145` | number | `1.0 -> (1.5)` | survived |
| `7e656910c0` | `spectre/astro/monte_carlo.py:146` | number | `10.0 -> (15.0)` | survived |
| `2994ae42ad` | `spectre/astro/monte_carlo.py:152` | number | `0.050 -> (0.07500000000000001)` | survived |
| `f6a0937244` | `spectre/astro/monte_carlo.py:153` | number | `0.05 -> (0.07500000000000001)` | survived |
| `5b68731e02` | `spectre/astro/monte_carlo.py:154` | number | `2.0 -> (3.0)` | survived |
| `d82113bc87` | `spectre/astro/monte_carlo.py:155` | number | `30.0 -> (45.0)` | survived |
| `94a9ed4067` | `spectre/astro/monte_carlo.py:162` | number | `0.100 -> (0.15000000000000002)` | survived |
| `b2f934c2cd` | `spectre/astro/monte_carlo.py:163` | number | `0.05 -> (0.07500000000000001)` | survived |
| `80f222b6e3` | `spectre/astro/monte_carlo.py:164` | number | `3.0 -> (4.5)` | survived |
| `b6bd8baf3b` | `spectre/astro/monte_carlo.py:165` | number | `60.0 -> (90.0)` | survived |
| `cc7494db66` | `spectre/astro/monte_carlo.py:172` | number | `0.010 -> (0.015)` | survived |
| `e920c1d91b` | `spectre/astro/monte_carlo.py:173` | number | `0.08 -> (0.12)` | survived |
| `e61b8541c4` | `spectre/astro/monte_carlo.py:174` | number | `2.0 -> (3.0)` | survived |
| `63e77c80e9` | `spectre/astro/monte_carlo.py:175` | number | `20.0 -> (30.0)` | survived |
| `3664f21377` | `spectre/astro/monte_carlo.py:182` | number | `0.200 -> (0.30000000000000004)` | survived |
| `cd81cee4ae` | `spectre/astro/monte_carlo.py:183` | number | `0.03 -> (0.045)` | survived |
| `3f571ca8f4` | `spectre/astro/monte_carlo.py:184` | number | `1.5 -> (2.25)` | survived |
| `90dfa51bd8` | `spectre/astro/monte_carlo.py:185` | number | `15.0 -> (22.5)` | survived |
| `388ccae0fe` | `spectre/astro/monte_carlo.py:197` | number | `0.002 -> (0.003)` | survived |
| `0b4fd14909` | `spectre/astro/monte_carlo.py:198` | number | `0.15 -> (0.22499999999999998)` | survived |
| `f80b95a3f7` | `spectre/astro/monte_carlo.py:199` | number | `5.0 -> (7.5)` | survived |
| `758e32f093` | `spectre/astro/monte_carlo.py:200` | number | `120.0 -> (180.0)` | survived |
| `e9a36824fa` | `spectre/astro/monte_carlo.py:207` | number | `0.080 -> (0.12)` | survived |
| `9b8060b1ff` | `spectre/astro/monte_carlo.py:208` | number | `0.05 -> (0.07500000000000001)` | survived |
| `30f1907455` | `spectre/astro/monte_carlo.py:209` | number | `2.0 -> (3.0)` | survived |
| `020142c764` | `spectre/astro/monte_carlo.py:210` | number | `30.0 -> (45.0)` | survived |
| `a06822e6ba` | `spectre/astro/monte_carlo.py:244` | number | `0.001 -> (0.0015)` | survived |
| `db8d3ae63d` | `spectre/astro/monte_carlo.py:245` | number | `2.0 -> (3.0)` | survived |
| `6425ab1195` | `spectre/astro/monte_carlo.py:246` | number | `30.0 -> (45.0)` | survived |
| `dcd5571e9e` | `spectre/astro/monte_carlo.py:247` | number | `1.0e-4 -> (0.00015000000000000001)` | survived |
| `8761f9a440` | `spectre/astro/monte_carlo.py:248` | number | `1.0e-5 -> (1.5000000000000002e-05)` | survived |
| `4d48ddc21e` | `spectre/astro/monte_carlo.py:252` | number | `500 -> (501)` | survived |
| `0e5332f298` | `spectre/astro/monte_carlo.py:253` | number | `42 -> (43)` | survived |
| `06aba0989e` | `spectre/astro/monte_carlo.py:260` | bool | `True -> (False)` | survived |
| `c799b53c94` | `spectre/astro/monte_carlo.py:278` | return | `return cls( archetype=hypothesis.archetype or "unnamed", dv_1sigma_m_s -> return None` | survived |
| `1cbca7b3c4` | `spectre/astro/monte_carlo.py:279` | boolop | `hypothesis.archetype or "unnamed" -> (hypothesis.archetype and 'unnamed')` | survived |
| `c0f421e9d9` | `spectre/astro/monte_carlo.py:280` | number | `1000.0 -> (1500.0)` | survived |
| `89770ac434` | `spectre/astro/monte_carlo.py:280` | binop | `hypothesis.delta_v_magnitude_1sigma_km_s * 1000.0 -> (hypothesis.delta_v_magnitude_1sigma_km_s / 1000.0)` | survived |
| `2dd8fe5ad6` | `spectre/astro/monte_carlo.py:333` | number | `0.0 -> (1.0)` | survived |
| `3655feec1a` | `spectre/astro/monte_carlo.py:334` | number | `0.0 -> (1.0)` | survived |
| `03ddf10407` | `spectre/astro/monte_carlo.py:335` | number | `0.0 -> (1.0)` | survived |
| `2f6d5b6925` | `spectre/astro/monte_carlo.py:336` | number | `0.0 -> (1.0)` | survived |
| `f09803ad6a` | `spectre/astro/monte_carlo.py:378` | number | `2 -> (3)` | survived |
| `65b1424e1f` | `spectre/astro/monte_carlo.py:378` | binop | `(z / r) ** 2 -> (z / r * 2)` | survived |
| `a0fdc26fa7` | `spectre/astro/monte_carlo.py:379` | number | `1.5 -> (2.25)` | survived |
| `df8c207073` | `spectre/astro/monte_carlo.py:379` | binop | `_R_E ** 2 -> (_R_E * 2)` | survived |
| `2eeb6db998` | `spectre/astro/monte_carlo.py:379` | number | `5 -> (6)` | survived |
| `053b961cdf` | `spectre/astro/monte_carlo.py:379` | binop | `-1.5 * _J2 * _MU * _R_E ** 2 -> (-1.5 * _J2 * _MU / _R_E ** 2)` | survived |
| `844b14727c` | `spectre/astro/monte_carlo.py:379` | binop | `-1.5 * _J2 * _MU -> (-1.5 * _J2 / _MU)` | survived |
| `8ca2b45c99` | `spectre/astro/monte_carlo.py:381` | binop | `1.0 - 5.0 * zr2 -> (1.0 + 5.0 * zr2)` | survived |
| `8507a2ddeb` | `spectre/astro/monte_carlo.py:381` | number | `5.0 -> (7.5)` | survived |
| `811e4999fc` | `spectre/astro/monte_carlo.py:381` | number | `1.0 -> (1.5)` | survived |
| `e434582732` | `spectre/astro/monte_carlo.py:382` | number | `5.0 -> (7.5)` | survived |
| `9ef67b4ac7` | `spectre/astro/monte_carlo.py:382` | binop | `1.0 - 5.0 * zr2 -> (1.0 + 5.0 * zr2)` | survived |
| `455fcf3d11` | `spectre/astro/monte_carlo.py:382` | number | `1.0 -> (1.5)` | survived |
| `0c427efff4` | `spectre/astro/monte_carlo.py:383` | binop | `3.0 - 5.0 * zr2 -> (3.0 + 5.0 * zr2)` | survived |
| `4eb8bd7a64` | `spectre/astro/monte_carlo.py:383` | number | `3.0 -> (4.5)` | survived |
| `0fa7406f71` | `spectre/astro/monte_carlo.py:383` | number | `5.0 -> (7.5)` | survived |
| `202edaaf18` | `spectre/astro/monte_carlo.py:389` | number | `800.0 -> (1200.0)` | survived |
| `c9d03f8eb8` | `spectre/astro/monte_carlo.py:389` | number | `0.0 -> (1.0)` | survived |
| `3323b5990d` | `spectre/astro/monte_carlo.py:389` | compare | `h_km < 800.0 -> (h_km <= 800.0)` | survived |
| `68407eac4f` | `spectre/astro/monte_carlo.py:392` | number | `0.01 -> (0.015)` | survived |
| `d9cabf4792` | `spectre/astro/monte_carlo.py:392` | compare | `v_mag > 0.01 -> (v_mag >= 0.01)` | survived |
| `65dbbf7c25` | `spectre/astro/monte_carlo.py:409` | number | `1e-12 -> (1.5e-12)` | survived |
| `ef705567cf` | `spectre/astro/monte_carlo.py:409` | number | `1e6 -> (1500000.0)` | survived |
| `17a0fa72eb` | `spectre/astro/monte_carlo.py:409` | compare | `abs(energy) > 1e-12 -> (abs(energy) >= 1e-12)` | survived |
| `e8cbc080f5` | `spectre/astro/monte_carlo.py:414` | number | `1.0 -> (1.5)` | survived |
| `b3b77dfeb3` | `spectre/astro/monte_carlo.py:414` | unary | `-1.0 -> (1.0)` | survived |
| `af5a80c998` | `spectre/astro/monte_carlo.py:414` | binop | `h_vec[2] / h -> (h_vec[2] * h)` | survived |
| `91a24eaf36` | `spectre/astro/monte_carlo.py:414` | number | `1.0 -> (1.5)` | survived |
| `2b5af40ea2` | `spectre/astro/monte_carlo.py:433` | compare | `hypothesis.distribution_type == "gaussian" -> (hypothesis.distribution_type != 'gaussian')` | survived |
| `dfbeaea763` | `spectre/astro/monte_carlo.py:458` | compare | `ric_norm < 1e-15 -> (ric_norm <= 1e-15)` | survived |
| `d4d95ed682` | `spectre/astro/monte_carlo.py:458` | number | `1e-15 -> (1.5000000000000001e-15)` | survived |
| `fef477d811` | `spectre/astro/monte_carlo.py:460` | number | `0.0 -> (1.0)` | survived |
| `3810b67b49` | `spectre/astro/monte_carlo.py:460` | number | `0.0 -> (1.0)` | survived |
| `7c5d0e25a9` | `spectre/astro/monte_carlo.py:460` | number | `1.0 -> (1.5)` | survived |
| `92efa28172` | `spectre/astro/monte_carlo.py:462` | binop | `ric / ric_norm -> (ric * ric_norm)` | survived |
| `32dc4e10eb` | `spectre/astro/monte_carlo.py:467` | binop | `2.0 * math.pi -> (2.0 / math.pi)` | survived |
| `e6069bc3ab` | `spectre/astro/monte_carlo.py:467` | number | `2.0 -> (3.0)` | survived |
| `471de50eba` | `spectre/astro/monte_carlo.py:467` | number | `0.0 -> (1.0)` | survived |
| `d4c094f100` | `spectre/astro/monte_carlo.py:471` | number | `0.9 -> (1.35)` | survived |
| `a1edbe3d44` | `spectre/astro/monte_carlo.py:471` | compare | `abs(ric_unit[0]) < 0.9 -> (abs(ric_unit[0]) <= 0.9)` | survived |
| `9aaa4d9152` | `spectre/astro/monte_carlo.py:472` | number | `0.0 -> (1.0)` | survived |
| `b6ade071ee` | `spectre/astro/monte_carlo.py:472` | number | `1.0 -> (1.5)` | survived |
| `deb4ebcfaa` | `spectre/astro/monte_carlo.py:472` | number | `0.0 -> (1.0)` | survived |
| `5fc46d0590` | `spectre/astro/monte_carlo.py:474` | number | `0.0 -> (1.0)` | survived |
| `94711ab2f7` | `spectre/astro/monte_carlo.py:474` | number | `1.0 -> (1.5)` | survived |
| `f224ff58d0` | `spectre/astro/monte_carlo.py:474` | number | `0.0 -> (1.0)` | survived |
| `ad7bfcb787` | `spectre/astro/monte_carlo.py:475` | augassign | `perp1 /= np.linalg.norm(perp1) -> perp1 *= np.linalg.norm(perp1)` | survived |
| `9d875b3023` | `spectre/astro/monte_carlo.py:485` | binop | `cos_c[:, None] * ric_unit + sin_c[:, None] * (cos_cl[:, None] * perp1  -> (cos_c[:, None] * ric_unit - sin_c[:, None] * (cos_cl[:, None] * perp1` | survived |
| `9f8271c07f` | `spectre/astro/monte_carlo.py:486` | binop | `cos_cl[:, None] * perp1 + sin_cl[:, None] * perp2 -> (cos_cl[:, None] * perp1 - sin_cl[:, None] * perp2)` | survived |
| `dbbd0a05a3` | `spectre/astro/monte_carlo.py:493` | number | `0.0 -> (1.0)` | survived |
| `f99b40be01` | `spectre/astro/monte_carlo.py:496` | number | `0.0 -> (1.0)` | survived |
| `ca8a822f6e` | `spectre/astro/monte_carlo.py:508` | number | `5.0 -> (7.5)` | survived |
| `b960110dbc` | `spectre/astro/monte_carlo.py:509` | number | `1e-8 -> (1.5000000000000002e-08)` | survived |
| `da0cac4799` | `spectre/astro/monte_carlo.py:511` | number | `1e-9 -> (1.5000000000000002e-09)` | survived |
| `f7d46a95c5` | `spectre/astro/monte_carlo.py:513` | number | `1e-12 -> (1.5e-12)` | survived |
| `4adedb8b83` | `spectre/astro/monte_carlo.py:516` | number | `1e-8 -> (1.5000000000000002e-08)` | survived |
| `50ad909413` | `spectre/astro/monte_carlo.py:517` | number | `1e-10 -> (1.5e-10)` | survived |
| `b9e93d7b0b` | `spectre/astro/monte_carlo.py:548` | number | `3 -> (4)` | survived |
| `d052e0bde9` | `spectre/astro/monte_carlo.py:549` | binop | `bstar_base + float(sample[4]) -> (bstar_base - float(sample[4]))` | survived |
| `e089515045` | `spectre/astro/monte_carlo.py:550` | number | `3600.0 -> (5400.0)` | survived |
| `2ec64ad90a` | `spectre/astro/monte_carlo.py:551` | compare | `t_burn >= horizon_s -> (t_burn > horizon_s)` | survived |
| `cdfb30cce7` | `spectre/astro/monte_carlo.py:558` | augassign | `burn_state[3:] += _ric_to_eci_rotation(burn_state[:3], burn_state[3:]) -> burn_state[3:] -= _ric_to_eci_rotation(burn_state[:3], burn_state[3:])` | survived |
| `b420e25217` | `spectre/astro/monte_carlo.py:563` | number | `3 -> (4)` | survived |
| `a15013f7eb` | `spectre/astro/monte_carlo.py:565` | binop | `float(np.linalg.norm(r_final)) - _R_E -> (float(np.linalg.norm(r_final)) + _R_E)` | survived |
| `97eebda48d` | `spectre/astro/monte_carlo.py:566` | binop | `2.0 * math.pi * math.sqrt(max(sma, 1.0) ** 3 / _MU) / 60.0 -> (2.0 * math.pi * math.sqrt(max(sma, 1.0) ** 3 / _MU) * 60.0)` | survived |
| `9dba942c5d` | `spectre/astro/monte_carlo.py:566` | binop | `2.0 * math.pi * math.sqrt(max(sma, 1.0) ** 3 / _MU) -> (2.0 * math.pi / math.sqrt(max(sma, 1.0) ** 3 / _MU))` | survived |
| `cb6832798e` | `spectre/astro/monte_carlo.py:566` | binop | `max(sma, 1.0) ** 3 / _MU -> (max(sma, 1.0) ** 3 * _MU)` | survived |
| `679cf97f1c` | `spectre/astro/monte_carlo.py:566` | number | `1.0 -> (1.5)` | survived |
| `7eb36c670d` | `spectre/astro/monte_carlo.py:566` | number | `2.0 -> (3.0)` | survived |
| `aabc5ada52` | `spectre/astro/monte_carlo.py:566` | binop | `max(sma, 1.0) ** 3 -> (max(sma, 1.0) * 3)` | survived |
| `03fcd82d70` | `spectre/astro/monte_carlo.py:566` | number | `60.0 -> (90.0)` | survived |
| `3d7834f6ec` | `spectre/astro/monte_carlo.py:566` | binop | `2.0 * math.pi -> (2.0 / math.pi)` | survived |
| `4e287bb9c9` | `spectre/astro/monte_carlo.py:566` | number | `3 -> (4)` | survived |
| `f9032f557c` | `spectre/astro/monte_carlo.py:583` | compare | `abs(span_s) < _ZERO_SPAN_S -> (abs(span_s) <= _ZERO_SPAN_S)` | survived |
| `95482231d2` | `spectre/astro/monte_carlo.py:587` | number | `0.0 -> (1.0)` | survived |
| `e3e5da212b` | `spectre/astro/monte_carlo.py:593` | bool | `False -> (True)` | survived |
| `168dd37660` | `spectre/astro/monte_carlo.py:595` | unary | `-1 -> (1)` | survived |
| `d1b7a42f1d` | `spectre/astro/monte_carlo.py:602` | number | `1.0 -> (1.5)` | survived |
| `a6d83139d8` | `spectre/astro/monte_carlo.py:603` | number | `50 -> (51)` | survived |
| `a609d6f9d8` | `spectre/astro/monte_carlo.py:604` | number | `200 -> (201)` | survived |
| `16a3b1ef76` | `spectre/astro/monte_carlo.py:605` | number | `5.0 -> (7.5)` | survived |
| `d0ae696486` | `spectre/astro/monte_carlo.py:605` | number | `50.0 -> (75.0)` | survived |
| `7416dfe7fa` | `spectre/astro/monte_carlo.py:614` | number | `0.05 -> (0.07500000000000001)` | survived |
| `ab2d3fad92` | `spectre/astro/monte_carlo.py:622` | unary | `not math.isfinite(p5_km) -> (math.isfinite(p5_km))` | survived |
| `1545a417c5` | `spectre/astro/monte_carlo.py:627` | number | `0 -> (1)` | survived |
| `ac215f280f` | `spectre/astro/monte_carlo.py:633` | compare | `arr.size < _MIN_CONVERGENCE_SAMPLES -> (arr.size <= _MIN_CONVERGENCE_SAMPLES)` | survived |
| `e79bc2f500` | `spectre/astro/monte_carlo.py:636` | number | `0 -> (1)` | survived |
| `161d895f44` | `spectre/astro/monte_carlo.py:638` | number | `2.5 -> (3.75)` | survived |
| `615f78360f` | `spectre/astro/monte_carlo.py:639` | binop | `(hi - lo) / 2.0 -> ((hi - lo) * 2.0)` | survived |
| `a9d8d20ecd` | `spectre/astro/monte_carlo.py:639` | binop | `hi - lo -> (hi + lo)` | survived |
| `62801343f2` | `spectre/astro/monte_carlo.py:639` | number | `2.0 -> (3.0)` | survived |
| `099a018641` | `spectre/astro/monte_carlo.py:643` | number | `0 -> (1)` | survived |
| `897aba637f` | `spectre/astro/monte_carlo.py:651` | compare | `percentile_half_width_km(sma_values, seed) <= tolerance_km -> (percentile_half_width_km(sma_values, seed) < tolerance_km)` | survived |
| `5f23add3f5` | `spectre/astro/monte_carlo.py:658` | number | `0 -> (1)` | survived |
| `81b3e816b1` | `spectre/astro/monte_carlo.py:659` | number | `48.0 -> (72.0)` | survived |
| `5ed8a9c40f` | `spectre/astro/monte_carlo.py:660` | number | `4 -> (5)` | survived |
| `0c64844874` | `spectre/astro/monte_carlo.py:712` | number | `3 -> (4)` | survived |
| `e131e52ec8` | `spectre/astro/monte_carlo.py:721` | number | `0.0 -> (1.0)` | survived |
| `fb8b773f01` | `spectre/astro/monte_carlo.py:722` | number | `0.0 -> (1.0)` | survived |
| `f6937f9332` | `spectre/astro/monte_carlo.py:723` | number | `1.0 -> (1.5)` | survived |
| `4b6996eade` | `spectre/astro/monte_carlo.py:724` | number | `0.0 -> (1.0)` | survived |
| `3a337b5571` | `spectre/astro/monte_carlo.py:725` | binop | `sma0 - _R_E -> (sma0 + _R_E)` | survived |
| `3f080bd127` | `spectre/astro/monte_carlo.py:725` | binop | `sma0 - _R_E -> (sma0 + _R_E)` | survived |
| `4132cf584b` | `spectre/astro/monte_carlo.py:726` | binop | `sma0 - _R_E -> (sma0 + _R_E)` | survived |
| `887b39f349` | `spectre/astro/monte_carlo.py:726` | binop | `sma0 - _R_E -> (sma0 + _R_E)` | survived |
| `8ffd5a36ac` | `spectre/astro/monte_carlo.py:727` | number | `0.0 -> (1.0)` | survived |
| `6ccd1ed988` | `spectre/astro/monte_carlo.py:727` | number | `0.0 -> (1.0)` | survived |
| `cb9dd90f88` | `spectre/astro/monte_carlo.py:728` | binop | `time.monotonic() - t_start -> (time.monotonic() + t_start)` | survived |
| `94e3ed9f4c` | `spectre/astro/monte_carlo.py:731` | binop | `sma0 - _R_E -> (sma0 + _R_E)` | survived |
| `5955373a05` | `spectre/astro/monte_carlo.py:752` | binop | `regime_counts.get(reg, 0) + 1 -> (regime_counts.get(reg, 0) - 1)` | survived |
| `edd5e9219b` | `spectre/astro/monte_carlo.py:752` | number | `0 -> (1)` | survived |
| `46693301fe` | `spectre/astro/monte_carlo.py:752` | number | `1 -> (2)` | survived |
| `1fe46a9901` | `spectre/astro/monte_carlo.py:753` | binop | `v / n_converged -> (v * n_converged)` | survived |
| `69433f86e5` | `spectre/astro/monte_carlo.py:755` | boolop | `hypothesis.random_seed or 0 -> (hypothesis.random_seed and 0)` | survived |
| `ccaa1ea51c` | `spectre/astro/monte_carlo.py:755` | number | `0 -> (1)` | survived |
| `2a0ee8812f` | `spectre/astro/monte_carlo.py:762` | compare | `half_width <= CONVERGENCE_TOLERANCE_KM -> (half_width < CONVERGENCE_TOLERANCE_KM)` | survived |
| `60dc9730ec` | `spectre/astro/monte_carlo.py:766` | number | `5 -> (6)` | survived |
| `b5becab4fe` | `spectre/astro/monte_carlo.py:767` | number | `50 -> (51)` | survived |
| `5b78c963e0` | `spectre/astro/monte_carlo.py:768` | number | `95 -> (96)` | survived |
| `229d87d3a9` | `spectre/astro/monte_carlo.py:775` | number | `5 -> (6)` | survived |
| `0eac6055f3` | `spectre/astro/monte_carlo.py:776` | number | `95 -> (96)` | survived |
| `a497e3f18f` | `spectre/astro/monte_carlo.py:779` | binop | `time.monotonic() - t_start -> (time.monotonic() + t_start)` | survived |
| `6764c2c994` | `spectre/astro/monte_carlo.py:782` | number | `50 -> (51)` | survived |
| `cc0ca2013c` | `spectre/astro/monte_carlo.py:783` | number | `5 -> (6)` | survived |
| `6c9ac1d17a` | `spectre/astro/monte_carlo.py:784` | number | `50 -> (51)` | survived |
| `cc6b7d3816` | `spectre/astro/monte_carlo.py:785` | number | `95 -> (96)` | survived |
| `3719643611` | `spectre/astro/monte_carlo.py:795` | number | `500 -> (501)` | survived |
| `004002e29c` | `spectre/astro/monte_carlo.py:820` | binop | `dv * archetype.delta_v_1sigma_fraction -> (dv / archetype.delta_v_1sigma_fraction)` | survived |
| `f56e03de92` | `spectre/astro/monte_carlo.py:820` | number | `0.0005 -> (0.00075)` | survived |
| `3bab3f1500` | `spectre/astro/monte_carlo.py:828` | binop | `dv * ric[2] -> (dv / ric[2])` | survived |
| `32853c2b6f` | `spectre/astro/monte_carlo.py:833` | number | `1e-4 -> (0.00015000000000000001)` | survived |
| `0a85384b56` | `spectre/astro/monte_carlo.py:844` | number | `1.0 -> (1.5)` | survived |
| `60a237f949` | `spectre/astro/monte_carlo.py:844` | number | `0.0 -> (1.0)` | survived |
| `026b0f9c5f` | `spectre/astro/monte_carlo.py:844` | number | `0.0 -> (1.0)` | survived |
| `724d2196dc` | `spectre/astro/monte_carlo.py:844` | compare | `along.inputs.get("delta_a_km", 0.0) < 0.0 -> (along.inputs.get('delta_a_km', 0.0) <= 0.0)` | survived |
| `55f2b56dc7` | `spectre/astro/monte_carlo.py:851` | compare | `norm < _ZERO_DV_KM_S -> (norm <= _ZERO_DV_KM_S)` | survived |
| `956e5755d7` | `spectre/astro/monte_carlo.py:900` | number | `100.0 -> (150.0)` | survived |
| `adc4ba850a` | `spectre/astro/monte_carlo.py:913` | number | `60.0 -> (90.0)` | survived |
| `d86ca993ad` | `spectre/astro/monte_carlo.py:973` | bool | `True -> (False)` | survived |
| `a18c3bd148` | `spectre/astro/monte_carlo.py:1009` | bool | `False -> (True)` | survived |
| `50e650fcaf` | `spectre/astro/monte_carlo.py:1113` | call | `_check_window(window, blue) -> pass` | survived |
| `b09f6d747d` | `spectre/astro/monte_carlo.py:1118` | binop | `1 + len(blue_burns) -> (1 - len(blue_burns))` | survived |
| `30065a5061` | `spectre/astro/monte_carlo.py:1120` | number | `0 -> (1)` | survived |
| `270ba551be` | `spectre/astro/monte_carlo.py:1120` | boolop | `hypothesis.random_seed or 0 -> (hypothesis.random_seed and 0)` | survived |
| `e6843ed62d` | `spectre/astro/monte_carlo.py:1123` | number | `3 -> (4)` | survived |
| `4086ef5561` | `spectre/astro/monte_carlo.py:1123` | binop | `burn_s + samples[:, 3] -> (burn_s - samples[:, 3])` | survived |
| `b28c21b445` | `spectre/astro/monte_carlo.py:1148` | boolop | `ran.seed or 0 -> (ran.seed and 0)` | survived |
| `b1c11c3b9e` | `spectre/astro/monte_carlo.py:1148` | number | `0 -> (1)` | survived |
| `58a28f23fd` | `spectre/astro/monte_carlo.py:1162` | binop | `time.monotonic() - ran.started -> (time.monotonic() + ran.started)` | survived |
| `780c7fcd8a` | `spectre/astro/monte_carlo.py:1179` | compare | `half_width <= tolerance -> (half_width < tolerance)` | survived |
| `68ba1b8014` | `spectre/astro/monte_carlo.py:1223` | compare | `norm >= _ZERO_DV_KM_S -> (norm > _ZERO_DV_KM_S)` | survived |
| `5c8230ec6d` | `spectre/astro/monte_carlo.py:1223` | number | `0.0 -> (1.0)` | survived |
| `9d384e1201` | `spectre/astro/monte_carlo.py:1223` | number | `1.0 -> (1.5)` | survived |
| `ce6b575f71` | `spectre/astro/monte_carlo.py:1223` | number | `0.0 -> (1.0)` | survived |
| `299943ba6b` | `spectre/astro/monte_carlo.py:1227` | number | `0.0 -> (1.0)` | survived |
| `ba6efedc6f` | `spectre/astro/monte_carlo.py:1240` | number | `0.0 -> (1.0)` | survived |
| `51dd9199fa` | `spectre/astro/monte_carlo.py:1258` | binop | `max(span_s, burn_s) - min(_earliest_s(burns_s), burn_s) -> (max(span_s, burn_s) + min(_earliest_s(burns_s), burn_s))` | survived |
| `91136a25b2` | `spectre/astro/monte_carlo.py:1259` | binop | `span_s - burns_s -> (span_s + burns_s)` | survived |
| `a4870bee94` | `spectre/astro/monte_carlo.py:1259` | number | `0.0 -> (1.0)` | survived |
| `8d47596ad9` | `spectre/astro/monte_carlo.py:1265` | number | `0.0 -> (1.0)` | survived |
| `4df77ec541` | `spectre/astro/monte_carlo.py:1270` | call | `_check_span(window) -> pass` | survived |
| `f344028a74` | `spectre/astro/monte_carlo.py:1281` | number | `0.0 -> (1.0)` | survived |
| `692a849de7` | `spectre/astro/monte_carlo.py:1281` | number | `0.0 -> (1.0)` | survived |
| `295e84bf0b` | `spectre/astro/monte_carlo.py:1281` | compare | `step > 0.0 -> (step >= 0.0)` | survived |
| `77eb868db6` | `spectre/astro/monte_carlo.py:1283` | compare | `span / step > MAX_SAMPLES - 1 -> (span / step >= MAX_SAMPLES - 1)` | survived |
| `e22da1fb4d` | `spectre/astro/monte_carlo.py:1283` | binop | `MAX_SAMPLES - 1 -> (MAX_SAMPLES + 1)` | survived |
| `af6a10d735` | `spectre/astro/monte_carlo.py:1283` | number | `1 -> (2)` | survived |
| `8ae582bbbd` | `spectre/astro/monte_carlo.py:1317` | boolop | `blue_arc is None or unburnt is None -> (blue_arc is None and unburnt is None)` | survived |
| `6f6f1364dd` | `spectre/astro/monte_carlo.py:1318` | number | `1 -> (2)` | survived |
| `2dd24b0f87` | `spectre/astro/monte_carlo.py:1318` | binop | `1 + len(blue_burns) -> (1 - len(blue_burns))` | survived |
| `20257b909c` | `spectre/astro/monte_carlo.py:1343` | number | `3 -> (4)` | survived |
| `3b8616df0e` | `spectre/astro/monte_carlo.py:1343` | binop | `float(np.linalg.norm(state[:3])) - _R_E - REENTRY_FLOOR_KM -> (float(np.linalg.norm(state[:3])) - _R_E + REENTRY_FLOOR_KM)` | survived |
| `c551a5d81e` | `spectre/astro/monte_carlo.py:1346` | bool | `True -> (False)` | survived |
| `ba5a0e269e` | `spectre/astro/monte_carlo.py:1354` | number | `0.0 -> (1.0)` | survived |
| `1cfbb4801a` | `spectre/astro/monte_carlo.py:1354` | compare | `_altitude_km(t0_s, state) < 0.0 -> (_altitude_km(t0_s, state) <= 0.0)` | survived |
| `7b05017539` | `spectre/astro/monte_carlo.py:1356` | binop | `t1_s - t0_s -> (t1_s + t0_s)` | survived |
| `6e24c40b39` | `spectre/astro/monte_carlo.py:1356` | compare | `abs(t1_s - t0_s) < _ZERO_SPAN_S -> (abs(t1_s - t0_s) <= _ZERO_SPAN_S)` | survived |
| `9d6745fd06` | `spectre/astro/monte_carlo.py:1369` | number | `1 -> (2)` | survived |
| `aaeb442ff1` | `spectre/astro/monte_carlo.py:1381` | boolop | `back is None or ahead is None -> (back is None and ahead is None)` | survived |
| `d98e4681f1` | `spectre/astro/monte_carlo.py:1388` | compare | `t < at_s -> (t <= at_s)` | survived |
| `82399bc3ca` | `spectre/astro/monte_carlo.py:1417` | return | `return _FAILED -> return None` | survived |
| `7d1c3428e6` | `spectre/astro/monte_carlo.py:1421` | return | `return _FAILED -> return None` | no_tests |
| `7e0078eb83` | `spectre/astro/monte_carlo.py:1429` | compare | `burn_s >= window.span_s -> (burn_s > window.span_s)` | survived |
| `89a68a368a` | `spectre/astro/monte_carlo.py:1433` | binop | `bstar_post + float(sample[4]) -> (bstar_post - float(sample[4]))` | survived |
| `63985c68af` | `spectre/astro/monte_carlo.py:1444` | binop | `red(approach.tca_s)[3:] - blue(approach.tca_s)[3:] -> (red(approach.tca_s)[3:] + blue(approach.tca_s)[3:])` | survived |
| `a9b1e54c39` | `spectre/astro/monte_carlo.py:1464` | boolop | `[ functools.partial(_unburnt_arc, h, 0.0, window.span_s, (h.epoch_utc  -> ([functools.partial(_unburnt_arc, h, 0.0, window.span_s, (h.epoch_utc ` | survived |
| `2d4241524a` | `spectre/astro/monte_carlo.py:1465` | number | `0.0 -> (1.0)` | survived |
| `d607cb4d96` | `spectre/astro/monte_carlo.py:1470` | compare | `None in reds -> (None not in reds)` | survived |
| `b09fcb45c3` | `spectre/astro/monte_carlo.py:1470` | compare | `blue is None -> (blue is not None)` | survived |
| `c08d4666c1` | `spectre/astro/monte_carlo.py:1470` | boolop | `blue is None or None in reds -> (blue is None and None in reds)` | survived |
| `c07d8d2da5` | `spectre/astro/monte_carlo.py:1472` | binop | `max(cast("list[float]", reds)) + blue -> (max(cast('list[float]', reds)) - blue)` | survived |
| `de0cf06503` | `spectre/astro/monte_carlo.py:1472` | return | `return max(cast("list[float]", reds)) + blue -> return None` | survived |
| `ce83a6c0c9` | `spectre/astro/monte_carlo.py:1478` | number | `0.0 -> (1.0)` | survived |
| `77dcd8ba64` | `spectre/astro/monte_carlo.py:1478` | return | `return None if start is None else _dense_arc(start.state_eci_km, 0.0,  -> return None` | survived |
| `6f7009dee2` | `spectre/astro/monte_carlo.py:1478` | compare | `start is None -> (start is not None)` | survived |
| `ef7f210acd` | `spectre/astro/monte_carlo.py:1489` | compare | `arc is None -> (arc is not None)` | survived |
| `e19c7ecd72` | `spectre/astro/monte_carlo.py:1492` | return | `return max( float(np.linalg.norm(arc(t)[:3] - orbit.propagate(window.s -> return None` | survived |
| `76e8739142` | `spectre/astro/monte_carlo.py:1493` | number | `3 -> (4)` | survived |
| `67194d6b99` | `spectre/astro/monte_carlo.py:1493` | binop | `window.start_utc + timedelta(seconds=t) -> (window.start_utc - timedelta(seconds=t))` | survived |
| `d3b25ec1f0` | `spectre/astro/monte_carlo.py:1493` | binop | `arc(t)[:3] - orbit.propagate(window.start_utc + timedelta(seconds=t)). -> (arc(t)[:3] + orbit.propagate(window.start_utc + timedelta(seconds=t))` | survived |
| `e14ee90900` | `spectre/astro/monte_carlo.py:1513` | compare | `burn.at_s <= t_s -> (burn.at_s < t_s)` | survived |
| `4151969bc8` | `spectre/astro/monte_carlo.py:1518` | compare | `burn.at_s > t_s -> (burn.at_s >= t_s)` | survived |
| `4a387fadc6` | `spectre/astro/monte_carlo.py:1580` | compare | `norm >= _ZERO_DV_KM_S -> (norm > _ZERO_DV_KM_S)` | survived |
| `50a56181fb` | `spectre/astro/monte_carlo.py:1580` | number | `0.0 -> (1.0)` | survived |
| `495da4900f` | `spectre/astro/monte_carlo.py:1580` | number | `1.0 -> (1.5)` | survived |
| `d85bd15724` | `spectre/astro/monte_carlo.py:1580` | number | `0.0 -> (1.0)` | survived |
| `06cc7435e9` | `spectre/astro/monte_carlo.py:1587` | boolop | `burn is None or draw is None -> (burn is None and draw is None)` | survived |
| `2bb92911f4` | `spectre/astro/monte_carlo.py:1590` | binop | `burn.hypothesis.bstar_post + float(draw[4]) -> (burn.hypothesis.bstar_post - float(draw[4]))` | survived |
| `2db55ce25a` | `spectre/astro/monte_carlo.py:1599` | compare | `b.at_s < span_s -> (b.at_s <= span_s)` | survived |
| `3791181808` | `spectre/astro/monte_carlo.py:1603` | compare | `arc is None -> (arc is not None)` | survived |
| `e04a003563` | `spectre/astro/monte_carlo.py:1671` | number | `0 -> (1)` | survived |
| `2f0edd7b56` | `spectre/astro/monte_carlo.py:1673` | binop | `n + len(blues) -> (n - len(blues))` | survived |
| `9a1635f6db` | `spectre/astro/monte_carlo.py:1673` | binop | `(n + len(blues)) * window.span_s -> ((n + len(blues)) / window.span_s)` | survived |
| `287a78a3dd` | `spectre/astro/notso.py:120` | number | `0 -> (1)` | survived |
| `b6295733dc` | `spectre/astro/notso.py:130` | number | `0 -> (1)` | survived |
| `9fe0bc1476` | `spectre/astro/notso.py:131` | number | `0 -> (1)` | survived |
| `09cfcb7117` | `spectre/astro/notso.py:136` | bool | `False -> (True)` | survived |
| `22bece8b6f` | `spectre/astro/notso.py:137` | bool | `False -> (True)` | survived |
| `8d06918f14` | `spectre/astro/notso.py:138` | bool | `False -> (True)` | survived |
| `659a7c57c1` | `spectre/astro/notso.py:139` | bool | `False -> (True)` | survived |
| `7a701cd517` | `spectre/astro/notso.py:140` | bool | `False -> (True)` | survived |
| `deab701b38` | `spectre/astro/notso.py:162` | call | `parts.append( f"{self.below_reporting_threshold} sat below it and woul -> pass` | no_tests |
| `33d5c12e18` | `spectre/astro/notso.py:167` | call | `parts.append( f"Mean notification lead time: {self.mean_lead_time_h:.1 -> pass` | no_tests |
| `e7a9609ea5` | `spectre/astro/notso.py:168` | binop | `f"Mean notification lead time: {self.mean_lead_time_h:.1f}h" + (f" ± { -> (f'Mean notification lead time: {self.mean_lead_time_h:.1f}h' - (f' ± ` | no_tests |
| `5d1d853016` | `spectre/astro/notso.py:171` | number | `0 -> (1)` | survived |
| `f330e16f5c` | `spectre/astro/notso.py:171` | compare | `self.notso_without_detection_count > 0 -> (self.notso_without_detection_count >= 0)` | survived |
| `e7bf39af0e` | `spectre/astro/notso.py:172` | call | `parts.append( f"{self.notso_without_detection_count} NOTSO(s) have no  -> pass` | survived |
| `0361860c79` | `spectre/astro/notso.py:179` | call | `parts.append("Timing is predictable (low lead-time variance).") -> pass` | no_tests |
| `796fcdbb35` | `spectre/astro/notso.py:180` | return | `return " ".join(parts) -> return None` | survived |
| `e947fb8b64` | `spectre/astro/notso.py:217` | compare | `max(int(slash.group(1)), int(slash.group(2))) <= 12 -> (max(int(slash.group(1)), int(slash.group(2))) < 12)` | survived |
| `9ede3f799a` | `spectre/astro/notso.py:217` | number | `12 -> (13)` | survived |
| `cb218d6c95` | `spectre/astro/notso.py:217` | number | `1 -> (2)` | survived |
| `9a9be69466` | `spectre/astro/notso.py:295` | compare | `1 <= val <= 999999 -> (1 <= val < 999999)` | survived |
| `7faf68617c` | `spectre/astro/notso.py:295` | compare | `1 <= val <= 999999 -> (1 < val <= 999999)` | survived |
| `7679677052` | `spectre/astro/notso.py:295` | number | `999999 -> (1000000)` | survived |
| `d0e3848ad9` | `spectre/astro/notso.py:295` | number | `1 -> (2)` | survived |
| `a953bac18e` | `spectre/astro/notso.py:300` | bool | `False -> (True)` | survived |
| `8991029b83` | `spectre/astro/notso.py:312` | number | `0 -> (1)` | survived |
| `f346d678e9` | `spectre/astro/notso.py:312` | call | `patterns.insert(0, r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m/s\|km/s)") -> pass` | survived |
| `053f064f1f` | `spectre/astro/notso.py:349` | bool | `True -> (False)` | survived |
| `cc336a950b` | `spectre/astro/notso.py:394` | call | `rejects.append(f"message {i + 1}: parse error") -> pass` | no_tests |
| `6b6deece67` | `spectre/astro/notso.py:419` | call | `inferred.append("issue date") -> pass` | survived |
| `852895228c` | `spectre/astro/notso.py:420` | boolop | `_extract_datetime(text) or datetime.now(UTC) -> (_extract_datetime(text) and datetime.now(UTC))` | survived |
| `80fffdd8c3` | `spectre/astro/notso.py:429` | boolop | `_extract_datetime(text) or issue_dt -> (_extract_datetime(text) and issue_dt)` | survived |
| `25cc92d014` | `spectre/astro/notso.py:485` | boolop | `fields.get("PREDICTED DV") or fields.get("DELTA-V") -> (fields.get('PREDICTED DV') and fields.get('DELTA-V'))` | survived |
| `4a29ba0916` | `spectre/astro/notso.py:486` | bool | `True -> (False)` | survived |
| `45585883bd` | `spectre/astro/notso.py:490` | number | `0 -> (1)` | survived |
| `aa17722d3d` | `spectre/astro/notso.py:506` | boolop | `fields.get("ISSUER") or fields.get("ISSUED BY") or fields.get("OPERATO -> (fields.get('ISSUER') and fields.get('ISSUED BY') and fields.get('OPER` | survived |
| `fd028ebd38` | `spectre/astro/notso.py:519` | number | `500 -> (501)` | survived |
| `e31cadf71a` | `spectre/astro/notso.py:525` | boolop | `fields.get("DIRECTION") or fields.get("BURN DIRECTION") or None -> (fields.get('DIRECTION') and fields.get('BURN DIRECTION') and None)` | survived |
| `0a671bb318` | `spectre/astro/notso.py:531` | boolop | `fields.get("INTL DESIG") or fields.get("COSPAR") or None -> (fields.get('INTL DESIG') and fields.get('COSPAR') and None)` | survived |
| `82ffc5f12e` | `spectre/astro/notso.py:532` | boolop | `fields.get("OBJECT NAME") or fields.get("OBJECT") or None -> (fields.get('OBJECT NAME') and fields.get('OBJECT') and None)` | survived |
| `5bd1eea038` | `spectre/astro/notso.py:552` | number | `24.0 -> (36.0)` | survived |
| `39d681d333` | `spectre/astro/notso.py:579` | compare | `m.tle_after.sma_km > 0 -> (m.tle_after.sma_km >= 0)` | survived |
| `75a4bb7c24` | `spectre/astro/notso.py:579` | number | `0 -> (1)` | survived |
| `d31373d765` | `spectre/astro/notso.py:617` | number | `1e-9 -> (1.5000000000000002e-09)` | survived |
| `fb8bb5f959` | `spectre/astro/notso.py:621` | number | `2 -> (3)` | survived |
| `e8b23338b8` | `spectre/astro/notso.py:621` | binop | `notso.effective_start_utc + (notso.effective_end_utc - notso.effective -> (notso.effective_start_utc - (notso.effective_end_utc - notso.effectiv` | survived |
| `e65608daf4` | `spectre/astro/notso.py:621` | binop | `(notso.effective_end_utc - notso.effective_start_utc) / 2 -> ((notso.effective_end_utc - notso.effective_start_utc) * 2)` | survived |
| `852b2b4a8d` | `spectre/astro/notso.py:635` | compare | `hi >= window_start -> (hi > window_start)` | survived |
| `1d12cbea2d` | `spectre/astro/notso.py:635` | compare | `lo <= window_end -> (lo < window_end)` | survived |
| `bb4f547d60` | `spectre/astro/notso.py:640` | number | `3 -> (4)` | survived |
| `a2b4422cfc` | `spectre/astro/notso.py:653` | compare | `best.delta_v_km_s > _MIN_DETECTED_DV_KM_S -> (best.delta_v_km_s >= _MIN_DETECTED_DV_KM_S)` | survived |
| `70dce0577b` | `spectre/astro/notso.py:659` | number | `2 -> (3)` | survived |
| `bef2f02301` | `spectre/astro/notso.py:660` | number | `3 -> (4)` | survived |
| `3799c2a4de` | `spectre/astro/notso.py:661` | number | `2 -> (3)` | survived |
| `2bb9a11f3b` | `spectre/astro/notso.py:681` | number | `6.0 -> (9.0)` | survived |
| `95081a5d1c` | `spectre/astro/notso.py:685` | number | `2 -> (3)` | survived |
| `6aa8248575` | `spectre/astro/notso.py:694` | number | `0.30 -> (0.44999999999999996)` | survived |
| `ceda0a030e` | `spectre/astro/notso.py:698` | number | `0.0 -> (1.0)` | survived |
| `6e1b5d6f43` | `spectre/astro/notso.py:698` | number | `0.0 -> (1.0)` | survived |
| `96b5e59b48` | `spectre/astro/notso.py:713` | number | `0 -> (1)` | survived |
| `a325a1dae6` | `spectre/astro/notso.py:715` | compare | `_dv(c) >= reportable_threshold_km_s -> (_dv(c) > reportable_threshold_km_s)` | survived |
| `3c45b4a024` | `spectre/astro/notso.py:716` | compare | `_dv(c) >= reportable_threshold_km_s -> (_dv(c) > reportable_threshold_km_s)` | survived |
| `cebfbd56b7` | `spectre/astro/notso.py:717` | binop | `len(matched) + len(mnv_only) - len(reportable_matched) -> (len(matched) + len(mnv_only) + len(reportable_matched))` | survived |
| `6c79d847a1` | `spectre/astro/notso.py:717` | binop | `len(matched) + len(mnv_only) - len(reportable_matched) - len(reportabl -> (len(matched) + len(mnv_only) - len(reportable_matched) + len(reportab` | survived |
| `ba8a224bea` | `spectre/astro/notso.py:726` | boolop | `len(values) >= _MIN_SAMPLES_FOR_STD and mean is not None -> (len(values) >= _MIN_SAMPLES_FOR_STD or mean is not None)` | survived |
| `f2ae1c1216` | `spectre/astro/notso.py:726` | compare | `mean is not None -> (mean is None)` | survived |
| `cf99050b88` | `spectre/astro/notso.py:726` | compare | `len(values) >= _MIN_SAMPLES_FOR_STD -> (len(values) > _MIN_SAMPLES_FOR_STD)` | survived |
| `f2d67a0be3` | `spectre/astro/notso.py:729` | binop | `(x - _mean) ** 2 -> ((x - _mean) * 2)` | survived |
| `82504260fd` | `spectre/astro/notso.py:729` | number | `1 -> (2)` | survived |
| `a1050356e9` | `spectre/astro/notso.py:729` | binop | `sum((x - _mean) ** 2 for x in values) / (len(values) - 1) -> (sum(((x - _mean) ** 2 for x in values)) * (len(values) - 1))` | survived |
| `47056f7f30` | `spectre/astro/notso.py:729` | binop | `len(values) - 1 -> (len(values) + 1)` | survived |
| `53890fea2c` | `spectre/astro/notso.py:729` | binop | `x - _mean -> (x + _mean)` | survived |
| `4358d1df35` | `spectre/astro/notso.py:729` | number | `2 -> (3)` | survived |
| `683975f061` | `spectre/astro/notso.py:744` | boolop | `c.notso and c.manoeuvre and mnv_epoch is not None and c.notso.effectiv -> (c.notso or c.manoeuvre or mnv_epoch is not None or (c.notso.effective` | survived |
| `9d5324ea00` | `spectre/astro/notso.py:747` | compare | `c.notso.effective_start_utc <= mnv_epoch <= c.notso.effective_end_utc -> (c.notso.effective_start_utc <= mnv_epoch < c.notso.effective_end_utc)` | survived |
| `1c31c5af06` | `spectre/astro/notso.py:747` | compare | `c.notso.effective_start_utc <= mnv_epoch <= c.notso.effective_end_utc -> (c.notso.effective_start_utc < mnv_epoch <= c.notso.effective_end_utc)` | survived |
| `0eb645d262` | `spectre/astro/notso.py:750` | number | `0.0 -> (1.0)` | survived |
| `1ce545dbff` | `spectre/astro/notso.py:759` | binop | `undetected_types.get(t, 0) + 1 -> (undetected_types.get(t, 0) - 1)` | survived |
| `58b7dd8e68` | `spectre/astro/notso.py:759` | number | `0 -> (1)` | survived |
| `258be33dc1` | `spectre/astro/notso.py:759` | number | `1 -> (2)` | survived |
| `168c1eaed0` | `spectre/astro/notso.py:760` | return | `return undetected_types -> return None` | survived |
| `915a6544bc` | `spectre/astro/notso.py:774` | number | `3 -> (4)` | survived |
| `1d964617ce` | `spectre/astro/notso.py:806` | number | `0.0 -> (1.0)` | survived |
| `aff4cb39fc` | `spectre/astro/notso.py:806` | number | `0 -> (1)` | survived |
| `3e74997632` | `spectre/astro/notso.py:807` | compare | `reportable >= min_reportable_for_behaviour -> (reportable > min_reportable_for_behaviour)` | survived |
| `52dce9e35e` | `spectre/astro/notso.py:831` | number | `4 -> (5)` | survived |
| `800d4ac7fc` | `spectre/astro/notso.py:832` | number | `2 -> (3)` | survived |
| `d5f2d75631` | `spectre/astro/notso.py:833` | number | `2 -> (3)` | survived |
| `91804bc130` | `spectre/astro/notso.py:834` | number | `2 -> (3)` | survived |
| `98d93a9b02` | `spectre/astro/notso.py:835` | number | `2 -> (3)` | survived |
| `f2340348fc` | `spectre/astro/notso.py:836` | number | `3 -> (4)` | survived |
| `5b2a633390` | `spectre/astro/notso.py:837` | number | `3 -> (4)` | survived |
| `cdf836e74b` | `spectre/astro/notso.py:838` | number | `4 -> (5)` | survived |
| `2883e6bf5d` | `spectre/astro/notso.py:845` | boolop | `assessable and notif_rate > _CONSISTENT_NOTIFIER_RATE -> (assessable or notif_rate > _CONSISTENT_NOTIFIER_RATE)` | survived |
| `665e0e6881` | `spectre/astro/notso.py:845` | compare | `notif_rate > _CONSISTENT_NOTIFIER_RATE -> (notif_rate >= _CONSISTENT_NOTIFIER_RATE)` | survived |
| `39cecb8d31` | `spectre/astro/notso.py:846` | boolop | `assessable and _LOW_NOTIFIER_RATE <= notif_rate <= _CONSISTENT_NOTIFIE -> (assessable or _LOW_NOTIFIER_RATE <= notif_rate <= _CONSISTENT_NOTIFIE` | survived |
| `da0d6be697` | `spectre/astro/notso.py:847` | compare | `_LOW_NOTIFIER_RATE <= notif_rate <= _CONSISTENT_NOTIFIER_RATE -> (_LOW_NOTIFIER_RATE < notif_rate <= _CONSISTENT_NOTIFIER_RATE)` | survived |
| `1b013d340b` | `spectre/astro/notso.py:847` | compare | `_LOW_NOTIFIER_RATE <= notif_rate <= _CONSISTENT_NOTIFIER_RATE -> (_LOW_NOTIFIER_RATE <= notif_rate < _CONSISTENT_NOTIFIER_RATE)` | survived |
| `e4742d9d78` | `spectre/astro/notso.py:848` | compare | `notif_rate < _LOW_NOTIFIER_RATE -> (notif_rate <= _LOW_NOTIFIER_RATE)` | survived |
| `175df51b06` | `spectre/astro/notso.py:849` | compare | `std_lt < _PREDICTABLE_LEAD_STD_H -> (std_lt <= _PREDICTABLE_LEAD_STD_H)` | survived |
| `9ae214670f` | `spectre/astro/pattern_of_life.py:83` | number | `180.0 -> (270.0)` | survived |
| `aa3e3de60f` | `spectre/astro/pattern_of_life.py:94` | number | `0.002 -> (0.003)` | survived |
| `7ba6ec3b01` | `spectre/astro/pattern_of_life.py:100` | number | `30.0 -> (45.0)` | survived |
| `2a110e14a9` | `spectre/astro/pattern_of_life.py:106` | number | `0.25 -> (0.375)` | survived |
| `1ea2628c22` | `spectre/astro/pattern_of_life.py:122` | number | `500 -> (501)` | survived |
| `02b1d6d5ec` | `spectre/astro/pattern_of_life.py:123` | number | `0.05 -> (0.07500000000000001)` | survived |
| `e768d12ef4` | `spectre/astro/pattern_of_life.py:124` | number | `0.20 -> (0.30000000000000004)` | survived |
| `37d39d3506` | `spectre/astro/pattern_of_life.py:133` | number | `3 -> (4)` | survived |
| `aaebd2d071` | `spectre/astro/pattern_of_life.py:181` | number | `0 -> (1)` | survived |
| `eca1568dc1` | `spectre/astro/pattern_of_life.py:230` | unary | `not bd.swept.burn_epoch_ambiguous -> (bd.swept.burn_epoch_ambiguous)` | survived |
| `dfad973c28` | `spectre/astro/pattern_of_life.py:230` | compare | `bd.burn_epoch is not None -> (bd.burn_epoch is None)` | survived |
| `d861e08061` | `spectre/astro/pattern_of_life.py:349` | number | `0 -> (1)` | survived |
| `e2b9151503` | `spectre/astro/pattern_of_life.py:350` | number | `0 -> (1)` | survived |
| `ae3eb7e2ad` | `spectre/astro/pattern_of_life.py:351` | number | `0 -> (1)` | survived |
| `2c22c34db8` | `spectre/astro/pattern_of_life.py:352` | number | `0 -> (1)` | survived |
| `6e74f2e6c7` | `spectre/astro/pattern_of_life.py:353` | number | `0 -> (1)` | survived |
| `56908894de` | `spectre/astro/pattern_of_life.py:354` | number | `0 -> (1)` | survived |
| `d18248ef53` | `spectre/astro/pattern_of_life.py:355` | number | `0 -> (1)` | survived |
| `21601bcef6` | `spectre/astro/pattern_of_life.py:356` | number | `0 -> (1)` | survived |
| `d281953f8c` | `spectre/astro/pattern_of_life.py:357` | number | `0 -> (1)` | survived |
| `a32791e071` | `spectre/astro/pattern_of_life.py:358` | number | `0 -> (1)` | survived |
| `4dd1743205` | `spectre/astro/pattern_of_life.py:370` | number | `32 -> (33)` | survived |
| `1f54b6ccdc` | `spectre/astro/pattern_of_life.py:372` | binop | `1900 + yy -> (1900 - yy)` | survived |
| `70e742d96e` | `spectre/astro/pattern_of_life.py:372` | compare | `yy < 57 -> (yy <= 57)` | survived |
| `477f8d30e7` | `spectre/astro/pattern_of_life.py:372` | number | `1900 -> (1901)` | survived |
| `5a4baee247` | `spectre/astro/pattern_of_life.py:372` | number | `57 -> (58)` | survived |
| `fd37d32b48` | `spectre/astro/pattern_of_life.py:411` | binop | `math.degrees(math.atan2(r[1], r[0])) - _gmst_deg(epoch + timedelta(day -> (math.degrees(math.atan2(r[1], r[0])) + _gmst_deg(epoch + timedelta(da` | survived |
| `96674a10e5` | `spectre/astro/pattern_of_life.py:411` | binop | `epoch + timedelta(days=days) -> (epoch - timedelta(days=days))` | survived |
| `f86c8e7fa6` | `spectre/astro/pattern_of_life.py:412` | number | `360.0 -> (540.0)` | survived |
| `5e1a9b6a79` | `spectre/astro/pattern_of_life.py:412` | binop | `lons[1] - lons[0] + 180.0 -> (lons[1] - lons[0] - 180.0)` | survived |
| `69c40d07a9` | `spectre/astro/pattern_of_life.py:422` | unary | `-1 -> (1)` | survived |
| `61195e6349` | `spectre/astro/pattern_of_life.py:431` | binop | `2.0 * math.pi / n_rad_min -> (2.0 * math.pi * n_rad_min)` | survived |
| `af42dfdfdf` | `spectre/astro/pattern_of_life.py:431` | number | `2.0 -> (3.0)` | survived |
| `0e8482d7ca` | `spectre/astro/pattern_of_life.py:431` | binop | `2.0 * math.pi -> (2.0 / math.pi)` | survived |
| `f9048567db` | `spectre/astro/pattern_of_life.py:435` | number | `360.0 -> (540.0)` | survived |
| `2b502286ef` | `spectre/astro/pattern_of_life.py:436` | number | `360.0 -> (540.0)` | survived |
| `0103932b04` | `spectre/astro/pattern_of_life.py:437` | binop | `math.degrees(sat.mo) % 360.0 -> (math.degrees(sat.mo) * 360.0)` | survived |
| `8b76c8d526` | `spectre/astro/pattern_of_life.py:437` | number | `360.0 -> (540.0)` | survived |
| `9ab5ac7ddb` | `spectre/astro/pattern_of_life.py:438` | binop | `sma - R_EARTH -> (sma + R_EARTH)` | survived |
| `2baaf9e4f8` | `spectre/astro/pattern_of_life.py:440` | number | `24 -> (25)` | survived |
| `7adee7171c` | `spectre/astro/pattern_of_life.py:440` | binop | `2 * math.pi -> (2 / math.pi)` | survived |
| `39079bb3e7` | `spectre/astro/pattern_of_life.py:440` | number | `2 -> (3)` | survived |
| `a641984553` | `spectre/astro/pattern_of_life.py:440` | binop | `n_rad_min * 60 -> (n_rad_min / 60)` | survived |
| `79ac9369e7` | `spectre/astro/pattern_of_life.py:440` | binop | `n_rad_min * 60 * 24 / (2 * math.pi) -> (n_rad_min * 60 * 24 * (2 * math.pi))` | survived |
| `6877dda1b4` | `spectre/astro/pattern_of_life.py:440` | binop | `n_rad_min * 60 * 24 -> (n_rad_min * 60 / 24)` | survived |
| `f659fdbd03` | `spectre/astro/pattern_of_life.py:440` | number | `60 -> (61)` | survived |
| `3d9c4ffa5f` | `spectre/astro/pattern_of_life.py:445` | boolop | `abs(inc_deg) < 15.0 and alt_km > 30000.0 -> (abs(inc_deg) < 15.0 or alt_km > 30000.0)` | survived |
| `96173d2d3b` | `spectre/astro/pattern_of_life.py:445` | number | `30000.0 -> (45000.0)` | survived |
| `c8fa7fb3b2` | `spectre/astro/pattern_of_life.py:445` | compare | `abs(inc_deg) < 15.0 -> (abs(inc_deg) <= 15.0)` | survived |
| `807387dddf` | `spectre/astro/pattern_of_life.py:445` | number | `15.0 -> (22.5)` | survived |
| `0a855617e2` | `spectre/astro/pattern_of_life.py:445` | compare | `regime in ("GEO", "DEEP") -> (regime not in ('GEO', 'DEEP'))` | survived |
| `8dcbb745d7` | `spectre/astro/pattern_of_life.py:445` | boolop | `regime in ("GEO", "DEEP") or (abs(inc_deg) < 15.0 and alt_km > 30000.0 -> (regime in ('GEO', 'DEEP') and (abs(inc_deg) < 15.0 and alt_km > 30000` | survived |
| `80e17da13e` | `spectre/astro/pattern_of_life.py:445` | compare | `alt_km > 30000.0 -> (alt_km >= 30000.0)` | survived |
| `1c630cff80` | `spectre/astro/pattern_of_life.py:446` | binop | `raan_deg + argp_deg + ma_deg -> (raan_deg + argp_deg - ma_deg)` | survived |
| `6749a92817` | `spectre/astro/pattern_of_life.py:446` | binop | `(raan_deg + argp_deg + ma_deg) % 360.0 -> ((raan_deg + argp_deg + ma_deg) * 360.0)` | survived |
| `ef2ad16aa3` | `spectre/astro/pattern_of_life.py:446` | binop | `raan_deg + argp_deg -> (raan_deg - argp_deg)` | survived |
| `a25619fdad` | `spectre/astro/pattern_of_life.py:446` | number | `360.0 -> (540.0)` | survived |
| `18da612b7c` | `spectre/astro/pattern_of_life.py:448` | binop | `mean_lon_eci - gst -> (mean_lon_eci + gst)` | survived |
| `604a22c8b0` | `spectre/astro/pattern_of_life.py:448` | number | `360.0 -> (540.0)` | survived |
| `ba38317937` | `spectre/astro/pattern_of_life.py:448` | binop | `(mean_lon_eci - gst) % 360.0 -> ((mean_lon_eci - gst) * 360.0)` | survived |
| `5c22da1d9d` | `spectre/astro/pattern_of_life.py:449` | compare | `lon > _LONGITUDE_WRAP_DEG -> (lon >= _LONGITUDE_WRAP_DEG)` | survived |
| `fb693de42b` | `spectre/astro/pattern_of_life.py:449` | number | `360.0 -> (540.0)` | survived |
| `aef01bdd0b` | `spectre/astro/pattern_of_life.py:449` | binop | `lon - 360.0 -> (lon + 360.0)` | survived |
| `39b807769c` | `spectre/astro/pattern_of_life.py:454` | number | `2 -> (3)` | survived |
| `d222e193fa` | `spectre/astro/pattern_of_life.py:454` | number | `68 -> (69)` | survived |
| `c0fc371a34` | `spectre/astro/pattern_of_life.py:454` | number | `64 -> (65)` | survived |
| `4f984433f3` | `spectre/astro/pattern_of_life.py:454` | unary | `-2 -> (2)` | survived |
| `c665424f85` | `spectre/astro/pattern_of_life.py:456` | number | `0 -> (1)` | no_tests |
| `b86d0ae86c` | `spectre/astro/pattern_of_life.py:471` | binop | `b - a + 180.0 -> (b - a - 180.0)` | survived |
| `1f85d8bad6` | `spectre/astro/pattern_of_life.py:522` | boolop | `not attributed or (len(keys) < _MIN_DISTINCT_SOURCES_TO_SPLIT) -> (not attributed and len(keys) < _MIN_DISTINCT_SOURCES_TO_SPLIT)` | survived |
| `d9e036c45c` | `spectre/astro/pattern_of_life.py:535` | binop | `(rec.epoch - prev.epoch).total_seconds() / 86400.0 -> ((rec.epoch - prev.epoch).total_seconds() * 86400.0)` | survived |
| `cafb0053c6` | `spectre/astro/pattern_of_life.py:535` | number | `86400.0 -> (129600.0)` | survived |
| `edd1e8043e` | `spectre/astro/pattern_of_life.py:537` | call | `pairs.sort(key=lambda t: t[1].epoch) -> pass` | survived |
| `efd77b79ec` | `spectre/astro/pattern_of_life.py:568` | number | `1 -> (2)` | survived |
| `83086b3e19` | `spectre/astro/pattern_of_life.py:568` | number | `3 -> (4)` | survived |
| `63ef3bfc9f` | `spectre/astro/pattern_of_life.py:568` | number | `2 -> (3)` | survived |
| `0caca1b3ef` | `spectre/astro/pattern_of_life.py:568` | number | `0 -> (1)` | survived |
| `96dbe0275e` | `spectre/astro/pattern_of_life.py:575` | compare | `abs((b.burn_epoch - a.burn_epoch).total_seconds()) / 86400.0 <= window -> (abs((b.burn_epoch - a.burn_epoch).total_seconds()) / 86400.0 < window` | survived |
| `487b50af8f` | `spectre/astro/pattern_of_life.py:575` | number | `86400.0 -> (129600.0)` | survived |
| `770ab715de` | `spectre/astro/pattern_of_life.py:602` | number | `3 -> (4)` | survived |
| `1c472d42c2` | `spectre/astro/pattern_of_life.py:624` | number | `0.6 -> (0.8999999999999999)` | survived |
| `9162b2a1bd` | `spectre/astro/pattern_of_life.py:630` | number | `0.5 -> (0.75)` | survived |
| `04a560bced` | `spectre/astro/pattern_of_life.py:635` | number | `0.05 -> (0.07500000000000001)` | survived |
| `ae39b22cc7` | `spectre/astro/pattern_of_life.py:654` | compare | `top.dv_km_s / total >= _DOMINANT_CHANNEL_SHARE -> (top.dv_km_s / total > _DOMINANT_CHANNEL_SHARE)` | survived |
| `ec63fa462c` | `spectre/astro/pattern_of_life.py:654` | compare | `total > 0 -> (total >= 0)` | survived |
| `ddbf2e4364` | `spectre/astro/pattern_of_life.py:654` | boolop | `total > 0 and top.dv_km_s / total >= _DOMINANT_CHANNEL_SHARE -> (total > 0 or top.dv_km_s / total >= _DOMINANT_CHANNEL_SHARE)` | survived |
| `bcbd6e4b69` | `spectre/astro/pattern_of_life.py:656` | return | `return "mixed" -> return None` | no_tests |
| `6688d1874d` | `spectre/astro/pattern_of_life.py:658` | number | `100 -> (101)` | survived |
| `50ae165af5` | `spectre/astro/pattern_of_life.py:658` | binop | `abs(d_inc) * 100 -> (abs(d_inc) / 100)` | survived |
| `f739ccb4d0` | `spectre/astro/pattern_of_life.py:659` | binop | `abs(d_ecc) * 1000 -> (abs(d_ecc) / 1000)` | survived |
| `84fa3654bd` | `spectre/astro/pattern_of_life.py:659` | number | `1000 -> (1001)` | survived |
| `2a2dcff024` | `spectre/astro/pattern_of_life.py:660` | compare | `v < _ELEMENT_SCORE_FLOOR -> (v <= _ELEMENT_SCORE_FLOOR)` | survived |
| `47f64b710d` | `spectre/astro/pattern_of_life.py:662` | compare | `abs(d_inc) > _PLANE_CHANGE_INC_DEG -> (abs(d_inc) >= _PLANE_CHANGE_INC_DEG)` | survived |
| `b613f88a13` | `spectre/astro/pattern_of_life.py:662` | compare | `abs(d_inc) > abs(d_alt) * 0.1 -> (abs(d_inc) >= abs(d_alt) * 0.1)` | survived |
| `834510c984` | `spectre/astro/pattern_of_life.py:662` | number | `0.1 -> (0.15000000000000002)` | survived |
| `e973d58569` | `spectre/astro/pattern_of_life.py:662` | binop | `abs(d_alt) * 0.1 -> (abs(d_alt) / 0.1)` | survived |
| `e83445e85e` | `spectre/astro/pattern_of_life.py:662` | boolop | `abs(d_inc) > _PLANE_CHANGE_INC_DEG and abs(d_inc) > abs(d_alt) * 0.1 -> (abs(d_inc) > _PLANE_CHANGE_INC_DEG or abs(d_inc) > abs(d_alt) * 0.1)` | survived |
| `168d0e854f` | `spectre/astro/pattern_of_life.py:672` | number | `1 -> (2)` | survived |
| `997a86ea18` | `spectre/astro/pattern_of_life.py:672` | binop | `int(idx) + 1 -> (int(idx) - 1)` | survived |
| `2c00d0d2c8` | `spectre/astro/pattern_of_life.py:672` | number | `1 -> (2)` | survived |
| `3a6411473d` | `spectre/astro/pattern_of_life.py:673` | binop | `s[lo] + (s[hi] - s[lo]) * (idx - lo) -> (s[lo] - (s[hi] - s[lo]) * (idx - lo))` | survived |
| `40840871cc` | `spectre/astro/pattern_of_life.py:673` | binop | `s[hi] - s[lo] -> (s[hi] + s[lo])` | survived |
| `7a3316fb91` | `spectre/astro/pattern_of_life.py:681` | number | `95 -> (96)` | survived |
| `83cb345e27` | `spectre/astro/pattern_of_life.py:681` | number | `5 -> (6)` | survived |
| `6aadbc2097` | `spectre/astro/pattern_of_life.py:682` | number | `2 -> (3)` | survived |
| `83bae77304` | `spectre/astro/pattern_of_life.py:682` | number | `2 -> (3)` | survived |
| `d68053011e` | `spectre/astro/pattern_of_life.py:685` | number | `500 -> (501)` | survived |
| `55825ac2b8` | `spectre/astro/pattern_of_life.py:686` | compare | `len(records) <= max_pts -> (len(records) < max_pts)` | survived |
| `efe2750981` | `spectre/astro/pattern_of_life.py:689` | binop | `i * step -> (i / step)` | survived |
| `43fdd8eeee` | `spectre/astro/pattern_of_life.py:696` | compare | `rate > _DRIFT_STATIONARY -> (rate >= _DRIFT_STATIONARY)` | survived |
| `ad3e2afcb3` | `spectre/astro/pattern_of_life.py:698` | unary | `-_DRIFT_STATIONARY -> (_DRIFT_STATIONARY)` | survived |
| `5051b755b4` | `spectre/astro/pattern_of_life.py:698` | compare | `rate < -_DRIFT_STATIONARY -> (rate <= -_DRIFT_STATIONARY)` | survived |
| `afabd65255` | `spectre/astro/pattern_of_life.py:699` | return | `return "WEST" -> return None` | no_tests |
| `e50dd36804` | `spectre/astro/pattern_of_life.py:700` | return | `return "STATIONARY" -> return None` | survived |
| `840a24086b` | `spectre/astro/pattern_of_life.py:705` | number | `86400.0 -> (129600.0)` | survived |
| `e01f61c11d` | `spectre/astro/pattern_of_life.py:705` | binop | `(end.epoch - start.epoch).total_seconds() / 86400.0 -> ((end.epoch - start.epoch).total_seconds() * 86400.0)` | survived |
| `054ff7ea58` | `spectre/astro/pattern_of_life.py:706` | compare | `dur < 0.5 -> (dur <= 0.5)` | survived |
| `b13e69189d` | `spectre/astro/pattern_of_life.py:706` | number | `0.5 -> (0.75)` | survived |
| `e155821abb` | `spectre/astro/pattern_of_life.py:708` | binop | `sum(rates) / len(rates) -> (sum(rates) * len(rates))` | survived |
| `9fccb91584` | `spectre/astro/pattern_of_life.py:711` | number | `3 -> (4)` | survived |
| `cf3781feed` | `spectre/astro/pattern_of_life.py:712` | number | `0.0 -> (1.0)` | survived |
| `e712067292` | `spectre/astro/pattern_of_life.py:712` | number | `0.0 -> (1.0)` | survived |
| `9a5cf5e965` | `spectre/astro/pattern_of_life.py:712` | boolop | `start.geo_longitude_deg or 0.0 -> (start.geo_longitude_deg and 0.0)` | survived |
| `c7f8a195d1` | `spectre/astro/pattern_of_life.py:712` | boolop | `end.geo_longitude_deg or 0.0 -> (end.geo_longitude_deg and 0.0)` | survived |
| `a09d2f2192` | `spectre/astro/pattern_of_life.py:712` | number | `2 -> (3)` | survived |
| `ccd252ed62` | `spectre/astro/pattern_of_life.py:712` | number | `2 -> (3)` | survived |
| `ca1bccd075` | `spectre/astro/pattern_of_life.py:713` | number | `2 -> (3)` | survived |
| `0851aeed68` | `spectre/astro/pattern_of_life.py:713` | binop | `mean_rate * dur -> (mean_rate / dur)` | survived |
| `a7d25d4815` | `spectre/astro/pattern_of_life.py:713` | number | `1 -> (2)` | survived |
| `602f38d262` | `spectre/astro/pattern_of_life.py:714` | number | `3 -> (4)` | survived |
| `78e8ba50f8` | `spectre/astro/pattern_of_life.py:725` | number | `0 -> (1)` | survived |
| `9c2d42e7ce` | `spectre/astro/pattern_of_life.py:726` | boolop | `start.geo_drift_rate_deg_day or 0.0 -> (start.geo_drift_rate_deg_day and 0.0)` | survived |
| `8fe701d5a0` | `spectre/astro/pattern_of_life.py:726` | number | `0.0 -> (1.0)` | survived |
| `bb770c4d49` | `spectre/astro/pattern_of_life.py:728` | number | `1 -> (2)` | survived |
| `da0d4a111c` | `spectre/astro/pattern_of_life.py:729` | boolop | `rec.geo_drift_rate_deg_day or 0.0 -> (rec.geo_drift_rate_deg_day and 0.0)` | survived |
| `7f74610399` | `spectre/astro/pattern_of_life.py:729` | number | `0.0 -> (1.0)` | survived |
| `e01b3147ce` | `spectre/astro/pattern_of_life.py:730` | compare | `_drift_direction(rate) == direction -> (_drift_direction(rate) != direction)` | survived |
| `db9f5ad9da` | `spectre/astro/pattern_of_life.py:731` | call | `rates.append(rate) -> pass` | survived |
| `cfd18276f1` | `spectre/astro/pattern_of_life.py:733` | call | `runs.append((start, rec, rates, direction)) -> pass` | no_tests |
| `b5fa7a93fc` | `spectre/astro/pattern_of_life.py:735` | unary | `-1 -> (1)` | survived |
| `95546aa246` | `spectre/astro/pattern_of_life.py:735` | number | `1 -> (2)` | survived |
| `eba2d66afd` | `spectre/astro/pattern_of_life.py:741` | boolop | `r.geo_longitude_deg is not None and r.geo_drift_rate_deg_day is not No -> (r.geo_longitude_deg is not None or r.geo_drift_rate_deg_day is not No` | survived |
| `1c68070de6` | `spectre/astro/pattern_of_life.py:742` | compare | `len(geo_recs) < 3 -> (len(geo_recs) <= 3)` | survived |
| `4f4b6e3d81` | `spectre/astro/pattern_of_life.py:742` | number | `3 -> (4)` | survived |
| `54090a8ac5` | `spectre/astro/pattern_of_life.py:764` | boolop | `line.startswith("1 ") and len(line) >= _TLE_LINE_COLUMNS and following -> (line.startswith('1 ') or len(line) >= _TLE_LINE_COLUMNS or following.` | survived |
| `75fd1ff9b3` | `spectre/astro/pattern_of_life.py:783` | number | `0 -> (1)` | survived |
| `f6a15f189a` | `spectre/astro/pattern_of_life.py:784` | number | `0 -> (1)` | survived |
| `c202532dc3` | `spectre/astro/pattern_of_life.py:839` | return | `return False -> return None` | survived |
| `c7284d86e9` | `spectre/astro/pattern_of_life.py:923` | number | `0 -> (1)` | survived |
| `ac3c325dfd` | `spectre/astro/pattern_of_life.py:925` | compare | `gap > _MAX_GAP_DAYS -> (gap >= _MAX_GAP_DAYS)` | survived |
| `8b4feb5cf3` | `spectre/astro/pattern_of_life.py:926` | number | `1 -> (2)` | survived |
| `437d317f05` | `spectre/astro/pattern_of_life.py:926` | augassign | `skipped_long_gap += 1 -> skipped_long_gap -= 1` | survived |
| `8af08db12d` | `spectre/astro/pattern_of_life.py:947` | compare | `rank < _MAX_FULL_BREAKDOWNS -> (rank <= _MAX_FULL_BREAKDOWNS)` | survived |
| `d78877acc0` | `spectre/astro/pattern_of_life.py:955` | binop | `rc.alt_km - rp.alt_km -> (rc.alt_km + rp.alt_km)` | survived |
| `ff8e5faf28` | `spectre/astro/pattern_of_life.py:957` | binop | `rc.ecc - rp.ecc -> (rc.ecc + rp.ecc)` | survived |
| `20f01a3f14` | `spectre/astro/pattern_of_life.py:958` | binop | `rc.period_min - rp.period_min -> (rc.period_min + rp.period_min)` | survived |
| `67c352dad5` | `spectre/astro/pattern_of_life.py:958` | binop | `(rc.period_min - rp.period_min) * 60.0 -> ((rc.period_min - rp.period_min) / 60.0)` | survived |
| `ee498730fe` | `spectre/astro/pattern_of_life.py:958` | number | `60.0 -> (90.0)` | survived |
| `b8b3ba3079` | `spectre/astro/pattern_of_life.py:964` | binop | `raan_rate * gap -> (raan_rate / gap)` | survived |
| `db05b432df` | `spectre/astro/pattern_of_life.py:965` | binop | `argp_rate * gap -> (argp_rate / gap)` | survived |
| `5183164d91` | `spectre/astro/pattern_of_life.py:966` | binop | `rp.raan_deg + raan_j2 -> (rp.raan_deg - raan_j2)` | survived |
| `f6d0a9dfae` | `spectre/astro/pattern_of_life.py:967` | binop | `rp.argp_deg + argp_j2 -> (rp.argp_deg - argp_j2)` | survived |
| `0b6477cbcf` | `spectre/astro/pattern_of_life.py:970` | boolop | `rp.geo_drift_rate_deg_day is not None and rc.geo_drift_rate_deg_day is -> (rp.geo_drift_rate_deg_day is not None or rc.geo_drift_rate_deg_day is` | survived |
| `b4f6019e5d` | `spectre/astro/pattern_of_life.py:970` | compare | `rc.geo_drift_rate_deg_day is not None -> (rc.geo_drift_rate_deg_day is None)` | survived |
| `85cd56fc56` | `spectre/astro/pattern_of_life.py:970` | compare | `rp.geo_drift_rate_deg_day is not None -> (rp.geo_drift_rate_deg_day is None)` | survived |
| `53e52c04a6` | `spectre/astro/pattern_of_life.py:971` | binop | `rc.geo_drift_rate_deg_day - rp.geo_drift_rate_deg_day -> (rc.geo_drift_rate_deg_day + rp.geo_drift_rate_deg_day)` | no_tests |
| `8afe790ada` | `spectre/astro/pattern_of_life.py:1031` | number | `0.0 -> (1.0)` | survived |
| `508ce09014` | `spectre/astro/pattern_of_life.py:1031` | compare | `last_dv > prior_stats.mean -> (last_dv >= prior_stats.mean)` | survived |
| `627be5bb48` | `spectre/astro/pattern_of_life.py:1075` | number | `0 -> (1)` | survived |
| `c3718a34b2` | `spectre/astro/pattern_of_life.py:1091` | number | `2 -> (3)` | survived |
| `89527886cd` | `spectre/astro/pattern_of_life.py:1092` | binop | `(records[-1].epoch - records[0].epoch).total_seconds() / 86400.0 -> ((records[-1].epoch - records[0].epoch).total_seconds() * 86400.0)` | survived |
| `541b75bf23` | `spectre/astro/pattern_of_life.py:1092` | number | `86400.0 -> (129600.0)` | survived |
| `a5bd12d8f3` | `spectre/astro/pattern_of_life.py:1117` | bool | `True -> (False)` | survived |
| `b7b1a83ecd` | `spectre/astro/pattern_of_life.py:1118` | compare | `dv >= effective_threshold -> (dv > effective_threshold)` | survived |
| `f6cdfdd347` | `spectre/astro/pattern_of_life.py:1121` | bool | `True -> (False)` | survived |
| `9bef555b5a` | `spectre/astro/pattern_of_life.py:1121` | call | `screened_pairs.sort(key=lambda c: c[3], reverse=True) -> pass` | survived |
| `bb43a3a0c6` | `spectre/astro/pattern_of_life.py:1129` | number | `0 -> (1)` | survived |
| `e5e1a60914` | `spectre/astro/pattern_of_life.py:1129` | binop | `len(screened_pairs) - _MAX_FULL_BREAKDOWNS -> (len(screened_pairs) + _MAX_FULL_BREAKDOWNS)` | survived |
| `82f4a24125` | `spectre/astro/pattern_of_life.py:1134` | number | `1 -> (2)` | survived |
| `be92cece64` | `spectre/astro/pattern_of_life.py:1139` | number | `2 -> (3)` | survived |
| `094ddb1961` | `spectre/astro/pattern_of_life.py:1139` | number | `0.0 -> (1.0)` | survived |
| `33aef48318` | `spectre/astro/pattern_of_life.py:1171` | number | `500 -> (501)` | survived |
| `860f6e234e` | `spectre/astro/pattern_of_life.py:1173` | number | `2 -> (3)` | survived |
| `186852e6fd` | `spectre/astro/pattern_of_life.py:1174` | number | `4 -> (5)` | survived |
| `0ff6685449` | `spectre/astro/pattern_of_life.py:1175` | number | `6 -> (7)` | survived |
| `8d68ecaf74` | `spectre/astro/pattern_of_life.py:1176` | number | `4 -> (5)` | survived |
| `c70517258e` | `spectre/astro/pattern_of_life.py:1177` | number | `4 -> (5)` | survived |
| `c2b2c88a63` | `spectre/astro/pattern_of_life.py:1179` | number | `3 -> (4)` | survived |
| `fe0df38322` | `spectre/astro/pattern_of_life.py:1180` | number | `0 -> (1)` | survived |
| `73ba331609` | `spectre/astro/pattern_of_life.py:1180` | number | `4 -> (5)` | survived |
| `1927995501` | `spectre/astro/pattern_of_life.py:1183` | number | `1000 -> (1001)` | survived |
| `a344996e13` | `spectre/astro/pattern_of_life.py:1183` | number | `3 -> (4)` | survived |
| `4758708930` | `spectre/astro/pattern_of_life.py:1183` | binop | `m.delta_v_km_s * 1000 -> (m.delta_v_km_s / 1000)` | survived |
| `0a93058af5` | `spectre/astro/pattern_of_life.py:1184` | number | `1 -> (2)` | survived |
| `3426bbb769` | `spectre/astro/pattern_of_life.py:1185` | number | `3 -> (4)` | survived |
| `42722acc68` | `spectre/astro/pattern_of_life.py:1185` | number | `0 -> (1)` | survived |
| `91759c30b0` | `spectre/astro/pattern_of_life.py:1189` | number | `1 -> (2)` | survived |
| `e02028a7c6` | `spectre/astro/pattern_of_life.py:1199` | number | `4 -> (5)` | survived |
| `6a42025c16` | `spectre/astro/pattern_of_life.py:1205` | number | `4 -> (5)` | survived |
| `eaceb6ba2c` | `spectre/astro/pattern_of_life.py:1206` | number | `1 -> (2)` | survived |
| `f25936c28e` | `spectre/astro/pattern_of_life.py:1207` | number | `1 -> (2)` | survived |
| `2dca3a9658` | `spectre/astro/photometry.py:151` | compare | `elevation_deg <= 0.0 -> (elevation_deg < 0.0)` | survived |
| `9c133d3efc` | `spectre/astro/photometry.py:151` | number | `0.0 -> (1.0)` | survived |
| `b34dd9adc9` | `spectre/astro/photometry.py:154` | number | `11.0 -> (16.5)` | survived |
| `c434816f8c` | `spectre/astro/photometry.py:154` | binop | `math.sin(el_rad) + 0.025 * math.exp(-11.0 * math.sin(el_rad)) -> (math.sin(el_rad) - 0.025 * math.exp(-11.0 * math.sin(el_rad)))` | survived |
| `2f978ede12` | `spectre/astro/photometry.py:154` | binop | `-11.0 * math.sin(el_rad) -> (-11.0 / math.sin(el_rad))` | survived |
| `65f9c36939` | `spectre/astro/photometry.py:159` | number | `0.12 -> (0.18)` | survived |
| `2cfd8bec4a` | `spectre/astro/photometry.py:160` | number | `1000.0 -> (1500.0)` | survived |
| `20ea42dd56` | `spectre/astro/photometry.py:179` | number | `1.0 -> (1.5)` | survived |
| `466c11a55e` | `spectre/astro/photometry.py:179` | number | `5.0 -> (7.5)` | survived |
| `ee917d1c92` | `spectre/astro/photometry.py:183` | number | `1.0 -> (1.5)` | survived |
| `5a50b77055` | `spectre/astro/photometry.py:185` | binop | `obs.apparent_magnitude - range_correction - atmo_correction -> (obs.apparent_magnitude - range_correction + atmo_correction)` | survived |
| `e40a9b5d7c` | `spectre/astro/photometry.py:188` | number | `0.80 -> (1.2000000000000002)` | survived |
| `5da311fd02` | `spectre/astro/photometry.py:188` | number | `20.0 -> (30.0)` | survived |
| `9cb681fc9c` | `spectre/astro/photometry.py:188` | compare | `obs.lunar_phase_fraction > 0.80 -> (obs.lunar_phase_fraction >= 0.8)` | survived |
| `e89d2539a9` | `spectre/astro/photometry.py:188` | boolop | `obs.lunar_phase_fraction > 0.80 or obs.lunar_separation_deg < 20.0 -> (obs.lunar_phase_fraction > 0.8 and obs.lunar_separation_deg < 20.0)` | survived |
| `311fd912d2` | `spectre/astro/photometry.py:188` | compare | `obs.lunar_separation_deg < 20.0 -> (obs.lunar_separation_deg <= 20.0)` | survived |
| `52bf56d1d0` | `spectre/astro/photometry.py:189` | number | `15.0 -> (22.5)` | survived |
| `bae8c57597` | `spectre/astro/photometry.py:189` | compare | `obs.elevation_deg < 15.0 -> (obs.elevation_deg <= 15.0)` | survived |
| `b1670cd47e` | `spectre/astro/photometry.py:190` | boolop | `lunar_bad and elev_bad -> (lunar_bad or elev_bad)` | survived |
| `3a5f42fb30` | `spectre/astro/photometry.py:201` | number | `4 -> (5)` | survived |
| `010be2231f` | `spectre/astro/photometry.py:221` | number | `5 -> (6)` | survived |
| `d903a50a83` | `spectre/astro/photometry.py:224` | number | `1.0 -> (1.5)` | survived |
| `31249e6065` | `spectre/astro/photometry.py:244` | compare | `n < n_coef -> (n <= n_coef)` | survived |
| `ec697752d3` | `spectre/astro/photometry.py:250` | number | `1.0 -> (1.5)` | survived |
| `ce0f081fdb` | `spectre/astro/photometry.py:250` | boolop | `float(x.std()) or 1.0 -> (float(x.std()) and 1.0)` | survived |
| `298a78f0ae` | `spectre/astro/photometry.py:258` | number | `1 -> (2)` | survived |
| `530c991512` | `spectre/astro/photometry.py:287` | compare | `len(kept) < _MIN_FIT_OBS -> (len(kept) <= _MIN_FIT_OBS)` | survived |
| `15934d7d4a` | `spectre/astro/photometry.py:295` | binop | `mags[i] - _eval_quadratic((a0, a1, a2), phases[i]) -> (mags[i] + _eval_quadratic((a0, a1, a2), phases[i]))` | survived |
| `5be0a71c9f` | `spectre/astro/photometry.py:296` | binop | `sum(residuals) / len(residuals) -> (sum(residuals) * len(residuals))` | survived |
| `ed408ca90b` | `spectre/astro/photometry.py:297` | binop | `r - mean_r -> (r + mean_r)` | survived |
| `2d9bf78efd` | `spectre/astro/photometry.py:297` | number | `1 -> (2)` | survived |
| `5fdf20ebf3` | `spectre/astro/photometry.py:297` | number | `1 -> (2)` | survived |
| `a88b7d6993` | `spectre/astro/photometry.py:297` | binop | `len(residuals) - 1 -> (len(residuals) + 1)` | survived |
| `843802dc09` | `spectre/astro/photometry.py:298` | number | `1e-12 -> (1.5e-12)` | survived |
| `0a6fb4ebc5` | `spectre/astro/photometry.py:298` | compare | `std_r < 1e-12 -> (std_r <= 1e-12)` | survived |
| `8d15b84e43` | `spectre/astro/photometry.py:300` | bool | `True -> (False)` | survived |
| `79d1e82a7e` | `spectre/astro/photometry.py:300` | compare | `abs(r - mean_r) > threshold * std_r -> (abs(r - mean_r) >= threshold * std_r)` | survived |
| `a3ea3ffdf7` | `spectre/astro/photometry.py:300` | binop | `r - mean_r -> (r + mean_r)` | survived |
| `492580f372` | `spectre/astro/photometry.py:304` | bool | `False -> (True)` | survived |
| `4458fd8914` | `spectre/astro/photometry.py:312` | number | `5 -> (6)` | survived |
| `2d46fe7f5a` | `spectre/astro/photometry.py:323` | compare | `len(usable) < _MIN_FIT_OBS -> (len(usable) <= _MIN_FIT_OBS)` | survived |
| `436b353314` | `spectre/astro/photometry.py:338` | number | `1 -> (2)` | survived |
| `e1e444748b` | `spectre/astro/photometry.py:338` | number | `1 -> (2)` | survived |
| `6bdcc911c9` | `spectre/astro/photometry.py:338` | binop | `len(final_resids) - 1 -> (len(final_resids) + 1)` | survived |
| `b9545d23f4` | `spectre/astro/photometry.py:339` | number | `0.0 -> (1.0)` | survived |
| `8c99d62f30` | `spectre/astro/photometry.py:339` | compare | `len(final_resids) > 1 -> (len(final_resids) >= 1)` | survived |
| `142e6be016` | `spectre/astro/photometry.py:339` | number | `1 -> (2)` | survived |
| `81161197db` | `spectre/astro/photometry.py:342` | number | `6 -> (7)` | survived |
| `fc79d37a51` | `spectre/astro/photometry.py:343` | number | `6 -> (7)` | survived |
| `f58e132dc5` | `spectre/astro/photometry.py:344` | number | `6 -> (7)` | survived |
| `94cdd4743d` | `spectre/astro/photometry.py:346` | number | `5 -> (6)` | survived |
| `8915ba0d95` | `spectre/astro/photometry.py:350` | number | `1 -> (2)` | survived |
| `6d7aa08993` | `spectre/astro/photometry.py:350` | number | `0 -> (1)` | survived |
| `aa2b6609ad` | `spectre/astro/photometry.py:350` | unary | `-1 -> (1)` | survived |
| `4515027806` | `spectre/astro/photometry.py:367` | number | `2 -> (3)` | survived |
| `743433afcd` | `spectre/astro/photometry.py:367` | compare | `na < 2 -> (na <= 2)` | survived |
| `a80bfb8ab7` | `spectre/astro/photometry.py:367` | boolop | `na < 2 or nb < 2 -> (na < 2 and nb < 2)` | survived |
| `2f16036fd5` | `spectre/astro/photometry.py:367` | compare | `nb < 2 -> (nb <= 2)` | survived |
| `1093a0be20` | `spectre/astro/photometry.py:367` | number | `2 -> (3)` | survived |
| `0d1f613101` | `spectre/astro/photometry.py:368` | number | `0.0 -> (1.0)` | survived |
| `5240a379b2` | `spectre/astro/photometry.py:376` | compare | `se < 1e-15 -> (se <= 1e-15)` | survived |
| `9a519defa6` | `spectre/astro/photometry.py:376` | number | `1e-15 -> (1.5000000000000001e-15)` | survived |
| `01271ad87c` | `spectre/astro/photometry.py:387` | binop | `na + nb - 2 -> (na + nb + 2)` | survived |
| `2fde03d534` | `spectre/astro/photometry.py:387` | compare | `denom > 0.0 -> (denom >= 0.0)` | survived |
| `c955db3e1e` | `spectre/astro/photometry.py:387` | number | `2 -> (3)` | survived |
| `add6deb39d` | `spectre/astro/photometry.py:387` | binop | `na + nb -> (na - nb)` | survived |
| `a8654f7c1c` | `spectre/astro/photometry.py:393` | number | `1.0 -> (1.5)` | survived |
| `e689e8366d` | `spectre/astro/photometry.py:404` | number | `200 -> (201)` | survived |
| `a41794e207` | `spectre/astro/photometry.py:405` | number | `1.0e-30 -> (1.5000000000000001e-30)` | survived |
| `162a46ea4f` | `spectre/astro/photometry.py:406` | number | `3.0e-7 -> (4.5e-07)` | survived |
| `793ca6ec08` | `spectre/astro/photometry.py:412` | compare | `abs(d) < FPMIN -> (abs(d) <= FPMIN)` | survived |
| `bdd336f6ad` | `spectre/astro/photometry.py:416` | number | `1 -> (2)` | survived |
| `ff1c119e06` | `spectre/astro/photometry.py:416` | binop | `MAXIT + 1 -> (MAXIT - 1)` | survived |
| `bab228996f` | `spectre/astro/photometry.py:420` | compare | `abs(d) < FPMIN -> (abs(d) <= FPMIN)` | survived |
| `8c10881eb0` | `spectre/astro/photometry.py:423` | compare | `abs(c) < FPMIN -> (abs(c) <= FPMIN)` | survived |
| `e85e0601da` | `spectre/astro/photometry.py:429` | compare | `abs(d) < FPMIN -> (abs(d) <= FPMIN)` | survived |
| `f75fc00f8a` | `spectre/astro/photometry.py:432` | compare | `abs(c) < FPMIN -> (abs(c) <= FPMIN)` | survived |
| `518d9a9333` | `spectre/astro/photometry.py:437` | binop | `delta - 1.0 -> (delta + 1.0)` | survived |
| `5022d05ba7` | `spectre/astro/photometry.py:437` | compare | `abs(delta - 1.0) < EPS -> (abs(delta - 1.0) <= EPS)` | survived |
| `798e591655` | `spectre/astro/photometry.py:437` | number | `1.0 -> (1.5)` | survived |
| `3104cdb9a9` | `spectre/astro/photometry.py:439` | return | `return h -> return None` | no_tests |
| `fff799cbde` | `spectre/astro/photometry.py:456` | number | `1.0 -> (1.5)` | survived |
| `3473fc7e62` | `spectre/astro/photometry.py:456` | number | `2.0 -> (3.0)` | survived |
| `9f8f60b786` | `spectre/astro/photometry.py:456` | compare | `x < (a + 1.0) / (a + b + 2.0) -> (x <= (a + 1.0) / (a + b + 2.0))` | survived |
| `4cab7f2da5` | `spectre/astro/photometry.py:463` | number | `2 -> (3)` | survived |
| `d04bce2f19` | `spectre/astro/photometry.py:469` | number | `30.0 -> (45.0)` | survived |
| `20b7681fdb` | `spectre/astro/photometry.py:470` | number | `90.0 -> (135.0)` | survived |
| `9e82b4a239` | `spectre/astro/photometry.py:482` | boolop | `not baseline_residuals or not recent_residuals -> (not baseline_residuals and (not recent_residuals))` | survived |
| `c27a4a0656` | `spectre/astro/photometry.py:483` | return | `return 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 -> return None` | no_tests |
| `c699983105` | `spectre/astro/photometry.py:483` | number | `0.0 -> (1.0)` | no_tests |
| `013b7f019d` | `spectre/astro/photometry.py:483` | number | `0.0 -> (1.0)` | no_tests |
| `0401e5a6d7` | `spectre/astro/photometry.py:483` | number | `0.0 -> (1.0)` | no_tests |
| `af4d0605d7` | `spectre/astro/photometry.py:483` | number | `1.0 -> (1.5)` | no_tests |
| `e47f403c2d` | `spectre/astro/photometry.py:483` | number | `0.0 -> (1.0)` | no_tests |
| `82c34a7bf0` | `spectre/astro/photometry.py:483` | number | `0.0 -> (1.0)` | no_tests |
| `73347f6f53` | `spectre/astro/photometry.py:486` | number | `1 -> (2)` | survived |
| `0e3a8f5eb4` | `spectre/astro/photometry.py:486` | binop | `len(baseline_residuals) - 1 -> (len(baseline_residuals) + 1)` | survived |
| `90d9ef1086` | `spectre/astro/photometry.py:486` | binop | `r - bm -> (r + bm)` | survived |
| `7ea881cc34` | `spectre/astro/photometry.py:486` | binop | `sum((r - bm) ** 2 for r in baseline_residuals) / max(len(baseline_resi -> (sum(((r - bm) ** 2 for r in baseline_residuals)) * max(len(baseline_r` | survived |
| `dadecbc6bb` | `spectre/astro/photometry.py:486` | number | `1 -> (2)` | survived |
| `3190d4f534` | `spectre/astro/photometry.py:488` | number | `1 -> (2)` | survived |
| `bc7738a31b` | `spectre/astro/photometry.py:488` | binop | `r - rm -> (r + rm)` | survived |
| `d8e233b5d5` | `spectre/astro/photometry.py:488` | binop | `len(recent_residuals) - 1 -> (len(recent_residuals) + 1)` | survived |
| `ca90c58900` | `spectre/astro/photometry.py:488` | number | `1 -> (2)` | survived |
| `c7d6220ff6` | `spectre/astro/photometry.py:488` | binop | `sum((r - rm) ** 2 for r in recent_residuals) / max(len(recent_residual -> (sum(((r - rm) ** 2 for r in recent_residuals)) * max(len(recent_resid` | survived |
| `8137799361` | `spectre/astro/photometry.py:508` | compare | `start <= c.epoch_utc < end -> (start < c.epoch_utc < end)` | survived |
| `08c9b70eb9` | `spectre/astro/photometry.py:517` | compare | `start <= e < recent_cutoff -> (start <= e <= recent_cutoff)` | survived |
| `9af973f4f8` | `spectre/astro/photometry.py:517` | compare | `start <= e < recent_cutoff -> (start < e < recent_cutoff)` | survived |
| `f16110213d` | `spectre/astro/photometry.py:517` | compare | `e >= recent_cutoff -> (e > recent_cutoff)` | survived |
| `95e6b4b84b` | `spectre/astro/photometry.py:528` | number | `0.0 -> (1.0)` | survived |
| `f112582a51` | `spectre/astro/photometry.py:531` | number | `0.0 -> (1.0)` | survived |
| `51b2890c6e` | `spectre/astro/photometry.py:532` | compare | `c.epoch_utc >= recent_cutoff -> (c.epoch_utc > recent_cutoff)` | survived |
| `4714b26b24` | `spectre/astro/photometry.py:532` | boolop | `c.epoch_utc >= recent_cutoff and c.quality_flag != "reject" -> (c.epoch_utc >= recent_cutoff or c.quality_flag != 'reject')` | survived |
| `088056de91` | `spectre/astro/photometry.py:533` | number | `0.0 -> (1.0)` | survived |
| `4c00126029` | `spectre/astro/photometry.py:555` | compare | `baseline_cutoff <= c.epoch_utc < recent_cutoff -> (baseline_cutoff <= c.epoch_utc <= recent_cutoff)` | survived |
| `3c6fd18f98` | `spectre/astro/photometry.py:555` | compare | `baseline_cutoff <= c.epoch_utc < recent_cutoff -> (baseline_cutoff < c.epoch_utc < recent_cutoff)` | survived |
| `c3730c55e3` | `spectre/astro/photometry.py:557` | compare | `c.epoch_utc >= recent_cutoff -> (c.epoch_utc > recent_cutoff)` | survived |
| `4dfc2063d0` | `spectre/astro/photometry.py:565` | number | `2.0 -> (3.0)` | survived |
| `f4a7c6a25e` | `spectre/astro/photometry.py:570` | compare | `c.quality_flag == "reject" -> (c.quality_flag != 'reject')` | survived |
| `f4d62d8191` | `spectre/astro/photometry.py:576` | compare | `abs(c.reduced_magnitude - predicted) > threshold_sigma * baseline.resi -> (abs(c.reduced_magnitude - predicted) >= threshold_sigma * baseline.re` | survived |
| `b773f3cc95` | `spectre/astro/photometry.py:576` | binop | `threshold_sigma * baseline.residual_std -> (threshold_sigma / baseline.residual_std)` | survived |
| `49b333c22d` | `spectre/astro/photometry.py:576` | binop | `c.reduced_magnitude - predicted -> (c.reduced_magnitude + predicted)` | survived |
| `2a426dc549` | `spectre/astro/photometry.py:577` | return | `return c.epoch_utc -> return None` | survived |
| `3040c1ae03` | `spectre/astro/photometry.py:584` | number | `48.0 -> (72.0)` | survived |
| `d1fd8c0368` | `spectre/astro/photometry.py:592` | compare | `abs((m.epoch - change_epoch).total_seconds()) <= window.total_seconds( -> (abs((m.epoch - change_epoch).total_seconds()) < window.total_seconds(` | survived |
| `19c08054dc` | `spectre/astro/photometry.py:601` | number | `0.12 -> (0.18)` | survived |
| `0028292753` | `spectre/astro/photometry.py:602` | number | `1000.0 -> (1500.0)` | survived |
| `0684c37c5a` | `spectre/astro/photometry.py:603` | number | `3.0 -> (4.5)` | survived |
| `58c1a4481b` | `spectre/astro/photometry.py:604` | number | `30.0 -> (45.0)` | survived |
| `ebd1da3b26` | `spectre/astro/photometry.py:605` | number | `90.0 -> (135.0)` | survived |
| `3685097b10` | `spectre/astro/photometry.py:650` | compare | `overhang > _PHASE_EXTRAPOLATION_DEG -> (overhang >= _PHASE_EXTRAPOLATION_DEG)` | survived |
| `5bd64624c6` | `spectre/astro/photometry.py:650` | number | `2 -> (3)` | survived |
| `7c1deca28f` | `spectre/astro/photometry.py:657` | number | `0.0 -> (1.0)` | survived |
| `5d6aeade7f` | `spectre/astro/photometry.py:657` | number | `0.0 -> (1.0)` | survived |
| `1e576a131a` | `spectre/astro/photometry.py:658` | number | `0.0 -> (1.0)` | survived |
| `dfeabb03ad` | `spectre/astro/photometry.py:658` | number | `0.0 -> (1.0)` | survived |
| `6238b2ada3` | `spectre/astro/photometry.py:659` | number | `1.0 -> (1.5)` | survived |
| `6b6ed5e1df` | `spectre/astro/photometry.py:659` | number | `0.0 -> (1.0)` | survived |
| `d66f5aa75b` | `spectre/astro/photometry.py:659` | number | `0.0 -> (1.0)` | survived |
| `c3c8756bb8` | `spectre/astro/photometry.py:660` | bool | `False -> (True)` | survived |
| `9091ce0287` | `spectre/astro/photometry.py:660` | bool | `False -> (True)` | survived |
| `3eae43f899` | `spectre/astro/photometry.py:661` | number | `0.0 -> (1.0)` | survived |
| `cfc721eb51` | `spectre/astro/photometry.py:679` | binop | `rm - bm -> (rm + bm)` | survived |
| `8924ca3c4a` | `spectre/astro/photometry.py:680` | number | `0.01 -> (0.015)` | survived |
| `7f2415a0d3` | `spectre/astro/photometry.py:680` | compare | `abs(delta_mag) < 0.01 -> (abs(delta_mag) <= 0.01)` | survived |
| `08cdd70f12` | `spectre/astro/photometry.py:682` | compare | `delta_mag > 0 -> (delta_mag >= 0)` | survived |
| `92360f68a7` | `spectre/astro/photometry.py:687` | number | `0.05 -> (0.07500000000000001)` | survived |
| `88cda50b8e` | `spectre/astro/photometry.py:687` | compare | `p < 0.05 -> (p <= 0.05)` | survived |
| `0b9aab0fdd` | `spectre/astro/photometry.py:688` | number | `0.01 -> (0.015)` | survived |
| `107b4891f8` | `spectre/astro/photometry.py:688` | compare | `p < 0.01 -> (p <= 0.01)` | survived |
| `765be8e6e1` | `spectre/astro/photometry.py:692` | compare | `c.quality_flag == "reject" -> (c.quality_flag != 'reject')` | survived |
| `f72e0c8ba4` | `spectre/astro/photometry.py:692` | number | `1 -> (2)` | survived |
| `e1836c0fb0` | `spectre/astro/photometry.py:693` | number | `1 -> (2)` | survived |
| `7f6db000fa` | `spectre/astro/photometry.py:693` | compare | `c.quality_flag == "lunar" -> (c.quality_flag != 'lunar')` | survived |
| `02e91dda4c` | `spectre/astro/photometry.py:694` | binop | `0.2 * len(corrected) -> (0.2 / len(corrected))` | survived |
| `09fb73cc6e` | `spectre/astro/photometry.py:694` | compare | `n_reject > 0.2 * len(corrected) -> (n_reject >= 0.2 * len(corrected))` | survived |
| `bb12f37e98` | `spectre/astro/photometry.py:694` | number | `0.2 -> (0.30000000000000004)` | survived |
| `b16bb6b1b5` | `spectre/astro/photometry.py:695` | call | `confounders.append(f"{n_reject} observations rejected (poor geometry/l -> pass` | no_tests |
| `3b038bbe81` | `spectre/astro/photometry.py:696` | number | `0 -> (1)` | survived |
| `73a3b76c00` | `spectre/astro/photometry.py:696` | compare | `n_lunar > 0 -> (n_lunar >= 0)` | survived |
| `e6870749e2` | `spectre/astro/photometry.py:697` | call | `confounders.append(f"{n_lunar} observations affected by lunar proximit -> pass` | no_tests |
| `01d75e136f` | `spectre/astro/photometry.py:698` | number | `0.3 -> (0.44999999999999996)` | survived |
| `a4969f1da9` | `spectre/astro/photometry.py:698` | compare | `baseline.residual_std > 0.3 -> (baseline.residual_std >= 0.3)` | survived |
| `a6717ae9de` | `spectre/astro/photometry.py:699` | call | `confounders.append(f"High baseline scatter (σ={baseline.residual_std:. -> pass` | no_tests |
| `02a3c13713` | `spectre/astro/photometry.py:700` | compare | `overhang > _PHASE_EXTRAPOLATION_DEG -> (overhang >= _PHASE_EXTRAPOLATION_DEG)` | survived |
| `a4ded25624` | `spectre/astro/photometry.py:709` | compare | `min(len(base_res), len(recent_res)) < _MIN_WINDOW_OBS -> (min(len(base_res), len(recent_res)) <= _MIN_WINDOW_OBS)` | survived |
| `92c1452c49` | `spectre/astro/photometry.py:710` | call | `confounders.append( f"No change could be tested: the baseline window h -> pass` | no_tests |
| `aec9fbc203` | `spectre/astro/photometry.py:723` | number | `4 -> (5)` | survived |
| `a32ee78808` | `spectre/astro/photometry.py:724` | number | `4 -> (5)` | survived |
| `8f4d5fc031` | `spectre/astro/photometry.py:725` | number | `4 -> (5)` | survived |
| `7305df4f55` | `spectre/astro/photometry.py:726` | number | `4 -> (5)` | survived |
| `6c745afad7` | `spectre/astro/photometry.py:727` | number | `4 -> (5)` | survived |
| `02829befe0` | `spectre/astro/photometry.py:728` | number | `4 -> (5)` | survived |
| `c1437ea776` | `spectre/astro/photometry.py:729` | number | `6 -> (7)` | survived |
| `b15430a182` | `spectre/astro/photometry.py:732` | number | `4 -> (5)` | survived |
| `59f6f36988` | `spectre/astro/photometry.py:789` | return | `return "" -> return None` | survived |
| `849d6b2a36` | `spectre/astro/photometry.py:796` | boolop | `not isinstance(value, str) or not value.strip() -> (not isinstance(value, str) and (not value.strip()))` | survived |
| `c29da66500` | `spectre/astro/photometry.py:833` | boolop | `_cell(row, columns, "filter_band") or "unfiltered" -> (_cell(row, columns, 'filter_band') and 'unfiltered')` | survived |
| `f6eb039974` | `spectre/astro/photometry.py:834` | number | `0.0 -> (1.0)` | survived |
| `fb294978bf` | `spectre/astro/photometry.py:835` | number | `0.0 -> (1.0)` | survived |
| `5c33c597d4` | `spectre/astro/photometry.py:836` | number | `0.0 -> (1.0)` | survived |
| `5fb7513435` | `spectre/astro/photometry.py:837` | number | `1000.0 -> (1500.0)` | survived |
| `602aa8c1af` | `spectre/astro/photometry.py:838` | number | `45.0 -> (67.5)` | survived |
| `528685dc43` | `spectre/astro/photometry.py:839` | number | `45.0 -> (67.5)` | survived |
| `2657786a18` | `spectre/astro/photometry.py:840` | number | `0.0 -> (1.0)` | survived |
| `11873dc141` | `spectre/astro/photometry.py:841` | number | `90.0 -> (135.0)` | survived |
| `2e0811d58a` | `spectre/astro/propagator.py:24` | number | `1e-10 -> (1.5e-10)` | survived |
| `faaa35a10e` | `spectre/astro/propagator.py:25` | number | `1e-10 -> (1.5e-10)` | survived |
| `9c128f1984` | `spectre/astro/propagator.py:70` | binop | `1.0 + self.ecc -> (1.0 - self.ecc)` | no_tests |
| `0f67736a4a` | `spectre/astro/propagator.py:70` | return | `return self.a * (1.0 + self.ecc) -> return None` | no_tests |
| `69d24035ee` | `spectre/astro/propagator.py:70` | binop | `self.a * (1.0 + self.ecc) -> (self.a / (1.0 + self.ecc))` | no_tests |
| `9156cf3762` | `spectre/astro/propagator.py:70` | number | `1.0 -> (1.5)` | no_tests |
| `9e4efe8dfc` | `spectre/astro/propagator.py:75` | binop | `1.0 - self.ecc -> (1.0 + self.ecc)` | no_tests |
| `23c874d203` | `spectre/astro/propagator.py:75` | return | `return self.a * (1.0 - self.ecc) -> return None` | no_tests |
| `db2e1870b3` | `spectre/astro/propagator.py:75` | number | `1.0 -> (1.5)` | no_tests |
| `17b26fb60f` | `spectre/astro/propagator.py:75` | binop | `self.a * (1.0 - self.ecc) -> (self.a / (1.0 - self.ecc))` | no_tests |
| `6c0ab7fbf5` | `spectre/astro/propagator.py:97` | boolop | `len(line) != _TLE_LINE_LENGTH or not line[-1].isdigit() -> (len(line) != _TLE_LINE_LENGTH and (not line[-1].isdigit()))` | survived |
| `6c50cdc0a7` | `spectre/astro/propagator.py:97` | number | `1 -> (2)` | survived |
| `d16c03d282` | `spectre/astro/propagator.py:111` | unary | `-1 -> (1)` | survived |
| `fc6f915488` | `spectre/astro/propagator.py:135` | number | `60.0 -> (90.0)` | survived |
| `4fcc2e309b` | `spectre/astro/propagator.py:140` | number | `1 -> (2)` | survived |
| `74c8bc6cd1` | `spectre/astro/propagator.py:140` | binop | `window / step_s -> (window * step_s)` | survived |
| `c8f5cf8fd5` | `spectre/astro/propagator.py:141` | number | `1 -> (2)` | survived |
| `5657eb566c` | `spectre/astro/propagator.py:141` | binop | `n + 1 -> (n - 1)` | survived |
| `f85a178ac5` | `spectre/astro/propagator.py:142` | binop | `i * step_s -> (i / step_s)` | survived |
| `8f03e8493e` | `spectre/astro/propagator.py:142` | binop | `start + timedelta(seconds=i * step_s) -> (start - timedelta(seconds=i * step_s))` | survived |
| `5967c3164d` | `spectre/astro/propagator.py:167` | number | `1.0 -> (1.5)` | survived |
| `339fff83a9` | `spectre/astro/propagator.py:177` | number | `1e-14 -> (1.5e-14)` | survived |
| `707a2af5b1` | `spectre/astro/propagator.py:177` | compare | `abs(energy) < 1e-14 -> (abs(energy) <= 1e-14)` | survived |
| `8dfb7fd6d7` | `spectre/astro/propagator.py:183` | number | `1.0 -> (1.5)` | survived |
| `24d78e2110` | `spectre/astro/propagator.py:183` | number | `1.0 -> (1.5)` | survived |
| `44cf37b60a` | `spectre/astro/propagator.py:186` | number | `1e-10 -> (1.5e-10)` | survived |
| `1959e6d586` | `spectre/astro/propagator.py:186` | compare | `n_mag > 1e-10 -> (n_mag >= 1e-10)` | survived |
| `7d812fa394` | `spectre/astro/propagator.py:187` | number | `1.0 -> (1.5)` | survived |
| `1387ef16fb` | `spectre/astro/propagator.py:187` | number | `1.0 -> (1.5)` | survived |
| `c7bd490207` | `spectre/astro/propagator.py:188` | number | `0 -> (1)` | survived |
| `9be0d72cdc` | `spectre/astro/propagator.py:188` | compare | `n[1] < 0 -> (n[1] <= 0)` | survived |
| `0305e76cb9` | `spectre/astro/propagator.py:240` | compare | `n_mag <= _EQUATORIAL_NODE_TOL -> (n_mag < _EQUATORIAL_NODE_TOL)` | survived |
| `44482af038` | `spectre/astro/propagator.py:241` | compare | `ecc <= _CIRCULAR_ECC_TOL -> (ecc < _CIRCULAR_ECC_TOL)` | survived |
| `d8e549d4d9` | `spectre/astro/propagator.py:249` | number | `0 -> (1)` | survived |
| `32c7558586` | `spectre/astro/propagator.py:249` | compare | `h[2] < 0 -> (h[2] <= 0)` | survived |
| `e6f98d59d4` | `spectre/astro/propagator.py:250` | number | `360.0 -> (540.0)` | survived |
| `c03b5178d7` | `spectre/astro/propagator.py:261` | number | `360.0 -> (540.0)` | survived |
| `af4253e36e` | `spectre/astro/propagator.py:262` | compare | `h[2] < 0 -> (h[2] <= 0)` | survived |
| `010409f2c9` | `spectre/astro/propagator.py:262` | number | `0 -> (1)` | survived |
| `edc054af97` | `spectre/astro/propagator.py:263` | binop | `360.0 - argp -> (360.0 + argp)` | no_tests |
| `85d5501f30` | `spectre/astro/propagator.py:263` | number | `360.0 -> (540.0)` | no_tests |
| `007f8e6b3a` | `spectre/astro/propagator.py:264` | number | `1.0 -> (1.5)` | survived |
| `4625c952a0` | `spectre/astro/propagator.py:264` | number | `1.0 -> (1.5)` | survived |
| `1efe5e3a36` | `spectre/astro/propagator.py:266` | compare | `np.dot(r, v) < 0 -> (np.dot(r, v) <= 0)` | survived |
| `db959667dd` | `spectre/astro/propagator.py:266` | number | `0 -> (1)` | survived |
| `9d8ce27894` | `spectre/astro/propagator.py:267` | number | `360.0 -> (540.0)` | no_tests |
| `cb26fa28ed` | `spectre/astro/propagator.py:267` | binop | `360.0 - ta -> (360.0 + ta)` | no_tests |
| `93598fb53e` | `spectre/astro/propagator.py:270` | number | `1.0 -> (1.5)` | survived |
| `d21f38986f` | `spectre/astro/propagator.py:270` | number | `1.0 -> (1.5)` | survived |
| `aa16b49b71` | `spectre/astro/propagator.py:272` | compare | `e_vec[2] < 0 -> (e_vec[2] <= 0)` | survived |
| `9c37a527e2` | `spectre/astro/propagator.py:274` | number | `1.0 -> (1.5)` | survived |
| `d280fb1135` | `spectre/astro/propagator.py:274` | number | `1.0 -> (1.5)` | survived |
| `f9e2752848` | `spectre/astro/propagator.py:276` | number | `0 -> (1)` | survived |
| `c8e87669aa` | `spectre/astro/propagator.py:276` | compare | `np.dot(r, v) < 0 -> (np.dot(r, v) <= 0)` | survived |
| `223ef6634e` | `spectre/astro/propagator.py:277` | number | `360.0 -> (540.0)` | survived |
| `34d1a6e9e1` | `spectre/astro/propagator.py:277` | binop | `360.0 - ta -> (360.0 + ta)` | survived |
| `85dc6d7b81` | `spectre/astro/propagator.py:317` | unary | `-cos_O -> (cos_O)` | survived |
| `c1b11b6ed4` | `spectre/astro/propagator.py:327` | boolop | `elem.epoch or datetime.now(tz=UTC) -> (elem.epoch and datetime.now(tz=UTC))` | survived |
| `9e28a4f6aa` | `spectre/astro/response_burn.py:51` | number | `16 -> (17)` | survived |
| `960108fd26` | `spectre/astro/response_burn.py:55` | number | `0.01 -> (0.015)` | survived |
| `d539beb557` | `spectre/astro/response_burn.py:72` | number | `2 -> (3)` | survived |
| `68aa89a0b0` | `spectre/astro/response_burn.py:159` | number | `0.0 -> (1.0)` | survived |
| `b470b5a8bd` | `spectre/astro/response_burn.py:164` | boolop | `start is None or arc is None -> (start is None and arc is None)` | survived |
| `c638e59826` | `spectre/astro/response_burn.py:234` | return | `return self.count >= MAX_SIZING_TRIALS -> return None` | survived |
| `f8dacb2b8b` | `spectre/astro/response_burn.py:234` | compare | `self.count >= MAX_SIZING_TRIALS -> (self.count > MAX_SIZING_TRIALS)` | survived |
| `6b4af49c73` | `spectre/astro/response_burn.py:243` | bool | `False -> (True)` | survived |
| `9c2836b532` | `spectre/astro/response_burn.py:243` | number | `0 -> (1)` | survived |
| `a0e03072e8` | `spectre/astro/response_burn.py:246` | number | `0.0 -> (1.0)` | survived |
| `98b758a89f` | `spectre/astro/response_burn.py:260` | number | `3 -> (4)` | survived |
| `162b4355d4` | `spectre/astro/response_burn.py:277` | number | `1 -> (2)` | survived |
| `66ab7abdef` | `spectre/astro/response_burn.py:277` | compare | `plus.approach.miss_km >= minus.approach.miss_km -> (plus.approach.miss_km > minus.approach.miss_km)` | survived |
| `36c61c8bea` | `spectre/astro/response_burn.py:279` | compare | `high < request.budget_km_s -> (high <= request.budget_km_s)` | survived |
| `f164f9b5e1` | `spectre/astro/response_burn.py:279` | compare | `found.approach.miss_km < request.target_km -> (found.approach.miss_km <= request.target_km)` | survived |
| `d4301080a5` | `spectre/astro/response_burn.py:280` | number | `2.0 -> (3.0)` | survived |
| `2a67649970` | `spectre/astro/response_burn.py:280` | binop | `2.0 * high -> (2.0 / high)` | survived |
| `db1729d656` | `spectre/astro/response_burn.py:282` | compare | `found.approach.miss_km >= request.target_km -> (found.approach.miss_km > request.target_km)` | survived |
| `9e58150c54` | `spectre/astro/response_burn.py:283` | compare | `high - low > _SIZE_TOLERANCE * high -> (high - low >= _SIZE_TOLERANCE * high)` | survived |
| `cce4340670` | `spectre/astro/response_burn.py:286` | compare | `tried.approach.miss_km >= request.target_km -> (tried.approach.miss_km > request.target_km)` | survived |
| `9ca18c70ad` | `spectre/astro/tactical.py:64` | number | `10.0 -> (15.0)` | survived |
| `c269b69a45` | `spectre/astro/tactical.py:68` | number | `1e-12 -> (1.5e-12)` | survived |
| `cbe168df95` | `spectre/astro/tactical.py:71` | number | `1e-9 -> (1.5000000000000002e-09)` | survived |
| `d23083177b` | `spectre/astro/tactical.py:76` | number | `100.0 -> (150.0)` | survived |
| `1b01e89ffe` | `spectre/astro/tactical.py:83` | number | `1 -> (2)` | survived |
| `3e5e32fabb` | `spectre/astro/tactical.py:99` | compare | `gap_km > _PHASING_RADIUS_TOLERANCE_KM -> (gap_km >= _PHASING_RADIUS_TOLERANCE_KM)` | survived |
| `1fd76df034` | `spectre/astro/tactical.py:121` | compare | `revolutions_to_close <= 0.0 -> (revolutions_to_close < 0.0)` | survived |
| `f37c456eaa` | `spectre/astro/tactical.py:137` | compare | `far_apsis <= R_EARTH + MIN_PERIGEE_ALT_KM -> (far_apsis < R_EARTH + MIN_PERIGEE_ALT_KM)` | survived |
| `db3db973c6` | `spectre/astro/tactical.py:137` | binop | `R_EARTH + MIN_PERIGEE_ALT_KM -> (R_EARTH - MIN_PERIGEE_ALT_KM)` | survived |
| `20d3ae4cac` | `spectre/astro/tactical.py:208` | number | `1e-12 -> (1.5e-12)` | survived |
| `d63cb3343e` | `spectre/astro/tactical.py:208` | compare | `abs(sin_nt) < 1e-12 -> (abs(sin_nt) <= 1e-12)` | survived |
| `47f67c98e8` | `spectre/astro/tactical.py:223` | number | `0.0 -> (1.0)` | survived |
| `b474b3df72` | `spectre/astro/tactical.py:227` | number | `0.0 -> (1.0)` | survived |
| `285d378e9b` | `spectre/astro/tactical.py:258` | compare | `abs(coeff) < 1e-12 -> (abs(coeff) <= 1e-12)` | survived |
| `22f57c5a3e` | `spectre/astro/tactical.py:258` | number | `1e-12 -> (1.5e-12)` | survived |
| `dfcaf3deeb` | `spectre/astro/tactical.py:270` | number | `0.0 -> (1.0)` | survived |
| `0b303093a8` | `spectre/astro/tactical.py:272` | number | `0.0 -> (1.0)` | survived |
| `9a2f10f4ce` | `spectre/astro/tactical.py:276` | number | `0.0 -> (1.0)` | survived |
| `9dd8f0b8be` | `spectre/astro/tactical.py:316` | number | `1e-15 -> (1.5000000000000001e-15)` | survived |
| `136d69407f` | `spectre/astro/tactical.py:316` | compare | `abs(det) < 1e-15 -> (abs(det) <= 1e-15)` | survived |
| `73d527a210` | `spectre/astro/tactical.py:329` | number | `0.0 -> (1.0)` | survived |
| `1237e6fd35` | `spectre/astro/tactical.py:330` | number | `2 -> (3)` | survived |
| `b7a302d58c` | `spectre/astro/tactical.py:330` | number | `2 -> (3)` | survived |
| `0b6f344a11` | `spectre/astro/tactical.py:333` | number | `0.0 -> (1.0)` | survived |
| `1122b56538` | `spectre/astro/tactical.py:374` | number | `0.0 -> (1.0)` | survived |
| `61b7fedf5a` | `spectre/astro/tactical.py:401` | unary | `-argp_deg -> (argp_deg)` | survived |
| `180a06de5b` | `spectre/astro/tactical.py:402` | binop | `180.0 - argp_deg -> (180.0 + argp_deg)` | survived |
| `59c4642237` | `spectre/astro/tactical.py:404` | compare | `abs(ecc) < _CIRCULAR_ECC -> (abs(ecc) <= _CIRCULAR_ECC)` | survived |
| `00de6c64e8` | `spectre/astro/tactical.py:406` | compare | `dv_desc < dv_asc -> (dv_desc <= dv_asc)` | survived |
| `cb4785b96b` | `spectre/astro/tactical.py:450` | compare | `r2 > r1 -> (r2 >= r1)` | survived |
| `6b0f6799eb` | `spectre/astro/tactical.py:468` | binop | `r2 - r1 -> (r2 + r1)` | survived |
| `8112f6a833` | `spectre/astro/tactical.py:479` | number | `200.0 -> (300.0)` | survived |
| `ece7143c3f` | `spectre/astro/tactical.py:480` | number | `2000.0 -> (3000.0)` | survived |
| `1dc8b14085` | `spectre/astro/tactical.py:481` | number | `100 -> (101)` | survived |
| `aca0e51789` | `spectre/astro/tactical.py:482` | number | `180.0 -> (270.0)` | survived |
| `a605c6393c` | `spectre/astro/tactical.py:520` | binop | `1.0 - ecc**2 -> (1.0 + ecc ** 2)` | survived |
| `ee34da14cf` | `spectre/astro/tactical.py:520` | number | `2 -> (3)` | survived |
| `01ca380b6e` | `spectre/astro/tactical.py:520` | binop | `a * (1.0 - ecc**2) -> (a / (1.0 - ecc ** 2))` | survived |
| `86792c88a5` | `spectre/astro/tactical.py:558` | compare | `abs(diff_rate) < 1e-10 -> (abs(diff_rate) <= 1e-10)` | survived |
| `c56bbe78c0` | `spectre/astro/tactical.py:558` | number | `1e-10 -> (1.5e-10)` | survived |
| `7dc4ba81bc` | `spectre/astro/tactical.py:562` | compare | `conv_days < 0 -> (conv_days <= 0)` | survived |
| `11f26850d6` | `spectre/astro/tactical.py:562` | number | `0 -> (1)` | survived |
| `934ece8734` | `spectre/astro/tactical.py:563` | binop | `360.0 - abs(delta_raan_deg) -> (360.0 + abs(delta_raan_deg))` | survived |
| `15c65b6dfd` | `spectre/astro/tactical.py:563` | number | `360.0 -> (540.0)` | survived |
| `5a7fefe557` | `spectre/astro/tactical.py:568` | number | `0.0 -> (1.0)` | survived |
| `9fed423325` | `spectre/astro/tactical.py:601` | compare | `abs(delta_raan_deg) < _RAAN_CLOSED_DEG -> (abs(delta_raan_deg) <= _RAAN_CLOSED_DEG)` | survived |
| `03a5156fa0` | `spectre/astro/tactical.py:609` | binop | `R_EARTH + _J2_FLOOR_ALT_KM -> (R_EARTH - _J2_FLOOR_ALT_KM)` | survived |
| `2608cc01d1` | `spectre/astro/tactical.py:611` | binop | `f_lo * excess(hi) -> (f_lo / excess(hi))` | survived |
| `e1dd8dbc2a` | `spectre/astro/tactical.py:611` | compare | `f_lo * excess(hi) > 0.0 -> (f_lo * excess(hi) >= 0.0)` | survived |
| `33d571e59b` | `spectre/astro/tactical.py:611` | number | `0.0 -> (1.0)` | survived |
| `fc6d649638` | `spectre/astro/tactical.py:616` | compare | `f_mid < 0.0 -> (f_mid <= 0.0)` | survived |
| `815b0ca59e` | `spectre/astro/tactical.py:616` | compare | `f_lo < 0.0 -> (f_lo <= 0.0)` | survived |
| `9c89bad3a0` | `spectre/astro/tactical.py:652` | boolop | `math.isfinite(dv_radial) and math.isfinite(dv_along) -> (math.isfinite(dv_radial) or math.isfinite(dv_along))` | survived |
| `b7b48a64ea` | `spectre/astro/tactical.py:653` | return | `return math.inf -> return None` | no_tests |
| `f1b9ce76a0` | `spectre/astro/tactical.py:655` | binop | `dv_radial / n -> (dv_radial * n)` | survived |
| `0f7ea22e20` | `spectre/astro/tactical.py:655` | binop | `dv_radial / n * s + 2.0 * dv_along / n * (1.0 - c) -> (dv_radial / n * s - 2.0 * dv_along / n * (1.0 - c))` | survived |
| `da613344cf` | `spectre/astro/tactical.py:655` | binop | `dv_radial / n * s -> (dv_radial / n / s)` | survived |
| `928974ba1d` | `spectre/astro/tactical.py:656` | number | `2.0 -> (3.0)` | survived |
| `7ddbdee22c` | `spectre/astro/tactical.py:656` | number | `1.0 -> (1.5)` | survived |
| `93288d6b32` | `spectre/astro/tactical.py:656` | binop | `1.0 - c -> (1.0 + c)` | survived |
| `dbb5059cd0` | `spectre/astro/tactical.py:656` | binop | `-2.0 * dv_radial / n * (1.0 - c) + dv_along * (4.0 * s - 3.0 * n * t)  -> (-2.0 * dv_radial / n * (1.0 - c) - dv_along * (4.0 * s - 3.0 * n * t)` | survived |
| `83024a2b48` | `spectre/astro/tactical.py:656` | binop | `-2.0 * dv_radial / n -> (-2.0 * dv_radial * n)` | survived |
| `ea70639628` | `spectre/astro/tactical.py:656` | unary | `-2.0 -> (2.0)` | survived |
| `68e289bd44` | `spectre/astro/tactical.py:656` | binop | `-2.0 * dv_radial / n * (1.0 - c) -> (-2.0 * dv_radial / n / (1.0 - c))` | survived |
| `3e9eefd6d9` | `spectre/astro/tactical.py:687` | compare | `abs(sin_nt) > 1e-12 -> (abs(sin_nt) >= 1e-12)` | survived |
| `6499eeeb9c` | `spectre/astro/tactical.py:687` | number | `1e-12 -> (1.5e-12)` | survived |
| `a87c869a2b` | `spectre/astro/tactical.py:688` | binop | `desired_miss_km * n / abs(sin_nt) -> (desired_miss_km * n * abs(sin_nt))` | survived |
| `2bc7db964e` | `spectre/astro/tactical.py:695` | compare | `coeff_y > 1e-12 -> (coeff_y >= 1e-12)` | survived |
| `fa375047ee` | `spectre/astro/tactical.py:695` | number | `1e-12 -> (1.5e-12)` | survived |
| `516c3ec05d` | `spectre/astro/tactical.py:702` | compare | `abs(sin_nt) > 1e-12 -> (abs(sin_nt) >= 1e-12)` | survived |
| `c6cd8c814e` | `spectre/astro/tactical.py:702` | number | `1e-12 -> (1.5e-12)` | survived |
| `8a7f692466` | `spectre/astro/tactical.py:715` | number | `0.0 -> (1.0)` | survived |
| `310c5c5a00` | `spectre/astro/tactical.py:789` | binop | `abs(longitude_gap_deg) / 1.0 -> (abs(longitude_gap_deg) * 1.0)` | survived |
| `42b9fcf45f` | `spectre/astro/tactical.py:789` | number | `1.0 -> (1.5)` | survived |
| `4a81292c52` | `spectre/astro/tactical.py:800` | binop | `mu / a_geo -> (mu * a_geo)` | survived |
| `1983f42099` | `spectre/astro/tactical.py:801` | binop | `mu * (2.0 / a_geo - 1.0 / drift_sma) -> (mu / (2.0 / a_geo - 1.0 / drift_sma))` | survived |
| `45df50e73f` | `spectre/astro/tactical.py:801` | binop | `2.0 / a_geo - 1.0 / drift_sma -> (2.0 / a_geo + 1.0 / drift_sma)` | survived |
| `563e78b47e` | `spectre/astro/tactical.py:805` | number | `0.0 -> (1.0)` | survived |
| `3154c0e9ae` | `spectre/astro/tactical.py:812` | number | `2.0 -> (3.0)` | survived |
| `216eed9889` | `spectre/astro/tactical.py:831` | number | `300.0 -> (450.0)` | survived |
| `d7645f3590` | `spectre/astro/tactical.py:858` | binop | `a_t**3 -> (a_t * 3)` | survived |
| `1458181825` | `spectre/astro/tactical.py:858` | binop | `a_t**3 / mu -> (a_t ** 3 * mu)` | survived |
| `03ec678d70` | `spectre/astro/tactical.py:858` | number | `3 -> (4)` | survived |
| `6541a4c6ee` | `spectre/astro/tactical.py:858` | binop | `math.pi * math.sqrt(a_t**3 / mu) -> (math.pi / math.sqrt(a_t ** 3 / mu))` | survived |
| `1e51a76da7` | `spectre/astro/tactical.py:915` | binop | `ecc2 - ecc1 -> (ecc2 + ecc1)` | survived |
| `9cb22931fc` | `spectre/astro/tactical.py:929` | compare | `abs(da) > _ALT_CHANGE_KM -> (abs(da) >= _ALT_CHANGE_KM)` | survived |
| `14f6407fde` | `spectre/astro/tactical.py:930` | compare | `di > _INC_CHANGE_DEG -> (di >= _INC_CHANGE_DEG)` | survived |
| `cb9adc1c84` | `spectre/astro/tactical.py:931` | compare | `raan_residual > _RAAN_CHANGE_DEG -> (raan_residual >= _RAAN_CHANGE_DEG)` | survived |
| `d8e43f5581` | `spectre/astro/tactical.py:932` | compare | `abs(de) > _ECC_CHANGE -> (abs(de) >= _ECC_CHANGE)` | survived |
| `e876ada48a` | `spectre/astro/tactical.py:938` | call | `notes_parts.append(f"Δa={da:+.1f} km") -> pass` | survived |
| `6160c8a98b` | `spectre/astro/tactical.py:940` | call | `notes_parts.append(f"Δi={di:.3f}°") -> pass` | survived |
| `7ba7da0250` | `spectre/astro/tactical.py:944` | call | `notes_parts.append(f"Δe={de:+.5f}") -> pass` | no_tests |
| `59dc0daadc` | `spectre/astro/tactical.py:952` | binop | `inc2_deg - inc1_deg -> (inc2_deg + inc1_deg)` | survived |
| `5fea5f940b` | `spectre/astro/tactical.py:953` | binop | `raan2_deg - raan1_deg -> (raan2_deg + raan1_deg)` | survived |
| `4c8f3abaad` | `spectre/astro/tactical.py:961` | number | `5.0 -> (7.5)` | survived |
| `670d79d894` | `spectre/astro/tactical.py:962` | number | `0.05 -> (0.07500000000000001)` | survived |
| `d48dd4a740` | `spectre/astro/tactical.py:963` | number | `0.05 -> (0.07500000000000001)` | survived |
| `d3a93666fb` | `spectre/astro/tactical.py:964` | number | `0.001 -> (0.0015)` | survived |
| `3e742e7635` | `spectre/astro/tactical.py:965` | number | `0.001 -> (0.0015)` | survived |
| `aaab398143` | `spectre/astro/tactical.py:967` | number | `1.0 -> (1.5)` | survived |
| `1ca94ed359` | `spectre/astro/tactical.py:968` | number | `0.01 -> (0.015)` | survived |
| `1a9e7ab4e3` | `spectre/astro/tactical.py:991` | binop | `mu / a2 -> (mu * a2)` | survived |
| `fe865c01f4` | `spectre/astro/tactical.py:994` | compare | `abs(a2 - a1) > _ALT_COST_KM -> (abs(a2 - a1) >= _ALT_COST_KM)` | survived |
| `daaf97dc7e` | `spectre/astro/tactical.py:994` | binop | `v2 - v1 -> (v2 + v1)` | survived |
| `dac4169822` | `spectre/astro/tactical.py:994` | binop | `a2 - a1 -> (a2 + a1)` | survived |
| `0c78450cef` | `spectre/astro/tactical.py:997` | compare | `di > _ANGLE_COST_DEG -> (di >= _ANGLE_COST_DEG)` | survived |
| `4faabc8c4a` | `spectre/astro/tactical.py:1004` | number | `1.0 -> (1.5)` | survived |
| `da46cb8d5d` | `spectre/astro/tactical.py:1004` | number | `1.0 -> (1.5)` | survived |
| `2baee6eb57` | `spectre/astro/tactical.py:1005` | compare | `raan_residual > _ANGLE_COST_DEG -> (raan_residual >= _ANGLE_COST_DEG)` | survived |
| `d3354f6de0` | `spectre/astro/tactical.py:1007` | binop | `dv_altitude**2 -> (dv_altitude * 2)` | survived |
| `bd3528cd4f` | `spectre/astro/tactical.py:1007` | number | `2 -> (3)` | survived |
| `c512183b2d` | `spectre/astro/tactical.py:1012` | boolop | `changes.altitude and not changes.plane -> (changes.altitude or not changes.plane)` | survived |
| `24f5d41c49` | `spectre/astro/tactical.py:1013` | number | `0 -> (1)` | survived |
| `901f3a4718` | `spectre/astro/tactical.py:1013` | compare | `da > 0 -> (da >= 0)` | survived |
| `cddb84505b` | `spectre/astro/tactical.py:1014` | boolop | `changes.plane and not changes.altitude -> (changes.plane or not changes.altitude)` | survived |
| `4a61ef901d` | `spectre/astro/tactical.py:1016` | boolop | `changes.altitude and changes.plane -> (changes.altitude or changes.plane)` | survived |
| `2370600858` | `spectre/astro/tactical.py:1017` | return | `return "combined" -> return None` | survived |
| `319ab70689` | `spectre/astro/tactical.py:1019` | return | `return "radial" -> return None` | no_tests |
| `f8b1f2b69c` | `spectre/astro/tactical.py:1020` | return | `return "combined" -> return None` | survived |
| `3827236c49` | `spectre/astro/tactical.py:1029` | compare | `total_dv < _SK_DV_KM_S -> (total_dv <= _SK_DV_KM_S)` | survived |
| `b615dbf69f` | `spectre/astro/tactical.py:1029` | number | `0.3 -> (0.44999999999999996)` | survived |
| `c82c607e2d` | `spectre/astro/tactical.py:1030` | number | `0.85 -> (1.275)` | survived |
| `33556cdb44` | `spectre/astro/tactical.py:1031` | number | `0.85 -> (1.275)` | survived |
| `c2a3fc86a8` | `spectre/astro/tactical.py:1032` | boolop | `changes.raan and not changes.altitude and not changes.plane -> (changes.raan or not changes.altitude or (not changes.plane))` | survived |
| `60869b4d20` | `spectre/astro/tactical.py:1032` | number | `0.7 -> (1.0499999999999998)` | survived |
| `eb45b40694` | `spectre/astro/tactical.py:1032` | unary | `not changes.plane -> (changes.plane)` | survived |
| `e77e60202c` | `spectre/astro/tactical.py:1032` | unary | `not changes.altitude -> (changes.altitude)` | survived |
| `b696588429` | `spectre/astro/tactical.py:1033` | boolop | `changes.altitude and changes.plane -> (changes.altitude or changes.plane)` | survived |
| `b6b59921bf` | `spectre/astro/tactical.py:1033` | number | `0.75 -> (1.125)` | survived |
| `44a12ec5ec` | `spectre/astro/tactical.py:1034` | boolop | `changes.ecc and abs(da) < _ALT_CHANGE_KM -> (changes.ecc or abs(da) < _ALT_CHANGE_KM)` | survived |
| `9d17224387` | `spectre/astro/tactical.py:1034` | compare | `abs(da) < _ALT_CHANGE_KM -> (abs(da) <= _ALT_CHANGE_KM)` | survived |
| `32ddfa23fb` | `spectre/astro/tactical.py:1034` | number | `0.6 -> (0.8999999999999999)` | survived |
| `db5dec80bd` | `spectre/astro/tactical.py:1036` | number | `0.3 -> (0.44999999999999996)` | survived |
| `22efd31f49` | `spectre/astro/tactical.py:1098` | compare | `radial_amp > 0.01 -> (radial_amp >= 0.01)` | survived |
| `31af5337de` | `spectre/astro/tactical.py:1098` | number | `0.01 -> (0.015)` | survived |
| `7020a9eeec` | `spectre/astro/tactical.py:1115` | compare | `cross_track_km > 0 -> (cross_track_km >= 0)` | survived |
| `f20ef9902a` | `spectre/astro/tactical.py:1115` | binop | `cross_track_km * n -> (cross_track_km / n)` | survived |
| `8b4a079c40` | `spectre/astro/tactical.py:1115` | number | `0 -> (1)` | survived |
| `17dc38dc1c` | `spectre/astro/tactical.py:1116` | number | `2 -> (3)` | survived |
| `a608902686` | `spectre/astro/tactical.py:1116` | binop | `dv_cross**2 -> (dv_cross * 2)` | survived |
| `90aeb1cf65` | `spectre/astro/tactical.py:1123` | compare | `cross_track_km > 0 -> (cross_track_km >= 0)` | survived |
| `dd7d9424c4` | `spectre/astro/tactical.py:1123` | number | `0 -> (1)` | survived |
| `2f53d3c1b8` | `spectre/astro/tactical.py:1124` | call | `notes_parts.append(f"cross-track ±{cross_track_km:.1f} km") -> pass` | survived |
| `94e8c641ce` | `spectre/astro/tactical.py:1126` | call | `notes_parts.append(f"passively safe (margin {safety_margin:.1f} km)") -> pass` | survived |
| `83a2bb9856` | `spectre/astro/tactical.py:1128` | call | `notes_parts.append("NOT passively safe - radial amplitude too small") -> pass` | survived |
| `4da0048a00` | `spectre/astro/tactical.py:1188` | number | `1000.0 -> (1500.0)` | survived |
| `d69610f5aa` | `spectre/astro/tactical.py:1191` | number | `1.0 -> (1.5)` | survived |
| `4a81e5d673` | `spectre/astro/tactical.py:1191` | compare | `dv_m_s < 1.0 -> (dv_m_s <= 1.0)` | survived |
| `06cbcdaf26` | `spectre/astro/tactical.py:1193` | compare | `dv_m_s < 10.0 -> (dv_m_s <= 10.0)` | survived |
| `0c876d9ecf` | `spectre/astro/tactical.py:1193` | number | `10.0 -> (15.0)` | survived |
| `8864d3bf65` | `spectre/astro/tactical.py:1195` | number | `100.0 -> (150.0)` | survived |
| `9a1330dcfe` | `spectre/astro/tactical.py:1195` | compare | `dv_m_s < 100.0 -> (dv_m_s <= 100.0)` | survived |
| `8b0a924b6e` | `spectre/astro/tactical.py:1202` | compare | `altitude_km < _LEO_MAX_ALT -> (altitude_km <= _LEO_MAX_ALT)` | survived |
| `0c1d4252bc` | `spectre/astro/tactical.py:1203` | number | `0.5 -> (0.75)` | survived |
| `93a48ed7f7` | `spectre/astro/tactical.py:1204` | number | `6.0 -> (9.0)` | survived |
| `d20d21ed62` | `spectre/astro/tactical.py:1205` | compare | `altitude_km < _MEO_MAX_ALT -> (altitude_km <= _MEO_MAX_ALT)` | survived |
| `104201cd05` | `spectre/astro/tactical.py:1206` | number | `0.2 -> (0.30000000000000004)` | no_tests |
| `c3b9708b2f` | `spectre/astro/tactical.py:1207` | number | `24.0 -> (36.0)` | no_tests |
| `3237ebca74` | `spectre/astro/tactical.py:1209` | number | `0.1 -> (0.15000000000000002)` | survived |
| `f72b44898a` | `spectre/astro/tactical.py:1210` | number | `48.0 -> (72.0)` | survived |
| `01a21d1299` | `spectre/astro/tactical.py:1215` | number | `0.01 -> (0.015)` | survived |
| `ac0b640613` | `spectre/astro/tactical.py:1215` | compare | `dv_m_s > 0.01 -> (dv_m_s >= 0.01)` | survived |
| `c50557299e` | `spectre/astro/tactical.py:1216` | binop | `base_detection_time / math.log2(1.0 + dv_m_s) -> (base_detection_time * math.log2(1.0 + dv_m_s))` | survived |
| `560e3e4f0d` | `spectre/astro/tactical.py:1216` | number | `1.0 -> (1.5)` | survived |
| `c1d38ba9df` | `spectre/astro/tactical.py:1218` | binop | `base_detection_time * 100.0 -> (base_detection_time / 100.0)` | no_tests |
| `1bfed3a8ab` | `spectre/astro/tactical.py:1218` | number | `100.0 -> (150.0)` | no_tests |
| `fc27a72934` | `spectre/astro/tactical.py:1221` | number | `1.0 -> (1.5)` | survived |
| `ac48900b52` | `spectre/astro/tactical.py:1222` | compare | `manoeuvre_type in ("plane_change", "raan_change") -> (manoeuvre_type not in ('plane_change', 'raan_change'))` | survived |
| `87cfba9fbc` | `spectre/astro/tactical.py:1223` | number | `1.3 -> (1.9500000000000002)` | no_tests |
| `2059bce339` | `spectre/astro/tactical.py:1225` | number | `0.7 -> (1.0499999999999998)` | no_tests |
| `297c6d1b7c` | `spectre/astro/tactical.py:1227` | binop | `detection_prob * type_modifier -> (detection_prob / type_modifier)` | survived |
| `024f252d29` | `spectre/astro/tactical.py:1227` | number | `1.0 -> (1.5)` | survived |
| `fb097b5ad7` | `spectre/astro/tactical.py:1230` | binop | `base_detection_time * 10.0 -> (base_detection_time / 10.0)` | survived |
| `f47c690c32` | `spectre/astro/tactical.py:1230` | binop | `0.4 * detection_prob -> (0.4 / detection_prob)` | survived |
| `80d2c80624` | `spectre/astro/tactical.py:1230` | number | `0.4 -> (0.6000000000000001)` | survived |
| `d5bbb7a295` | `spectre/astro/tactical.py:1230` | binop | `0.4 * detection_prob + 0.3 * min(1.0, dv_m_s / 50.0) + 0.3 * (1.0 - ti -> (0.4 * detection_prob + 0.3 * min(1.0, dv_m_s / 50.0) - 0.3 * (1.0 - t` | survived |
| `0bb093cded` | `spectre/astro/tactical.py:1230` | number | `50.0 -> (75.0)` | survived |
| `6610420bb9` | `spectre/astro/tactical.py:1230` | number | `0.3 -> (0.44999999999999996)` | survived |
| `b8789b0a67` | `spectre/astro/tactical.py:1230` | number | `0.3 -> (0.44999999999999996)` | survived |
| `d54e82ef2f` | `spectre/astro/tactical.py:1230` | binop | `time_hours / (base_detection_time * 10.0) -> (time_hours * (base_detection_time * 10.0))` | survived |
| `63938506d1` | `spectre/astro/tactical.py:1230` | binop | `0.4 * detection_prob + 0.3 * min(1.0, dv_m_s / 50.0) -> (0.4 * detection_prob - 0.3 * min(1.0, dv_m_s / 50.0))` | survived |
| `938c3d749e` | `spectre/astro/tactical.py:1230` | number | `1.0 -> (1.5)` | survived |
| `6b9f99b9f5` | `spectre/astro/tactical.py:1230` | binop | `0.3 * (1.0 - time_hours / (base_detection_time * 10.0)) -> (0.3 / (1.0 - time_hours / (base_detection_time * 10.0)))` | survived |
| `ee502e85c8` | `spectre/astro/tactical.py:1230` | binop | `1.0 - time_hours / (base_detection_time * 10.0) -> (1.0 + time_hours / (base_detection_time * 10.0))` | survived |
| `9c9d9efc67` | `spectre/astro/tactical.py:1230` | binop | `dv_m_s / 50.0 -> (dv_m_s * 50.0)` | survived |
| `af3772ebad` | `spectre/astro/tactical.py:1230` | binop | `0.3 * min(1.0, dv_m_s / 50.0) -> (0.3 / min(1.0, dv_m_s / 50.0))` | survived |
| `fb2b6682b4` | `spectre/astro/tactical.py:1230` | number | `1.0 -> (1.5)` | survived |
| `0886b0230f` | `spectre/astro/tactical.py:1230` | number | `10.0 -> (15.0)` | survived |
| `ae689b4285` | `spectre/astro/tactical.py:1231` | number | `0.0 -> (1.0)` | survived |
| `3cf88822f4` | `spectre/astro/tactical.py:1231` | number | `1.0 -> (1.5)` | survived |
| `39ee335b14` | `spectre/astro/tactical.py:1283` | number | `0.5 -> (0.75)` | survived |
| `abe553f963` | `spectre/astro/tactical.py:1283` | number | `0.25 -> (0.375)` | survived |
| `e3cbcf49f9` | `spectre/astro/tactical.py:1284` | number | `1e-12 -> (1.5e-12)` | survived |
| `d3a253eec1` | `spectre/astro/tactical.py:1300` | compare | `coeff_y > _DEGENERATE -> (coeff_y >= _DEGENERATE)` | survived |
| `0c549a42d7` | `spectre/astro/tactical.py:1301` | compare | `abs(sin_nt) > _DEGENERATE -> (abs(sin_nt) >= _DEGENERATE)` | survived |
| `0861b4655c` | `spectre/astro/tactical.py:1302` | number | `1 -> (2)` | survived |
| `53031f7944` | `spectre/astro/tactical.py:1302` | number | `0 -> (1)` | survived |
| `9848331ff6` | `spectre/astro/tactical.py:1313` | compare | `dv > fuel_budget_km_s -> (dv >= fuel_budget_km_s)` | survived |
| `dc9e4fb8eb` | `spectre/astro/tactical.py:1315` | binop | `dv_actual / dv -> (dv_actual * dv)` | survived |
| `3e514b3ba8` | `spectre/astro/tactical.py:1319` | number | `0.0 -> (1.0)` | survived |
| `6ed133592a` | `spectre/astro/tactical.py:1319` | number | `0.0 -> (1.0)` | survived |
| `ccdac8c5da` | `spectre/astro/tactical.py:1319` | number | `0.0 -> (1.0)` | survived |
| `81f0f587fe` | `spectre/astro/tactical.py:1320` | binop | `dv_actual / dv -> (dv_actual * dv)` | survived |
| `affa95e13f` | `spectre/astro/tactical.py:1320` | compare | `dv_actual == dv -> (dv_actual != dv)` | survived |
| `169affc823` | `spectre/astro/tactical.py:1321` | binop | `dv_actual / fuel_budget_km_s -> (dv_actual * fuel_budget_km_s)` | survived |
| `409ff4e747` | `spectre/astro/tactical.py:1321` | number | `0 -> (1)` | survived |
| `8e6e2d1707` | `spectre/astro/tactical.py:1328` | number | `0 -> (1)` | survived |
| `3cbc6514b2` | `spectre/astro/tactical.py:1329` | number | `1 -> (2)` | survived |
| `13607607ad` | `spectre/astro/tactical.py:1343` | compare | `result.delta_v < best.delta_v -> (result.delta_v <= best.delta_v)` | survived |
| `b591b87428` | `spectre/astro/tactical.py:1345` | compare | `best.resulting_miss_km < desired_miss_km -> (best.resulting_miss_km <= desired_miss_km)` | survived |
| `321984bcae` | `spectre/astro/tactical.py:1345` | compare | `result.resulting_miss_km > best.resulting_miss_km -> (result.resulting_miss_km >= best.resulting_miss_km)` | survived |
| `57d3a11076` | `spectre/astro/tactical.py:1345` | boolop | `best.resulting_miss_km < desired_miss_km and result.resulting_miss_km  -> (best.resulting_miss_km < desired_miss_km or result.resulting_miss_km ` | survived |
| `3dc52e0cb6` | `spectre/astro/tactical.py:1354` | number | `1.0 -> (1.5)` | survived |
| `c37c6c37b0` | `spectre/astro/tactical.py:1394` | number | `0.0 -> (1.0)` | survived |
| `a07aa271a3` | `spectre/astro/tactical.py:1395` | number | `0.0 -> (1.0)` | survived |
| `a0448b53ad` | `spectre/astro/tactical.py:1396` | number | `0.0 -> (1.0)` | survived |
| `3df161f28c` | `spectre/astro/tactical.py:1397` | number | `0.0 -> (1.0)` | survived |
| `116910e0d3` | `spectre/astro/tactical.py:1469` | number | `1.0 -> (1.5)` | survived |
| `b75d55b399` | `spectre/astro/tactical.py:1473` | compare | `range_rate_km_s < _CLOSING_RATE_KM_S -> (range_rate_km_s <= _CLOSING_RATE_KM_S)` | survived |
| `4daf8caf56` | `spectre/astro/tactical.py:1474` | compare | `abs(range_rate_km_s) > 1e-6 -> (abs(range_rate_km_s) >= 1e-06)` | survived |
| `db2fd0d331` | `spectre/astro/tactical.py:1474` | number | `1e-6 -> (1.5e-06)` | survived |
| `b6eba46c23` | `spectre/astro/tactical.py:1474` | boolop | `is_closing and abs(range_rate_km_s) > 1e-6 -> (is_closing or abs(range_rate_km_s) > 1e-06)` | survived |
| `da68936fda` | `spectre/astro/tactical.py:1475` | number | `3600.0 -> (5400.0)` | survived |
| `5ddf60f308` | `spectre/astro/tactical.py:1475` | binop | `relative_range_km / abs(range_rate_km_s) -> (relative_range_km * abs(range_rate_km_s))` | survived |
| `f590581da7` | `spectre/astro/tactical.py:1483` | number | `9999.0 -> (14998.5)` | survived |
| `dab178c165` | `spectre/astro/tactical.py:1491` | number | `0.001 -> (0.0015)` | survived |
| `58db5e0291` | `spectre/astro/tactical.py:1491` | unary | `-0.001 -> (0.001)` | survived |
| `549a639145` | `spectre/astro/tactical.py:1492` | number | `100.0 -> (150.0)` | survived |
| `fa91018e1f` | `spectre/astro/tactical.py:1493` | number | `1000.0 -> (1500.0)` | survived |
| `d14923da52` | `spectre/astro/tactical.py:1494` | number | `200.0 -> (300.0)` | survived |
| `f1d24e4da7` | `spectre/astro/tactical.py:1494` | number | `5.0 -> (7.5)` | survived |
| `9e20c8e1b9` | `spectre/astro/tactical.py:1495` | number | `0.05 -> (0.07500000000000001)` | survived |
| `b9abb4ab8d` | `spectre/astro/tactical.py:1496` | number | `50.0 -> (75.0)` | survived |
| `18fb2d566b` | `spectre/astro/tactical.py:1497` | number | `0.01 -> (0.015)` | survived |
| `5151d5e345` | `spectre/astro/tactical.py:1500` | number | `0.85 -> (1.275)` | survived |
| `898fbaece7` | `spectre/astro/tactical.py:1500` | number | `0.15 -> (0.22499999999999998)` | survived |
| `4d3d3b51aa` | `spectre/astro/tactical.py:1500` | number | `0.7 -> (1.0499999999999998)` | survived |
| `4aae620dca` | `spectre/astro/tactical.py:1506` | compare | `range_rate_km_s < _CLOSING_RATE_KM_S -> (range_rate_km_s <= _CLOSING_RATE_KM_S)` | survived |
| `28df46cd22` | `spectre/astro/tactical.py:1507` | number | `0.3 -> (0.44999999999999996)` | survived |
| `b92b1f98fe` | `spectre/astro/tactical.py:1507` | binop | `abs(range_rate_km_s) / 1.0 -> (abs(range_rate_km_s) * 1.0)` | survived |
| `6e061c8386` | `spectre/astro/tactical.py:1507` | binop | `0.3 * min(1.0, abs(range_rate_km_s) / 1.0) -> (0.3 / min(1.0, abs(range_rate_km_s) / 1.0))` | survived |
| `a62b2875cc` | `spectre/astro/tactical.py:1507` | number | `1.0 -> (1.5)` | survived |
| `f0eb4399b9` | `spectre/astro/tactical.py:1507` | number | `1.0 -> (1.5)` | survived |
| `05f9457347` | `spectre/astro/tactical.py:1508` | call | `evidence.append(f"closing at {abs(range_rate_km_s):.3f} km/s") -> pass` | survived |
| `226ca2c0a1` | `spectre/astro/tactical.py:1509` | compare | `relative_range_km < _PROXIMATE_KM -> (relative_range_km <= _PROXIMATE_KM)` | survived |
| `59e65bd524` | `spectre/astro/tactical.py:1510` | number | `0.25 -> (0.375)` | survived |
| `9afbe6a9b9` | `spectre/astro/tactical.py:1511` | call | `evidence.append(f"range {relative_range_km:.0f} km (proximate)") -> pass` | survived |
| `eb0f63ade0` | `spectre/astro/tactical.py:1512` | compare | `relative_range_km < _APPROACHING_KM -> (relative_range_km <= _APPROACHING_KM)` | survived |
| `1c64a438d0` | `spectre/astro/tactical.py:1513` | number | `1.0 -> (1.5)` | survived |
| `0917cc8c74` | `spectre/astro/tactical.py:1513` | binop | `relative_range_km / _APPROACHING_KM -> (relative_range_km * _APPROACHING_KM)` | survived |
| `45ca8c47c5` | `spectre/astro/tactical.py:1513` | augassign | `score += 0.15 * (1.0 - relative_range_km / _APPROACHING_KM) -> score -= 0.15 * (1.0 - relative_range_km / _APPROACHING_KM)` | survived |
| `5f2cae0d31` | `spectre/astro/tactical.py:1513` | number | `0.15 -> (0.22499999999999998)` | survived |
| `448c9d01ee` | `spectre/astro/tactical.py:1513` | binop | `0.15 * (1.0 - relative_range_km / _APPROACHING_KM) -> (0.15 / (1.0 - relative_range_km / _APPROACHING_KM))` | survived |
| `64174c2613` | `spectre/astro/tactical.py:1513` | binop | `1.0 - relative_range_km / _APPROACHING_KM -> (1.0 + relative_range_km / _APPROACHING_KM)` | survived |
| `391ae0a4ef` | `spectre/astro/tactical.py:1514` | call | `evidence.append(f"range {relative_range_km:.0f} km (approaching)") -> pass` | survived |
| `10c9dc7627` | `spectre/astro/tactical.py:1523` | number | `0.15 -> (0.22499999999999998)` | survived |
| `6e205a7172` | `spectre/astro/tactical.py:1524` | compare | `_ORBIT_MATCH_DA_KM[0] < abs(delta_a_km) < _ORBIT_MATCH_DA_KM[1] -> (_ORBIT_MATCH_DA_KM[0] <= abs(delta_a_km) < _ORBIT_MATCH_DA_KM[1])` | survived |
| `7093046baf` | `spectre/astro/tactical.py:1524` | compare | `_ORBIT_MATCH_DA_KM[0] < abs(delta_a_km) < _ORBIT_MATCH_DA_KM[1] -> (_ORBIT_MATCH_DA_KM[0] < abs(delta_a_km) <= _ORBIT_MATCH_DA_KM[1])` | survived |
| `43e8884f24` | `spectre/astro/tactical.py:1524` | number | `0 -> (1)` | survived |
| `9b036bdf4f` | `spectre/astro/tactical.py:1524` | number | `0.1 -> (0.15000000000000002)` | survived |
| `b7f6b763b1` | `spectre/astro/tactical.py:1526` | compare | `abs(delta_inc_deg) > _PLANE_MATCH_DEG -> (abs(delta_inc_deg) >= _PLANE_MATCH_DEG)` | survived |
| `17ecb347cb` | `spectre/astro/tactical.py:1526` | number | `0.1 -> (0.15000000000000002)` | survived |
| `5d50a7d456` | `spectre/astro/tactical.py:1527` | compare | `abs(delta_raan_deg) > _PLANE_MATCH_DEG -> (abs(delta_raan_deg) >= _PLANE_MATCH_DEG)` | survived |
| `6ca9a6fb2e` | `spectre/astro/tactical.py:1535` | compare | `score > _INTENT_HIGH -> (score >= _INTENT_HIGH)` | survived |
| `3466ea22b7` | `spectre/astro/tactical.py:1536` | compare | `relative_range_km < _INSPECTION_RANGE_KM -> (relative_range_km <= _INSPECTION_RANGE_KM)` | survived |
| `3c8febcc1a` | `spectre/astro/tactical.py:1536` | boolop | `relative_range_km < _INSPECTION_RANGE_KM and abs(range_rate_km_s) < _I -> (relative_range_km < _INSPECTION_RANGE_KM or abs(range_rate_km_s) < _I` | survived |
| `a07561e7d4` | `spectre/astro/tactical.py:1536` | compare | `abs(range_rate_km_s) < _INSPECTION_RATE_KM_S -> (abs(range_rate_km_s) <= _INSPECTION_RATE_KM_S)` | survived |
| `11fb359a6f` | `spectre/astro/tactical.py:1537` | compare | `score > _INTENT_CRITICAL -> (score >= _INTENT_CRITICAL)` | survived |
| `9c14bb9233` | `spectre/astro/tactical.py:1539` | compare | `score > _INTENT_REPOSITION -> (score >= _INTENT_REPOSITION)` | survived |
| `76ed682e2f` | `spectre/astro/tactical.py:1541` | compare | `score > _INTENT_SK -> (score >= _INTENT_SK)` | survived |
| `dabf95c5c2` | `spectre/astro/tactical.py:1542` | return | `return "station_keeping", "low" -> return None` | survived |
| `54dd1af9d3` | `spectre/astro/tactical.py:1578` | number | `0.5 -> (0.75)` | survived |
| `f8302a8304` | `spectre/astro/tactical.py:1579` | number | `48.0 -> (72.0)` | survived |
| `0005438288` | `spectre/astro/tactical.py:1580` | number | `24 -> (25)` | survived |
| `3a647679af` | `spectre/astro/tactical.py:1615` | binop | `(r1 + r2) / 2.0 -> ((r1 + r2) * 2.0)` | survived |
| `b8bf1a70a5` | `spectre/astro/tactical.py:1616` | binop | `2.0 / r1 -> (2.0 * r1)` | survived |
| `5452c06dcf` | `spectre/astro/tactical.py:1616` | binop | `2.0 / r1 - 1.0 / a_h -> (2.0 / r1 + 1.0 / a_h)` | survived |
| `6b57478c89` | `spectre/astro/tactical.py:1616` | number | `1.0 -> (1.5)` | survived |
| `423886820d` | `spectre/astro/tactical.py:1616` | binop | `mu * (2.0 / r1 - 1.0 / a_h) -> (mu / (2.0 / r1 - 1.0 / a_h))` | survived |
| `75d361ff31` | `spectre/astro/tactical.py:1616` | number | `2.0 -> (3.0)` | survived |
| `123edd94ae` | `spectre/astro/tactical.py:1617` | binop | `2.0 / r2 - 1.0 / a_h -> (2.0 / r2 + 1.0 / a_h)` | survived |
| `3f8dcb8da8` | `spectre/astro/tactical.py:1617` | number | `2.0 -> (3.0)` | survived |
| `90730853bf` | `spectre/astro/tactical.py:1617` | binop | `2.0 / r2 -> (2.0 * r2)` | survived |
| `c92c1881f0` | `spectre/astro/tactical.py:1617` | binop | `mu * (2.0 / r2 - 1.0 / a_h) -> (mu / (2.0 / r2 - 1.0 / a_h))` | survived |
| `43d5fb4bc2` | `spectre/astro/tactical.py:1618` | binop | `v2 - v_h_arr -> (v2 + v_h_arr)` | survived |
| `8898aaa247` | `spectre/astro/tactical.py:1618` | binop | `v_h_dep - v1 -> (v_h_dep + v1)` | survived |
| `1be216f37d` | `spectre/astro/tactical.py:1618` | binop | `abs(v_h_dep - v1) + abs(v2 - v_h_arr) -> (abs(v_h_dep - v1) - abs(v2 - v_h_arr))` | survived |
| `16e794d643` | `spectre/astro/tactical.py:1619` | binop | `math.pi * math.sqrt(a_h**3 / mu) -> (math.pi / math.sqrt(a_h ** 3 / mu))` | survived |
| `a307a20912` | `spectre/astro/tactical.py:1619` | number | `3600.0 -> (5400.0)` | survived |
| `238e082083` | `spectre/astro/tactical.py:1619` | binop | `a_h**3 -> (a_h * 3)` | survived |
| `d6e78044c5` | `spectre/astro/tactical.py:1619` | number | `3 -> (4)` | survived |
| `66dbad3d74` | `spectre/astro/tactical.py:1624` | number | `0 -> (1)` | survived |
| `c43cfeb4d6` | `spectre/astro/tactical.py:1626` | binop | `tof_max_hours - tof_min_hours -> (tof_max_hours + tof_min_hours)` | survived |
| `4fdb8442ba` | `spectre/astro/tactical.py:1626` | number | `1 -> (2)` | survived |
| `c114fc393a` | `spectre/astro/tactical.py:1626` | number | `1 -> (2)` | survived |
| `5852f50007` | `spectre/astro/tactical.py:1626` | binop | `(tof_max_hours - tof_min_hours) / max(n_steps - 1, 1) -> ((tof_max_hours - tof_min_hours) * max(n_steps - 1, 1))` | survived |
| `bee839df79` | `spectre/astro/tactical.py:1626` | binop | `n_steps - 1 -> (n_steps + 1)` | survived |
| `21b498f49a` | `spectre/astro/tactical.py:1628` | binop | `tof_min_hours + i * dt -> (tof_min_hours - i * dt)` | survived |
| `144b81d09c` | `spectre/astro/tactical.py:1628` | binop | `i * dt -> (i / dt)` | survived |
| `cb1cb2b536` | `spectre/astro/tactical.py:1629` | binop | `tof_h * 3600.0 -> (tof_h / 3600.0)` | survived |
| `f2fa4745c0` | `spectre/astro/tactical.py:1629` | number | `3600.0 -> (5400.0)` | survived |
| `43efc53c9c` | `spectre/astro/tactical.py:1634` | number | `3.0 -> (4.5)` | survived |
| `bf4c686666` | `spectre/astro/tactical.py:1634` | binop | `(tof_s / math.pi) ** 2 -> (tof_s / math.pi * 2)` | survived |
| `613de66426` | `spectre/astro/tactical.py:1634` | binop | `mu * (tof_s / math.pi) ** 2 -> (mu / (tof_s / math.pi) ** 2)` | survived |
| `08022286fc` | `spectre/astro/tactical.py:1635` | binop | `(r1 + r2) / 2.0 -> ((r1 + r2) * 2.0)` | survived |
| `48e798d68f` | `spectre/astro/tactical.py:1635` | binop | `r1 + r2 -> (r1 - r2)` | survived |
| `9ea4dd7800` | `spectre/astro/tactical.py:1635` | number | `2.0 -> (3.0)` | survived |
| `a558de4d24` | `spectre/astro/tactical.py:1635` | binop | `(r1 + r2) / 2.0 * 0.8 -> ((r1 + r2) / 2.0 / 0.8)` | survived |
| `0b9fd83d7f` | `spectre/astro/tactical.py:1635` | number | `0.8 -> (1.2000000000000002)` | survived |
| `ccfed15933` | `spectre/astro/tactical.py:1639` | number | `2.0 -> (3.0)` | survived |
| `0044519a49` | `spectre/astro/tactical.py:1639` | number | `1.0 -> (1.5)` | survived |
| `e034c7f9fd` | `spectre/astro/tactical.py:1639` | number | `0 -> (1)` | survived |
| `6fa0e5473b` | `spectre/astro/tactical.py:1640` | number | `2.0 -> (3.0)` | survived |
| `dd735aa1ae` | `spectre/astro/tactical.py:1640` | number | `0 -> (1)` | survived |
| `2cc48b8fdd` | `spectre/astro/tactical.py:1640` | number | `1.0 -> (1.5)` | survived |
| `d51510ede9` | `spectre/astro/tactical.py:1645` | binop | `abs(v_dep - v1) + abs(v2 - v_arr) -> (abs(v_dep - v1) - abs(v2 - v_arr))` | survived |
| `0bfd5fe657` | `spectre/astro/tactical.py:1648` | compare | `tof_h < tof_hohmann -> (tof_h <= tof_hohmann)` | survived |
| `4e7b6ad182` | `spectre/astro/tactical.py:1649` | binop | `(tof_hohmann / max(tof_h, 0.1)) ** 0.5 -> (tof_hohmann / max(tof_h, 0.1) * 0.5)` | survived |
| `1fd83e86de` | `spectre/astro/tactical.py:1649` | binop | `tof_hohmann / max(tof_h, 0.1) -> (tof_hohmann * max(tof_h, 0.1))` | survived |
| `dcd5f40461` | `spectre/astro/tactical.py:1649` | number | `0.5 -> (0.75)` | survived |
| `39cc2f7507` | `spectre/astro/tactical.py:1649` | number | `0.1 -> (0.15000000000000002)` | survived |
| `782cf3a69c` | `spectre/astro/tactical.py:1650` | binop | `dv * penalty -> (dv / penalty)` | survived |
| `df0c56e6b2` | `spectre/astro/tactical.py:1652` | compare | `dv <= max_delta_v -> (dv < max_delta_v)` | survived |
| `9d095901c3` | `spectre/astro/tactical.py:1653` | call | `points.append(EnvelopePoint(tof_hours=tof_h, delta_v_km_s=dv, feasible -> pass` | survived |
| `47ffd2d554` | `spectre/astro/tactical.py:1656` | number | `1 -> (2)` | survived |
| `29db3a18a6` | `spectre/astro/tactical.py:1657` | compare | `tof_h < min_feas_tof -> (tof_h <= min_feas_tof)` | survived |
| `32f61cdb6a` | `spectre/astro/tactical.py:1659` | compare | `dv < min_feas_dv -> (dv <= min_feas_dv)` | survived |
| `82ceddcc4c` | `spectre/astro/tactical.py:1666` | number | `0.0 -> (1.0)` | survived |
| `7cb819004b` | `spectre/astro/tactical.py:1666` | compare | `feasible > 0 -> (feasible >= 0)` | survived |
| `ec2a64e893` | `spectre/astro/tactical.py:1666` | number | `0 -> (1)` | survived |
| `115a838b5d` | `spectre/astro/tactical.py:1667` | compare | `feasible > 0 -> (feasible >= 0)` | survived |
| `85a17045f2` | `spectre/astro/tactical.py:1667` | number | `0 -> (1)` | survived |
| `c535462073` | `spectre/astro/tactical.py:1667` | number | `0.0 -> (1.0)` | survived |
| `1c275cddca` | `spectre/astro/tactical.py:1731` | number | `0 -> (1)` | survived |
| `10d3b4eb5e` | `spectre/astro/tactical.py:1731` | number | `2 -> (3)` | survived |
| `d46c547a16` | `spectre/astro/tactical.py:1731` | binop | `dz0**2 + (dvz0 / n)**2 -> (dz0 ** 2 - (dvz0 / n) ** 2)` | survived |
| `514aaf7e58` | `spectre/astro/tactical.py:1731` | binop | `dvz0 / n -> (dvz0 * n)` | survived |
| `cccf1b6cb0` | `spectre/astro/tactical.py:1731` | binop | `(dvz0 / n)**2 -> (dvz0 / n * 2)` | survived |
| `daa40506f2` | `spectre/astro/tactical.py:1731` | compare | `n > 0 -> (n >= 0)` | survived |
| `fb006814be` | `spectre/astro/tactical.py:1731` | number | `2 -> (3)` | survived |
| `71b43a534e` | `spectre/astro/tactical.py:1734` | number | `0.1 -> (0.15000000000000002)` | survived |
| `46a316f100` | `spectre/astro/tactical.py:1734` | compare | `abs(secular_drift_per_orbit) < 0.1 -> (abs(secular_drift_per_orbit) <= 0.1)` | survived |
| `ed11e03068` | `spectre/astro/tactical.py:1735` | number | `0.001 -> (0.0015)` | survived |
| `63c26effe7` | `spectre/astro/tactical.py:1735` | compare | `abs(secular_drift_per_orbit) < 0.001 -> (abs(secular_drift_per_orbit) <= 0.001)` | survived |
| `4a941f2c14` | `spectre/astro/tactical.py:1737` | compare | `abs(secular_drift_per_orbit) < 0.1 -> (abs(secular_drift_per_orbit) <= 0.1)` | survived |
| `44f11f78e3` | `spectre/astro/tactical.py:1737` | number | `0.1 -> (0.15000000000000002)` | survived |
| `f6b943523b` | `spectre/astro/tactical.py:1738` | number | `0.8 -> (1.2000000000000002)` | no_tests |
| `e7e92987ed` | `spectre/astro/tactical.py:1739` | compare | `abs(secular_drift_per_orbit) < 1.0 -> (abs(secular_drift_per_orbit) <= 1.0)` | survived |
| `d3e8278b4a` | `spectre/astro/tactical.py:1739` | number | `1.0 -> (1.5)` | survived |
| `378497653e` | `spectre/astro/tactical.py:1740` | number | `0.5 -> (0.75)` | no_tests |
| `0120c19f43` | `spectre/astro/tactical.py:1741` | number | `10.0 -> (15.0)` | survived |
| `423f1f5185` | `spectre/astro/tactical.py:1741` | compare | `abs(secular_drift_per_orbit) < 10.0 -> (abs(secular_drift_per_orbit) <= 10.0)` | survived |
| `5e4376e9c3` | `spectre/astro/tactical.py:1742` | number | `0.2 -> (0.30000000000000004)` | no_tests |
| `78ea70a50d` | `spectre/astro/tactical.py:1744` | number | `0.0 -> (1.0)` | survived |
| `764833433c` | `spectre/astro/tactical.py:1748` | call | `notes_parts.append("bounded (non-drifting) relative motion") -> pass` | survived |
| `95b9fef2a7` | `spectre/astro/tactical.py:1750` | call | `notes_parts.append(f"secular drift {secular_drift_per_orbit:.2f} km/or -> pass` | survived |
| `147cae4638` | `spectre/astro/tactical.py:1751` | call | `notes_parts.append(f"radial ±{radial_extent:.2f} km, cross-track ±{A_z -> pass` | survived |
| `d4b8f39ed4` | `spectre/astro/tactical.py:1752` | call | `notes_parts.append(f"drift indicator (Δvy+2nΔx) = {drift_indicator:.4e -> pass` | survived |
| `192347ab66` | `spectre/astro/tactical.py:1797` | number | `37000.0 -> (55500.0)` | survived |
| `40f0b5deb0` | `spectre/astro/tactical.py:1798` | number | `5.0 -> (7.5)` | survived |
| `27ce723974` | `spectre/astro/tactical.py:1799` | number | `20.0 -> (30.0)` | survived |
| `817a64c864` | `spectre/astro/tactical.py:1799` | number | `10.0 -> (15.0)` | survived |
| `370f04761f` | `spectre/astro/tactical.py:1801` | number | `0.01 -> (0.015)` | survived |
| `9c5e84209d` | `spectre/astro/tactical.py:1802` | number | `2000.0 -> (3000.0)` | survived |
| `3c42586fdf` | `spectre/astro/tactical.py:1803` | number | `0.5 -> (0.75)` | survived |
| `af9085a130` | `spectre/astro/tactical.py:1803` | number | `20.0 -> (30.0)` | survived |
| `4eb58049c5` | `spectre/astro/tactical.py:1804` | number | `100.0 -> (150.0)` | survived |
| `e5bcfb18ca` | `spectre/astro/tactical.py:1805` | number | `1500.0 -> (2250.0)` | survived |
| `9aed4e8d4b` | `spectre/astro/tactical.py:1806` | number | `0.1 -> (0.15000000000000002)` | survived |
| `94811bb7ca` | `spectre/astro/tactical.py:1807` | number | `10.0 -> (15.0)` | survived |
| `196659fb3f` | `spectre/astro/tactical.py:1808` | number | `1000.0 -> (1500.0)` | survived |
| `e6fb201d23` | `spectre/astro/tactical.py:1809` | number | `500.0 -> (750.0)` | survived |
| `84a4c60f01` | `spectre/astro/tactical.py:1809` | number | `10.0 -> (15.0)` | survived |
| `5ad0838364` | `spectre/astro/tactical.py:1810` | number | `0.05 -> (0.07500000000000001)` | survived |
| `183a55311c` | `spectre/astro/tactical.py:1811` | number | `20.0 -> (30.0)` | survived |
| `13f7e7101b` | `spectre/astro/tactical.py:1812` | number | `20.0 -> (30.0)` | survived |
| `6e012f134d` | `spectre/astro/tactical.py:1812` | number | `180.0 -> (270.0)` | survived |
| `ba005e6375` | `spectre/astro/tactical.py:1813` | number | `100.0 -> (150.0)` | survived |
| `1b91735431` | `spectre/astro/tactical.py:1813` | number | `50.0 -> (75.0)` | survived |
| `68db0d1ac5` | `spectre/astro/tactical.py:1818` | compare | `band[0] < value < band[1] -> (band[0] <= value < band[1])` | survived |
| `97b50fa2b3` | `spectre/astro/tactical.py:1818` | compare | `band[0] < value < band[1] -> (band[0] < value <= band[1])` | survived |
| `01f8d04bfa` | `spectre/astro/tactical.py:1838` | number | `0.4 -> (0.6000000000000001)` | survived |
| `3abbdbf75c` | `spectre/astro/tactical.py:1839` | compare | `s.dv_ms < _FP_GEO_SK_DV_MS -> (s.dv_ms <= _FP_GEO_SK_DV_MS)` | survived |
| `78b87f271a` | `spectre/astro/tactical.py:1839` | number | `0.3 -> (0.44999999999999996)` | survived |
| `b918415ed7` | `spectre/astro/tactical.py:1839` | boolop | `in_band and s.dv_ms < _FP_GEO_SK_DV_MS -> (in_band or s.dv_ms < _FP_GEO_SK_DV_MS)` | survived |
| `07b8478a2e` | `spectre/astro/tactical.py:1840` | compare | `s.direction in ("prograde", "retrograde", "normal") -> (s.direction not in ('prograde', 'retrograde', 'normal'))` | survived |
| `8fcb6f7e70` | `spectre/astro/tactical.py:1840` | boolop | `in_band and s.direction in ("prograde", "retrograde", "normal") -> (in_band or s.direction in ('prograde', 'retrograde', 'normal'))` | survived |
| `3002a01e93` | `spectre/astro/tactical.py:1840` | number | `0.1 -> (0.15000000000000002)` | survived |
| `407647d6df` | `spectre/astro/tactical.py:1841` | number | `0.2 -> (0.30000000000000004)` | survived |
| `6d8fed61ed` | `spectre/astro/tactical.py:1841` | boolop | `in_band and _inside(s.repeat_days, _FP_GEO_SK_CYCLE_DAYS) -> (in_band or _inside(s.repeat_days, _FP_GEO_SK_CYCLE_DAYS))` | survived |
| `aa931ba8bc` | `spectre/astro/tactical.py:1849` | compare | `s.eccentricity < _FP_NEAR_CIRCULAR_ECC -> (s.eccentricity <= _FP_NEAR_CIRCULAR_ECC)` | survived |
| `0e3eec8bde` | `spectre/astro/tactical.py:1849` | number | `0.1 -> (0.15000000000000002)` | survived |
| `70e592691f` | `spectre/astro/tactical.py:1850` | compare | `s.altitude_km < _FP_LEO_KM -> (s.altitude_km <= _FP_LEO_KM)` | survived |
| `fe26d63f66` | `spectre/astro/tactical.py:1850` | boolop | `s.altitude_km < _FP_LEO_KM or _in_geo_band(s.altitude_km) -> (s.altitude_km < _FP_LEO_KM and _in_geo_band(s.altitude_km))` | survived |
| `4583ac92b9` | `spectre/astro/tactical.py:1857` | compare | `s.dv_ms > _FP_ASAT_DV_MS -> (s.dv_ms >= _FP_ASAT_DV_MS)` | survived |
| `547126798c` | `spectre/astro/tactical.py:1857` | number | `0.3 -> (0.44999999999999996)` | survived |
| `84978e3828` | `spectre/astro/tactical.py:1858` | number | `0.3 -> (0.44999999999999996)` | survived |
| `cc38bf8548` | `spectre/astro/tactical.py:1859` | number | `0.2 -> (0.30000000000000004)` | survived |
| `a3d8e7554a` | `spectre/astro/tactical.py:1859` | compare | `s.altitude_km < _FP_ASAT_ALT_KM -> (s.altitude_km <= _FP_ASAT_ALT_KM)` | survived |
| `e91517f589` | `spectre/astro/tactical.py:1860` | number | `0.1 -> (0.15000000000000002)` | survived |
| `2295a23efb` | `spectre/astro/tactical.py:1860` | compare | `s.eccentricity > _FP_ECCENTRIC -> (s.eccentricity >= _FP_ECCENTRIC)` | survived |
| `ca15b5838f` | `spectre/astro/tactical.py:1866` | compare | `s.dv_ms < _FP_AVOIDANCE_DV_MS -> (s.dv_ms <= _FP_AVOIDANCE_DV_MS)` | survived |
| `7c91ce68b5` | `spectre/astro/tactical.py:1868` | compare | `s.altitude_km < _FP_AVOIDANCE_ALT_KM -> (s.altitude_km <= _FP_AVOIDANCE_ALT_KM)` | survived |
| `56124558fb` | `spectre/astro/tactical.py:1874` | number | `0.3 -> (0.44999999999999996)` | survived |
| `834129ed4e` | `spectre/astro/tactical.py:1876` | compare | `s.eccentricity < _FP_RAISE_ECC -> (s.eccentricity <= _FP_RAISE_ECC)` | survived |
| `0476eaaf50` | `spectre/astro/tactical.py:1876` | number | `0.1 -> (0.15000000000000002)` | survived |
| `f3a0ab86ee` | `spectre/astro/tactical.py:1882` | number | `0.2 -> (0.30000000000000004)` | survived |
| `6528a033f8` | `spectre/astro/tactical.py:1882` | compare | `s.dv_ms < _FP_MAINTENANCE_DV_MS -> (s.dv_ms <= _FP_MAINTENANCE_DV_MS)` | survived |
| `9ef823bd7f` | `spectre/astro/tactical.py:1883` | number | `0.2 -> (0.30000000000000004)` | survived |
| `9f5081bf0d` | `spectre/astro/tactical.py:1883` | compare | `s.direction in ("prograde", "retrograde") -> (s.direction not in ('prograde', 'retrograde'))` | survived |
| `cbc80a9950` | `spectre/astro/tactical.py:1884` | number | `0.3 -> (0.44999999999999996)` | survived |
| `9c7b025379` | `spectre/astro/tactical.py:1885` | number | `0.1 -> (0.15000000000000002)` | survived |
| `e60b47ee72` | `spectre/astro/tactical.py:1908` | number | `0.0 -> (1.0)` | survived |
| `919eb20cf1` | `spectre/astro/tactical.py:1930` | number | `1000.0 -> (1500.0)` | survived |
| `8a599961ed` | `spectre/astro/tactical.py:1933` | number | `1.0 -> (1.5)` | survived |
| `004705f34f` | `spectre/astro/tactical.py:1941` | number | `0.3 -> (0.44999999999999996)` | survived |
| `354c38aed4` | `spectre/astro/tactical.py:1941` | compare | `confidence < 0.3 -> (confidence <= 0.3)` | survived |
| `0b49de2907` | `spectre/astro/tactical.py:1961` | number | `2000 -> (2001)` | survived |
| `f7f6d04678` | `spectre/astro/tactical.py:1977` | number | `1 -> (2)` | survived |
| `8e6c069ac7` | `spectre/astro/tactical.py:1977` | binop | `_SLOT_SAMPLES + 1 -> (_SLOT_SAMPLES - 1)` | survived |
| `6dbc3f7007` | `spectre/astro/tactical.py:1998` | number | `50.0 -> (75.0)` | survived |
| `bbc29628d1` | `spectre/astro/tactical.py:2025` | compare | `formation_displacement < formation_spacing_km -> (formation_displacement <= formation_spacing_km)` | survived |
| `42c2adbe4c` | `spectre/astro/tactical.py:2066` | number | `36200.0 -> (54300.0)` | survived |
| `71b067b2ad` | `spectre/astro/tactical.py:2067` | number | `1000.0 -> (1500.0)` | survived |
| `26b1cd5a2f` | `spectre/astro/tactical.py:2067` | number | `700.0 -> (1050.0)` | survived |
| `6eb0fcceaf` | `spectre/astro/tactical.py:2068` | number | `400.0 -> (600.0)` | survived |
| `4cfee6ef9e` | `spectre/astro/tactical.py:2069` | number | `1200.0 -> (1800.0)` | survived |
| `f488981e7c` | `spectre/astro/tactical.py:2070` | number | `200.0 -> (300.0)` | survived |
| `3d9df99ff3` | `spectre/astro/tactical.py:2071` | number | `1500.0 -> (2250.0)` | survived |
| `b635334f60` | `spectre/astro/tactical.py:2072` | number | `100.0 -> (150.0)` | survived |
| `276a9649d1` | `spectre/astro/tactical.py:2072` | number | `96.0 -> (144.0)` | survived |
| `814d761425` | `spectre/astro/tactical.py:2073` | number | `500.0 -> (750.0)` | survived |
| `cff0726196` | `spectre/astro/tactical.py:2073` | number | `900.0 -> (1350.0)` | survived |
| `659cac14d1` | `spectre/astro/tactical.py:2074` | number | `400.0 -> (600.0)` | survived |
| `a901d25143` | `spectre/astro/tactical.py:2074` | number | `600.0 -> (900.0)` | survived |
| `843e998f45` | `spectre/astro/tactical.py:2075` | number | `40.0 -> (60.0)` | survived |
| `efa6152d13` | `spectre/astro/tactical.py:2075` | number | `60.0 -> (90.0)` | survived |
| `72eb2981f0` | `spectre/astro/tactical.py:2076` | number | `2000.0 -> (3000.0)` | survived |
| `ae320f60a4` | `spectre/astro/tactical.py:2077` | number | `1000.0 -> (1500.0)` | survived |
| `33018ce206` | `spectre/astro/tactical.py:2082` | compare | `band[0] <= value <= band[1] -> (band[0] < value <= band[1])` | survived |
| `f767461fae` | `spectre/astro/tactical.py:2082` | compare | `band[0] <= value <= band[1] -> (band[0] <= value < band[1])` | survived |
| `549fdb0e56` | `spectre/astro/tactical.py:2093` | number | `1.0 -> (1.5)` | survived |
| `1e5503add5` | `spectre/astro/tactical.py:2094` | compare | `extreme_top < altitude_km <= _DEBRIS_HIGH_TOP_KM -> (extreme_top < altitude_km < _DEBRIS_HIGH_TOP_KM)` | survived |
| `5d4d2ad086` | `spectre/astro/tactical.py:2094` | boolop | `_DEBRIS_HIGH_LOW_KM <= altitude_km <= extreme_low or extreme_top < alt -> (_DEBRIS_HIGH_LOW_KM <= altitude_km <= extreme_low and extreme_top < a` | survived |
| `c85af88527` | `spectre/astro/tactical.py:2094` | compare | `_DEBRIS_HIGH_LOW_KM <= altitude_km <= extreme_low -> (_DEBRIS_HIGH_LOW_KM <= altitude_km < extreme_low)` | survived |
| `fd49d49917` | `spectre/astro/tactical.py:2094` | compare | `_DEBRIS_HIGH_LOW_KM <= altitude_km <= extreme_low -> (_DEBRIS_HIGH_LOW_KM < altitude_km <= extreme_low)` | survived |
| `c7913b7c9c` | `spectre/astro/tactical.py:2094` | compare | `extreme_top < altitude_km <= _DEBRIS_HIGH_TOP_KM -> (extreme_top <= altitude_km <= _DEBRIS_HIGH_TOP_KM)` | survived |
| `c86122f6c3` | `spectre/astro/tactical.py:2095` | number | `0.7 -> (1.0499999999999998)` | no_tests |
| `cae2c65566` | `spectre/astro/tactical.py:2096` | compare | `_DEBRIS_MEDIUM_LOW_KM <= altitude_km < _DEBRIS_HIGH_LOW_KM -> (_DEBRIS_MEDIUM_LOW_KM <= altitude_km <= _DEBRIS_HIGH_LOW_KM)` | survived |
| `aa315e6662` | `spectre/astro/tactical.py:2096` | compare | `_DEBRIS_MEDIUM_LOW_KM <= altitude_km < _DEBRIS_HIGH_LOW_KM -> (_DEBRIS_MEDIUM_LOW_KM < altitude_km < _DEBRIS_HIGH_LOW_KM)` | survived |
| `12b4a02552` | `spectre/astro/tactical.py:2097` | compare | `_DEBRIS_HIGH_TOP_KM < altitude_km <= _DEBRIS_MEDIUM_TOP_KM -> (_DEBRIS_HIGH_TOP_KM < altitude_km < _DEBRIS_MEDIUM_TOP_KM)` | survived |
| `90163a54e2` | `spectre/astro/tactical.py:2097` | compare | `_DEBRIS_HIGH_TOP_KM < altitude_km <= _DEBRIS_MEDIUM_TOP_KM -> (_DEBRIS_HIGH_TOP_KM <= altitude_km <= _DEBRIS_MEDIUM_TOP_KM)` | survived |
| `656a8dc1dd` | `spectre/astro/tactical.py:2098` | number | `0.4 -> (0.6000000000000001)` | survived |
| `b5e3177ff3` | `spectre/astro/tactical.py:2102` | number | `0.1 -> (0.15000000000000002)` | survived |
| `f05b82d15c` | `spectre/astro/tactical.py:2104` | boolop | `_within(inclination_deg, _SSO_INC_DEG) and _within(altitude_km, _SSO_A -> (_within(inclination_deg, _SSO_INC_DEG) or _within(altitude_km, _SSO_A` | survived |
| `36013655e3` | `spectre/astro/tactical.py:2105` | number | `0.9 -> (1.35)` | survived |
| `0f9f156b94` | `spectre/astro/tactical.py:2110` | boolop | `_within(altitude_km, _ISS_CORRIDOR_KM) and _within(inclination_deg, _I -> (_within(altitude_km, _ISS_CORRIDOR_KM) or _within(inclination_deg, _I` | survived |
| `a72b985cb2` | `spectre/astro/tactical.py:2111` | return | `return "saturated" -> return None` | no_tests |
| `a70e77d6f4` | `spectre/astro/tactical.py:2114` | compare | `altitude_km < _TERRAIN_LEO_KM -> (altitude_km <= _TERRAIN_LEO_KM)` | survived |
| `7c9417bc8a` | `spectre/astro/tactical.py:2117` | number | `0.1 -> (0.15000000000000002)` | survived |
| `3443ea7191` | `spectre/astro/tactical.py:2117` | number | `0.9 -> (1.35)` | survived |
| `bb6909f2e2` | `spectre/astro/tactical.py:2117` | number | `0.3 -> (0.44999999999999996)` | survived |
| `7f4139be7b` | `spectre/astro/tactical.py:2122` | number | `0.8 -> (1.2000000000000002)` | no_tests |
| `b47a8a46ea` | `spectre/astro/tactical.py:2122` | number | `5000.0 -> (7500.0)` | no_tests |
| `17e1e48ae4` | `spectre/astro/tactical.py:2123` | number | `12000.0 -> (18000.0)` | no_tests |
| `2bed4e4d21` | `spectre/astro/tactical.py:2123` | number | `1.0 -> (1.5)` | no_tests |
| `8190aee878` | `spectre/astro/tactical.py:2124` | number | `0.7 -> (1.0499999999999998)` | no_tests |
| `e10decddb5` | `spectre/astro/tactical.py:2124` | number | `20000.0 -> (30000.0)` | no_tests |
| `95c5967f8e` | `spectre/astro/tactical.py:2125` | number | `0.3 -> (0.44999999999999996)` | no_tests |
| `a7c4b8ccce` | `spectre/astro/tactical.py:2125` | number | `35000.0 -> (52500.0)` | no_tests |
| `2669a3a835` | `spectre/astro/tactical.py:2130` | compare | `altitude_km >= _INNER_BELT_FLOOR_KM -> (altitude_km > _INNER_BELT_FLOOR_KM)` | survived |
| `fd34c50af7` | `spectre/astro/tactical.py:2132` | compare | `altitude_km <= upper -> (altitude_km < upper)` | survived |
| `1576551430` | `spectre/astro/tactical.py:2169` | boolop | `altitude_km > 200 and altitude_km < 36000 -> (altitude_km > 200 or altitude_km < 36000)` | survived |
| `fbc436223a` | `spectre/astro/tactical.py:2169` | compare | `altitude_km < 36000 -> (altitude_km <= 36000)` | survived |
| `3cc6e9b8c9` | `spectre/astro/tactical.py:2169` | number | `200 -> (201)` | survived |
| `e50f655f56` | `spectre/astro/tactical.py:2169` | number | `36000 -> (36001)` | survived |
| `8454cca9b9` | `spectre/astro/tactical.py:2169` | compare | `altitude_km > 200 -> (altitude_km >= 200)` | survived |
| `3d93583ea9` | `spectre/astro/tactical.py:2171` | compare | `altitude_km > 1000 -> (altitude_km >= 1000)` | survived |
| `829a6e9cf9` | `spectre/astro/tactical.py:2171` | boolop | `is_gto and inclination_deg < 30 and altitude_km > 1000 -> (is_gto or inclination_deg < 30 or altitude_km > 1000)` | survived |
| `289e2e296d` | `spectre/astro/tactical.py:2171` | compare | `inclination_deg < 30 -> (inclination_deg <= 30)` | survived |
| `20dd486cd3` | `spectre/astro/tactical.py:2171` | number | `1000 -> (1001)` | survived |
| `25d8549ee7` | `spectre/astro/tactical.py:2171` | number | `30 -> (31)` | survived |
| `2ed4af2d6b` | `spectre/astro/tactical.py:2174` | number | `0.0 -> (1.0)` | survived |
| `8f191d7131` | `spectre/astro/tactical.py:2175` | number | `1.0 -> (1.5)` | survived |
| `ca31d5dac1` | `spectre/astro/tactical.py:2211` | number | `1e-6 -> (1.5e-06)` | survived |
| `44b58623c4` | `spectre/astro/tactical.py:2231` | number | `3 -> (4)` | survived |
| `865f40cef0` | `spectre/astro/tactical.py:2270` | compare | `abs(half_orbits - whole) > _HOP_CADENCE_TOL -> (abs(half_orbits - whole) >= _HOP_CADENCE_TOL)` | survived |
| `7264dfe761` | `spectre/astro/tactical.py:2278` | binop | `n_hops * dv_per_hop -> (n_hops / dv_per_hop)` | survived |
| `bc4b17b622` | `spectre/astro/tactical.py:2283` | binop | `n_hops * hop_distance_km -> (n_hops / hop_distance_km)` | survived |
| `61cfbf911f` | `spectre/astro/tactical.py:2313` | number | `3 -> (4)` | survived |
| `0c00273c7b` | `spectre/astro/tactical.py:2353` | compare | `abs(half_orbits - round(half_orbits)) > _HOP_CADENCE_TOL -> (abs(half_orbits - round(half_orbits)) >= _HOP_CADENCE_TOL)` | survived |
| `b75a988d92` | `spectre/astro/tactical.py:2361` | binop | `n_hops * dv_per_hop -> (n_hops / dv_per_hop)` | survived |
| `d9dd34bd41` | `spectre/astro/tle_filter.py:75` | return | `return max(t.epoch for t in self.tles) -> return None` | no_tests |
| `43c2c8ce8d` | `spectre/astro/tle_filter.py:125` | compare | `span >= min_spacing -> (span > min_spacing)` | survived |
| `6027d894ef` | `spectre/astro/tle_filter.py:147` | unary | `-t.epoch.timestamp() -> (t.epoch.timestamp())` | survived |
| `4efc75591e` | `spectre/astro/tle_filter.py:176` | compare | `gap_h > stale_h -> (gap_h >= stale_h)` | survived |
| `882edcea88` | `spectre/astro/tle_filter.py:187` | number | `1e-12 -> (1.5e-12)` | survived |
| `818051728f` | `spectre/astro/tle_filter.py:187` | compare | `abs(prev.bstar) > 1e-12 -> (abs(prev.bstar) >= 1e-12)` | survived |
| `fde4a3760b` | `spectre/astro/tle_filter.py:189` | compare | `ratio > TLE_FILTER["bstar_discontinuity_frac"] -> (ratio >= TLE_FILTER['bstar_discontinuity_frac'])` | survived |
| `66c535e9b3` | `spectre/astro/tle_filter.py:231` | number | `2 -> (3)` | survived |
| `a253edbef3` | `spectre/astro/tle_filter.py:236` | call | `reps.sort(key=lambda r: r.epoch) -> pass` | survived |
| `aac4161bc4` | `spectre/astro/tle_filter.py:243` | compare | `len(c.tles) >= large -> (len(c.tles) > large)` | survived |
| `9a06c569d3` | `spectre/astro/tle_filter.py:255` | call | `flags.sort(key=lambda f: f.epoch, reverse=True) -> pass` | survived |
| `297647e78f` | `spectre/astro/tle_preprocessing.py:76` | bool | `False -> (True)` | survived |
| `a13e6b3d6c` | `spectre/astro/tle_preprocessing.py:77` | bool | `False -> (True)` | survived |
| `2dbaa4a56e` | `spectre/astro/tle_preprocessing.py:98` | number | `0 -> (1)` | survived |
| `7a9b94c53e` | `spectre/astro/tle_preprocessing.py:99` | number | `0 -> (1)` | survived |
| `c67ad77ac3` | `spectre/astro/tle_preprocessing.py:100` | number | `0 -> (1)` | survived |
| `d863137f25` | `spectre/astro/tle_preprocessing.py:101` | number | `0 -> (1)` | survived |
| `ae6c28b2cd` | `spectre/astro/tle_preprocessing.py:102` | number | `0 -> (1)` | survived |
| `2ad4ce3700` | `spectre/astro/tle_preprocessing.py:103` | number | `0 -> (1)` | survived |
| `698bcfde97` | `spectre/astro/tle_preprocessing.py:160` | return | `return {}, ClusteringSummary() -> return None` | no_tests |
| `5decf4d0f5` | `spectre/astro/tle_preprocessing.py:170` | number | `0 -> (1)` | survived |
| `3ba8ef86f0` | `spectre/astro/tle_preprocessing.py:182` | augassign | `objects_multi_cluster += outcome.multi -> objects_multi_cluster -= outcome.multi` | survived |
| `6db229d93e` | `spectre/astro/tle_preprocessing.py:193` | number | `0.0 -> (1.0)` | survived |
| `d0eb23a53a` | `spectre/astro/tle_preprocessing.py:193` | number | `0 -> (1)` | survived |
| `ca5c50fe13` | `spectre/astro/tle_preprocessing.py:230` | number | `0 -> (1)` | survived |
| `58b17ffaa0` | `spectre/astro/tle_preprocessing.py:231` | bool | `False -> (True)` | survived |
| `596d4db941` | `spectre/astro/tle_preprocessing.py:232` | bool | `False -> (True)` | survived |
| `76b3027c41` | `spectre/astro/tle_preprocessing.py:247` | number | `0 -> (1)` | survived |
| `819eee12f5` | `spectre/astro/tle_preprocessing.py:247` | number | `1 -> (2)` | survived |
| `925b797674` | `spectre/astro/tle_preprocessing.py:248` | number | `0.0 -> (1.0)` | survived |
| `49c70993f1` | `spectre/astro/tle_preprocessing.py:248` | number | `0 -> (1)` | survived |
| `5b8ba40fa5` | `spectre/astro/tle_preprocessing.py:267` | number | `0 -> (1)` | survived |
| `f1fb720556` | `spectre/astro/tle_preprocessing.py:268` | bool | `True -> (False)` | survived |
| `959b4b2ac7` | `spectre/astro/tle_preprocessing.py:268` | number | `0 -> (1)` | survived |
| `15249feb63` | `spectre/astro/tle_preprocessing.py:268` | bool | `True -> (False)` | survived |
| `474b0984c7` | `spectre/astro/tle_preprocessing.py:268` | number | `0.0 -> (1.0)` | survived |
| `e2a27c1cfb` | `spectre/astro/tle_preprocessing.py:296` | compare | `len(reps) > 1 -> (len(reps) >= 1)` | survived |
| `8165fa0e25` | `spectre/astro/tle_preprocessing.py:304` | binop | `1.0 / len(tle_list) -> (1.0 * len(tle_list))` | survived |
| `b6b409aca3` | `spectre/astro/tle_preprocessing.py:304` | binop | `100.0 * (1.0 - 1.0 / len(tle_list)) -> (100.0 / (1.0 - 1.0 / len(tle_list)))` | survived |
| `9b55577fe3` | `spectre/astro/tle_preprocessing.py:304` | number | `1.0 -> (1.5)` | survived |
| `7bde34819c` | `spectre/astro/tle_preprocessing.py:304` | number | `100.0 -> (150.0)` | survived |
| `38daf2d4e3` | `spectre/astro/tle_preprocessing.py:304` | binop | `1.0 - 1.0 / len(tle_list) -> (1.0 + 1.0 / len(tle_list))` | survived |
| `c681d82b88` | `spectre/astro/tle_preprocessing.py:304` | number | `1.0 -> (1.5)` | survived |
| `483291a3af` | `spectre/astro/tle_preprocessing.py:315` | bool | `False -> (True)` | survived |
| `dcf89855b1` | `spectre/astro/tle_preprocessing.py:335` | return | `return _Outcome( ObjectClusteringSummary( satno=satno, tles_in=len(tle -> return None` | no_tests |
| `b5dad9ff43` | `spectre/astro/tle_preprocessing.py:338` | number | `0 -> (1)` | no_tests |
| `be8ead1320` | `spectre/astro/tle_preprocessing.py:339` | number | `0.0 -> (1.0)` | no_tests |
| `64fc639d31` | `spectre/astro/tle_preprocessing.py:339` | bool | `True -> (False)` | no_tests |
| `78a698cb85` | `spectre/astro/tle_preprocessing.py:341` | bool | `True -> (False)` | no_tests |
| `6f73388497` | `spectre/astro/tle_preprocessing.py:341` | bool | `True -> (False)` | no_tests |
| `ec9fdef31e` | `spectre/astro/tle_preprocessing.py:347` | number | `1.0 -> (1.5)` | survived |
| `0fc35b044a` | `spectre/astro/tle_preprocessing.py:347` | binop | `1.0 / len(tle_list) -> (1.0 * len(tle_list))` | survived |
| `d778a21f73` | `spectre/astro/tle_preprocessing.py:347` | binop | `100.0 * (1.0 - 1.0 / len(tle_list)) -> (100.0 / (1.0 - 1.0 / len(tle_list)))` | survived |
| `8123624053` | `spectre/astro/tle_preprocessing.py:347` | number | `1.0 -> (1.5)` | survived |
| `e6299676dc` | `spectre/astro/tle_preprocessing.py:347` | number | `100.0 -> (150.0)` | survived |
| `09e10b674a` | `spectre/astro/tle_preprocessing.py:347` | binop | `1.0 - 1.0 / len(tle_list) -> (1.0 + 1.0 / len(tle_list))` | survived |
| `7ffc8c867b` | `spectre/astro/tle_preprocessing.py:356` | number | `1 -> (2)` | survived |
| `cb23a84fc3` | `spectre/astro/tle_preprocessing.py:358` | bool | `False -> (True)` | survived |
| `65f4496441` | `spectre/astro/tle_preprocessing.py:360` | bool | `True -> (False)` | survived |
| `a6eca1b759` | `spectre/astro/transfers.py:23` | number | `0.0 -> (1.0)` | survived |
