# The hourly board sync: a template

The stored prompt for a project's hourly sync Routine, with this project's details as placeholders. Copy it, replace every
`<PLACEHOLDER>`, and store the result as the Routine's prompt and as a file in the repository, changing both in the same
sitting whenever one changes. The Backlog Brain pack's own working copy, with Vendor Fishing's values, is that project's
`.claude/board/SYNC-PROCEDURE.md`.

| Placeholder | What it is |
|---|---|
| `<BOARD_URL>` | the board's claude.ai link, also kept as `board.url` in the settings record |
| `<SETTINGS>` | the settings record, normally `.board/config.json` |
| `<DELIVERY_BRANCH>` | the branch the work is delivered on, whose record the pipeline is read from |
| `<RECORD_PATH>` | the markdown file whose state block the guard rewrites, such as `docs/BACKLOG.md` |
| `<RECORD_BRANCH>` | the branch that file is pushed to |
| `<FEED_COMMAND>` | the command that reads the delivery record into gate statuses; each project writes its own |
| `<IDLE_CHECKS>` | quiet checks before the sync pauses: the record's `board.sync.idle_checks`, 3 when unset |

## The steps
0. Read the clock (`date -u`) first and use it for every stamp. Never write a time from memory or ahead of the clock.
1. `git fetch`, then read `<DELIVERY_BRANCH>` in a worktree that is not checked out anywhere else.
2. Fresh dumps only: list items, plan, gates, releases, accuracy, threads, links and intake from `<BOARD_URL>` with `out_dir`
   into a NEW folder, and get `board/meta` into the same folder. Never reuse an older dump, and take every `if_version` from
   the read just made.
3. Run `<FEED_COMMAND>` against the worktree and the gates dump. Copy a "running" reading into a gate only when a round has
   actually started.
4. If the delivery record is on an earlier release than `board/meta.currentRelease`, write nothing to gates; stamp
   `pipelineSyncedAt`, `pipelineSyncedFrom`, `updatedAt` and a `pipelineNote`. If it is on a later release, stop and ask the
   owner: that is a plan change.
5. Otherwise update every gate whose status, rounds or note differ, in one batch, pinned with `if_version`. Never touch
   `gates/upload` once it carries `markedAt`: that is the owner's mark.
6. Record each finished item's priced and actual minutes in `accuracy` (kind `item`), a release's freeze-to-package time as
   kind `release`, a refusal's refusal-to-package time as `recut`, and anything else as `rollup`. Take times only from the
   delivery record.
7. Triage every intake entry that is `submitted` or `investigating` and close it in the same run, logged with a ref or
   rejected with the reason. Never write a release name into an outcome.
8. Report each planned release's forecast. The cap is advisory unless the owner says otherwise: never trim or move a release
   because of it, and never move an item to another release without asking the owner first.
9. Run `python3 .claude/skills/backlog-brain/scripts/brain.py check --dump <dump> --config <SETTINGS> --state-block
   <RECORD_PATH>`. Fix every FAIL, re-dump after any write and run it again until it exits 0. Push `<RECORD_PATH>` to
   `<RECORD_BRANCH>` only when its state block changed. Every board write batch ends by setting `board/meta.updatedAt`.
10. If a stage changed status, reply to the owner with the one-row pipeline table only.
11. On the owner's green Upload mark, do not roll items forward: tell delivery, and ask the owner before the next release
    becomes current or any leftover item changes release. Build pokes with `brain.py relay`.
12. Idle pause, only when `board/meta.pauseEnabled` is true: run `python3 .claude/skills/backlog-brain/scripts/brain.py idle
    --dump <dump> --sha <delivery head> --meta <dump>/board/meta.json --threshold <IDLE_CHECKS>`. Exit 2 means the read was incomplete: do not pause. A
    run that wrote more than the meta stamp re-dumps and runs it again with `--store`. Write `idleChecks`, `syncFingerprint`
    and, when pausing, `syncPaused` and `pausedAt` in the last meta batch, and disable the Routine. The idle check refuses a
    board with no items, so a new board never pauses until it holds work.
