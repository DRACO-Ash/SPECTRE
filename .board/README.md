# SPECTRE backlog

The working backlog for SPECTRE, planned by the Backlog Brain pack in `.claude/skills/backlog-brain` (standard library Python, no
install). Seeded on 2026-10-28 from the planning trail, with every item checked against the code at `77a1088` (release 0.6.4).

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

## Where the seed came from

| Source | What was still open |
|---|---|
| `docs/BUILD-STATE-AND-ROADMAP.md` | Phase 1 item 3 (intent from behaviour), Phase 2 (manoeuvre trigger), Phase 3 |
| Coverage run, 2026-10-28 | 92.05% total against a ratchet of 74; lowest are `routes/pol.py` 59.9%, `routes/udl.py` 66.5%, `routes/threat.py` 85.0%. The roadmap's 74.3% and its module table are stale |
| `docs/RED-TEAM-THREAT-SWEEP.md` | findings 3 and 6 (phase angle, delta-V band); findings 1, 2, 4 and 5 shipped in 0.5.14 |
| `RETROSPECTIVE.md` | case-sensitive usernames, no self-service password change |
| `docs/TODO list.txt` | P1-B, P2-A, P2-B, P2-D, P3-A, P3-C, SEC-05 |
| `audit/GAPS.md` | the human decisions, PostgreSQL path, mutation run, unproven candidates, load test |
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
