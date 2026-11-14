# Threat verdict reference: sign-off for the verdict switch (SPC-175)

This is the sheet the owner signs before the verdict switch is turned on (Threat Understanding concept, section 9, decisions 2 and 3). It is generated from `tests/reference/threat_verdict_reference.csv`, and `tests/unit/test_threat_verdict_reference.py` fails if either file drifts from what the code computes, so what is signed here is what the switch does.

## What the switch changes

● Off, which is how every shipped configuration leaves it, the sweep and the screen show the current rule's verdict: the lower of geometric access and assessed capability, or access alone when nothing is known about capability. The Threat range and Understanding are shown beside it.
● On (`SPECTRE_THREAT_VERDICT_SWITCH=true` in the deployment's environment), they show the verdict of concept section 4.8: the Threat ceiling whenever Understanding is LOW or the Threat range spans four or more bands, and otherwise the current rule's verdict moved into the range.
● On the sweep, the switch changes only the verdict shown. The Threat range, Understanding, decide-by, the Decision Engine's picture, the ledger and its hash are the same either way.
● On the asset screen, it also ranks its actors by the verdict shown, so the actor named most dangerous can change. The notice of an actor whose verdict its own Threat range does not bear out no longer appears, because the verdict shown always sits inside that range.
● Each switched verdict carries its reason in one line, under the badge and in the verdict's cell, with what the current rule reads.

## The case

Each of the 20 bundled red objects against a deliverable 9 m/s GEO intercept (access CRITICAL), with custody held and no element-set history held, on its bundled element set. It is the case the pinned legacy verdicts in `tests/unit/test_threat_understanding_sweep.py` use. Every bundled element set is SYNTHETIC, so this is a demonstration case: on live data with histories held, Understanding rises and fewer verdicts read the ceiling.

## What it shows

11 of 20 verdicts change. Understanding LOW for all 20. The largest move is MINIMAL to CRITICAL, for Kowsar and Kowsar-1.5.

| Object | Name | Old verdict | New verdict | Understanding | Reason |
|:-|:-|:-|:-|:-|:-|
| 41838 | SJ-17 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 49330 | SJ-21 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 62485 | SJ-25 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 43874 | TJS-3 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 58204 | TJS-10 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 50321 | SY-12 01 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 50322 | SY-12 02 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 40892 | TJS-1 | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 41911 | TJS-2 | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 63157 | TJS-15 | MEDIUM | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat MEDIUM. |
| 40258 | Luch / Olymp-K | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 55841 | Luch / Olymp-2 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 62188 | TJS-13 | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 64467 | Cosmos 2589 | CRITICAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat CRITICAL. |
| 65563 | Yaogan-45 | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 65590 | Cosmos 2595 | MEDIUM | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat MEDIUM. |
| 61769 | Kowsar | MINIMAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat MINIMAL. |
| 61768 | Kowsar-1.5 | MINIMAL | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat MINIMAL. |
| 53370 | Khayyam | HIGH | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat HIGH. |
| 59065 | Pars-1 | MEDIUM | CRITICAL | LOW | Understanding LOW. Threat reads its ceiling, set by access at CRITICAL. The current rule reads Threat MEDIUM. |

## Decision

Concept section 9, decision 3: the verdict reads the Threat ceiling under Understanding LOW. Turning the switch on is a deployment setting, not a code change, and nothing in the image sets it.

● Agreed, the switch may be turned on: yes or no
● Owner:
● Date:
● Conditions or comments:
