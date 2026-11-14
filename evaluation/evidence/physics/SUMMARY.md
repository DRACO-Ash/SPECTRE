# Physics probes P-11 to P-14: summary

Written by a delegated assessor (astrodynamics), bounded to `evaluation/probes/test_p11_*.py` to `test_p14_*.py` and this folder; saved here by the lead assessor, who re-checked the claims marked † against the raw evidence. The engine and its tests are byte-identical to `ddba577` (`git diff --stat ddba577 HEAD -- spectre tests` prints nothing).

**Run:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -p no:cacheprovider -o addopts="" -q -rA evaluation/probes/test_p1[1-4]_*.py`: 8 passed, 8 failed, 471.8 s (`probes-physics.log`). A failure records that an expected property does not hold; none is a crash.

**Deviations:** P-11 windows 1 h and 6 h (not 72 h) to bound runtime; case C 6 seeds. P-12 wrapper bound set to the 1 µs datetime quantisation after the first run measured 1.004e-8 km/s, with the residual shown to be wholly that quantisation. P-13 separation-error section added; the original assertion kept, so it still fails. P-14 used two runtime fault injections limited to the test (a NaN lookup via monkeypatch; a fake HTTP client for the UDL path, no network).

| Probe | Expected | Observed | Result |
|:-|:-|:-|:-|
| P-11 P5 stability (recast; no Pc exists) | P5 spread falls as 1/sqrt(N); engine half-width covers the spread | No Pc computed anywhere. Case A (plane-change Evasive, 20 seeds): P5 SD 0.170, 0.119, 0.078, 0.063 km at N 50, 100, 200, 400, log-log slope −0.49; 79 of 80 runs within their own half-width. Case B: slope −0.41, 77 of 80 covered, converged in 15 of 20 seeds at N 50. Case C: half-width 18 to 45 times 1.96 SD; converged in 1 of 6 seeds at N 50. The half-width printed as P5's is the widest of P5, P50 and P95 † (`monte_carlo.py:1170-1179`; `decision.py:2169-2170`) | Pass |
| P-12 SGP4 against published vectors | Wrapper matches `tcppver.out` | 33 cases (24 SDP4), 666 vectors: `Satrec` within 1.6e-7 km; SPECTRE's wrapper within 9.8e-6 km and 1.0e-8 km/s, the residual being 1 µs datetime resolution; all 7 error cases raise at the library's instant. Gravity model WGS-72; the RK45 started from SGP4 states uses WGS-84 constants (`constants.py:12-18`) | Pass |
| P-13 production RK45 | Error at 72 h under 0.1 km | Against DOP853 at rtol 1e-12: LEO 0.285 km at 48 h, 0.652 km at 72 h (truncation; same with drag off); GEO 0.004 and 0.015 km; separation error at 72 h 0.001 to 0.353 km. The code's own element-set model at those ages: 5 to 7 km LEO, 4 to 5 km GEO. RK45 against SDP4 at GEO parts by 11 to 18 km (no third bodies in RK45) | Fail |
| P-14 stale set, 30 days | Flagged | Refused to lookups with sentences; "Modelled estimate" banner | Pass |
| P-14 deep space (SDP4) | Flagged | GEO pair: computed 89.3 km, no regime statement. Molniya-class red: 18,031.6 km, given the 24 h LEO staleness limit and LEO error model | Fail (silent) |
| P-14 decayed object | Flagged | Decay inside the window: refused. Decay between perigee passes (horizon 1 h starting 70 min after epoch, red altitude 5 to 320 km): "Computed: 643.1 km … ± under 1 s" in 12 cells, no flag † | Fail (1 of 3 silent) |
| P-14 NaN and missing values | Fails loudly | NaN in any of 8 inputs: ValueError. All five weights 0: accepted, every score 0, pick by row order, no flag. Injected NaN lookup: "nan" in cells, pick by row order, no explanation. Missing row values default silently | Mixed |
| P-14 contradictory observation | Flagged | Flagged with a sentence under both rules | Pass |
| P-14 extreme priors | Flagged where unusable | Every P at 0 under expected value: pick by row order, no guidance, nothing on the page | Fail |
| P-14 UDL checksum (G9) | Refused before binding | Not checked anywhere on the UDL path †; a one-digit corruption (inclination 97.4° to 98.4°, old checksum) reached `BoundElset` and moved the computed miss from 10.4 km to 13.4 km † with no flag; the background refresh replaced a good held set with it; an inclination of 597.4° is accepted | Fail |

Not probed: a 72 h P-11 run at N 400 (cost); force-model truth (no third-body propagator installed); a future-dated element set reading as age 0 (`elsets.py:97`).

Working tree after the run: only `evaluation/` paths changed.
