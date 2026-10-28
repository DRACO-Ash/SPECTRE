# SPECTRE backlog

The working backlog for SPECTRE, planned by the Backlog Brain pack in `.claude/skills/backlog-brain` (standard library Python, no
install). Seeded on 2026-10-28 from the planning trail, with every item checked against the code at `77a1088` (release 0.6.4).

## The operator's question: the acceptance test for every release

Confirmed by an operator on 2026-10-28 as precisely what they want a tool to help with:

> **Something moved. Can it reach one of mine, how long have I got, does it mean anything, and what do I need to decide, by when?**

The case that showed it: an overnight notification says an adversary satellite burned. At handover the operator sees "that burn
cut your warning on asset X from 14 hours to 3, it is unlike its last 200 days, and you need to decide by 0900Z", not "this object
could reach that one for 190 m/s".

The 4 outputs, in the operator's order:

| Rank | Output | What the operator reads | Items |
|---|---|---|---|
| 1 | Is this normal | This burn is routine for this object, or unlike anything in its history | SPC-001, SPC-009, SPC-003 |
| 2 | Warning-time change | The burn moved my warning from this to that, and these assets are now in reach | SPC-002, SPC-006, SPC-007 |
| 2 | Decide-by time | The latest time I can act, from the fastest credible arrival minus my response latency | SPC-008 |
| 4 | Recommended response | What to do, and what each option costs | SPC-100 to SPC-152 |

**Custody**, in the operator's words: having timely and actionable information to determine outputs 1 and 2. When it is lost, the
screen says so and why, and never shows a confident answer it lacks the information for (SPC-018).

Every release is checked against this before it ships:
1. Its changelog names which of the 4 outputs it advances, or why it advances none.
2. Each output it touches answers in the operator's words, as in the table, with its basis on screen (computed, sampled or lookup).
3. Where custody is not held, the output says so rather than guessing.
4. Higher-ranked outputs come first: nothing for output 4 displaces open work for outputs 1 to 3 without the owner's say.

## Files

● `config.json`: the settings record. Release budget, gates, people, agents and the files that carry extra risk.
● `items.json`: the backlog. One entry per job, refs `SPC-NNN`.
● `PLAN.md`: the last plan printed from the two, for reading without running anything.

## Commands

Run from the repository root.

```
python3 .claude/skills/backlog-brain/scripts/brain.py plan --config .board/config.json --items .board/items.json
python3 .claude/skills/backlog-brain/scripts/brain.py dupes --items .board/items.json
python3 .claude/skills/backlog-brain/scripts/brain.py evidence --items .board/items.json --repo .
python3 .claude/skills/backlog-brain/scripts/brain.py selfcheck
```

After changing `items.json`, re-plan and refresh `PLAN.md`:

```
python3 .claude/skills/backlog-brain/scripts/brain.py plan --config .board/config.json --items .board/items.json > .board/PLAN.md
```

## How to work an item

1. Take the first open item in the lowest release, or the next one in its lane.
2. Reproduce first: a failing test before the fix, as `audit/REMEDIATION-LOG.md` does.
3. Ship it in a SPECTRE release with its `CHANGELOG.md` and `docs/CHANGE-LEDGER.md` entries.
4. Mark it done in `items.json` with `"state": "done"`, `"est"` (its minutes) and `"actual"` (the minutes it took). Pace is
   measured from those rows; until there are some, every forecast reads from settings and says so.

## Owner rulings

| Date | Question | Ruling |
|---|---|---|
| 2026-10-24 | NOTSO cache marking, repository and image | Acceptable to hold, a public repository included (`audit/REMEDIATION-LOG.md`) |
| 2026-10-24 | UDL- and HRR-sourced object names | Treated as untrusted; fix shipped (F-038) |
| 2026-10-28 | NOTSO cache in the repository, its history and the image | Confirmed: it stays |
| 2026-10-28 | UDL and HRR name threat model | Confirmed: accepted as is |
| 2026-10-28 | Self-service password change | Covered by the platform's single sign-on; nothing to build |
| 2026-10-28 | Decision Engine | Invest in every phase: SPC-100 to SPC-152 |
| 2026-10-28 | Analyst session before the Phase 3 capabilities | Deferred; SPC-080 stays open |
| 2026-10-28 | The operator's question, output ranking and custody definition | Confirmed with an operator; see the acceptance test above |

## Decision Engine plan

23 items, 5820 priced minutes, in dependency order, after outputs 1 to 3 (the operator ranks it 4th). The phase numbers are the ones in `docs/decision_engine_phases.md`.

| Stage | Items | What it delivers |
|---|---|---|
| Foundation | SPC-100, 101, 102 | Scenarios bound to real element sets; a basis on every figure; reference cases every phase must pass |
| Phase 2, Monte Carlo | SPC-110 to 115 | Sampled closest approach against the blue trajectory, scored on P5, with bands in the matrix |
| Phase 3, physics | SPC-120, 121, 123 to 125 | SGP4 closest approach and TCA, computed friendly burns, custody from the operator's definition, lookup constants retired |
| Phase 5, NOTSO priors | SPC-130 to 132 | Adversary probabilities seeded from NOTSO history, with an interval and a sensitivity check |
| Phase 4, multi-turn | SPC-140 to 142 | Two and three turn trees, selectors over the tree, a server-rendered tree view |
| Joins and upkeep | SPC-150, 151, 152 | Open a scenario from the sweep; cited default weights; the guide kept current |

Three corrections to the April spec are built into the plan:
● Phase 2 needs the blue element set. `MonteCarloResult` holds element statistics at the horizon, not trajectories, so closest
  approach needs a separation series (SPC-110).
● Score on P5 separation, not P95. For a miss distance, P95 is the optimistic tail (SPC-112).
● No D3. The tree view is server-rendered, so no new third-party library to track and scan (SPC-142).

Phase 4 waits on computed responses and custody, because turn 2 starts from the states turn 1 leaves.

## A limit of the planner

An item that depends on a tooling or research item is never placed: the planner keeps those tracks apart and never marks them
ready. Keep a dependency's target on the release track, as SPC-102 is.

## Where the seed came from

| Source | What was still open |
|---|---|
| `docs/BUILD-STATE-AND-ROADMAP.md` | Phase 1 item 3 (intent from behaviour), Phase 2 (manoeuvre trigger), Phase 3 |
| Coverage run, 2026-10-28 | 92.05% total against a ratchet of 74; lowest are `routes/pol.py` 59.9%, `routes/udl.py` 66.5%, `routes/threat.py` 85.0%. The roadmap's 74.3% and its module table are stale |
| `docs/RED-TEAM-THREAT-SWEEP.md` | findings 3 and 6 (phase angle, delta-V band); findings 1, 2, 4 and 5 shipped in 0.5.14 |
| `RETROSPECTIVE.md` | case-sensitive usernames |
| `docs/TODO list.txt` | P1-B, P2-B, P2-D, SEC-05; the Decision Engine phases are planned above |
| `audit/GAPS.md` | PostgreSQL path, mutation run, unproven candidates, load test |
| `docs/CODE-QUALITY-GATE.md` | `fetch_tle` at complexity 67 and the next two worst |

Left out because the code shows them done: the audit's 296 findings (closed in `audit/REMEDIATION-LOG.md`), session state eviction
(`spectre/web/planning_state.py`, 8 hours), the HRR bootstrap list (`spectre/data/hrr_default.json`), SBOM in CI, the lockfile,
CodeQL, the cookie and CSRF items, and the five orbital findings the roadmap lists (inference: closed by the audit's
constants and frame work, F-093, F-055, F-194 and F-203; re-verify if one resurfaces). The `IMPROVEMENT-PLAN.md` items that target the
Foundations baseline are not here; they belong in that repository.

## What is not measured yet (TBC, re-verify)

● Every gate's minutes are 0. Set them from CI run times. The full local suite ran green on 2026-10-28 (Python 3.13, SQLite, 12 skips).
● The release budget (12 to 14 hours) is the pack's default, not a SPECTRE figure.
● The App Store submission overhead is 0 until measured.
● Ash's hours a week is a placeholder.
● Item minutes are estimates at agent pace, not measurements.
