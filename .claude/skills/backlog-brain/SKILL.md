---
name: backlog-brain
description: A dynamically optimised backlog for any project. Composes releases and a build order from priority, cost, dependencies and locks, groups work by the gates it triggers and the files it touches, and forecasts time as a range from measured pace, for people and agents. Use when the owner wants a backlog planned, re-planned, chunked, sized to a release budget, or checked for stale entries, in any repository.
---

# Backlog Brain

Standard library Python only, so it drops into a project of any language: copy this folder into the project's
`.claude/skills/`. Status, read against the board on 2026-10-07: built and tested are the settings model, the optimiser, the
resource and time model, the event log, the guard and its checks, the relay helper, the thread brief builder and the installer, and this
project's own guard runs on the pack. Since VH-584 the board page ships in this folder too, read from a settings document (see "The
board page"). The pilot on a second project was dropped by the owner, so the evidence the pack works is this project's live board and
the tests below, not a second project.

## The ethos (owner, 2026-10-07)
**Best speed and efficiency, balanced with quality and release standards: zero waste, zero duplication.** It governs
every plan and every thread this pack starts, and every thread brief carries it (`brain/threads.py`, "HOW YOU WORK").
- **No check runs twice on the same tree.** A later stage reads the earlier stage's stamp and re-runs only when an input changed.
- **No idle waits.** A thread that must wait books a short check-in and runs the next independent step.
- **Parallel by default.** Work is split across threads wherever the files do not collide; the plan's lanes exist for this.
- **A frozen release takes nothing new.** New rulings and findings below a blocking grade go to the next release.
- **The backlog stays tidy.** An answered decision is deleted once its answer is recorded; the Removed tab is never left to accumulate.
- **The standards are never lowered** to buy speed: measured or marked, red before green, and the binding gates stand.

## What it does
1. **Plans releases.** `python3 scripts/brain.py plan --config .board/config.json --items items.json` composes
   releases to the project's floor and cap. A person's lock is never moved; a dependency never lands before what
   it needs; waiting items (needs an owner answer) and research take no release capacity; tooling is planned apart.
2. **Groups by gate and by file.** Items that trigger the same gates share the cost of those gates, so a
   lower-priority item rides a release that already pays for its gate and never pays for a new one while a more
   urgent item waits. An item with no files and no gates triggers every gate: an unclassified change is never
   treated as a cheap one.
3. **Assigns lanes.** Items that touch the same file share a lane; lanes are packed onto the agent limit.
4. **Forecasts as a range.** From finished items (`est`, `actual`, `who`, `kind`) it measures pace per person and
   kind, falls back person and kind, kind, person, everything, then the settings, and says which it used. The
   headline is sequential (how releases are sized); the parallel figure shows what agents buy.
5. **Warns when people are the limit.** Declared owner time (`human_minutes`) is checked against the hours the
   people can give in the window.
6. **Explains itself.** Every placement carries a reason.

## Item fields
`ref`, `minutes` (priced), `priority` (high, med, low), `order` (the person's own sequence, first among equals),
`group` (a theme, preferred inside a release), `deps`, `files` or `gates`, `lock` (a release name), `needs_owner`,
`kind` (`research` takes no release capacity), `track` (`tooling` ships no store artefact), `who`, `human_minutes`.
On the board the same idea is a release, not an item: a plan entry with `kind: "tooling"` carries no store steps or refusal allowance.

## How to use me
Two guides, one source file: `assets/how-to-use.json`.
- The board page has a **How to use me** button beside Decisions for action. It opens a short list of jobs (add
  something, answer a decision, move work, read the times, keep the threads straight, record the store's answer, what to
  do when something looks wrong), each with numbered steps.
- `python3 scripts/brain.py guide` prints the pack's own guide for someone setting it up in a project;
  `--for board` prints the board guide as text.
To change the wording, edit the JSON, then refresh the page's copy with `brain.page_patch.embed(html)` and republish
the page. The board guide carries tokens filled from the board's settings: `{floor}` and `{cap}` (hours), `{ref}`, `{source}` and
`{overhead}`; a job marked `"when": "store"` is left out when the board has no store. `brain.py guide --for board --config FILE`
prints it as a given project's board would. `tests/test_guide.py` fails if the wording breaks the house rules (no long dashes, no plus signs, numbers of
5 and over as digits, no AI cliches, short sentences, 2 to 5 steps a job), if the guide names a button the page does not
have, or if the page's copy is out of date. When a button is renamed on the page, rename it in the JSON in the same change.

## Waking Backlog
Every thread brief (Development, Documentation, Research, Other) tells the thread to wake the Backlog thread whenever it
finishes something, starts something, is blocked, or passes a task back: a Routine with no schedule, bound to the
Backlog session, fired once, then deleted. That is how a paused hourly sync restarts on development activity, because
nothing delivers a branch push to a session. `brain.threads.backlog_session(threads)` reads the session from the
Backlog thread's link.

## Starting a thread from the board
The board's Threads panel has "Start this thread in Claude Code". Ticking it saves the thread with no link and
tells the Backlog thread (a comment that begins START THREAD). The Backlog thread then:
1. reads the `threads` and `links` collections, builds the request with `brain.threads.session_request(...)`,
   passing the BASE BRANCH of the project's trunk (never the default branch: see below);
2. starts the session with the session tool and takes the link from `brain.threads.thread_link(result)`;
3. writes `url`, `status` and `sessionId` onto the thread, and replies on the comment thread.
Measured on 2026-10-01 with Development 2: the session came up RUNNING in 26 seconds, read the repository, and
stopped to ask for a base branch and a lane, as briefed. One test thread cost 0.51 US dollars. Two traps found:
the platform does not create or switch the requested branch (the session started on `main`), and `main` was 479
commits behind the delivery branch, so a brief that does not name the base and say how to branch starts a thread
on stale code. A thread is given no lane until a person assigns one.

## Approvals, screenshots included (owner, 2026-10-05)
The board shows every item whose state is `input` and which has a `decision` in a panel at the top, "Waiting for your
approval". Each option is one large button: one press writes the answer, and Claude is told 10 seconds later unless
Undo is pressed. A screenshot approval is the same item with `decision.images`, each `{id, alt, caption}`, where `id`
is a 32 character asset id. To raise one:
1. Upload each screenshot: Artifact tool, `action: "publish"`, `url` the board, `asset: true`, `file_paths`. Keep the ids.
2. `python3 scripts/brain.py approval --question ... --context ... --image ID:alt:caption --option "Label|detail|rec"`
   prints the JSON (`brain/approvals.py`; this project's `.claude/board/raise_approval.py` is the same command); apply it with ArtifactData `update` on `items/<ref>` (give the item's current `version`).
3. The answer arrives as `state: "answered"` with `decisionAnswer`, and as a comment to the owning session starting
   `APPROVAL ANSWERED` or `DECISION ANSWERED`. A "Changes needed" answer carries the owner's note.
The page builds `/_blob/<id>` only from a 32 character lowercase hex id; anything else is dropped. The panel is
`brain/approvals_patch.py` (`apply()`), proved by `tests/test_approvals.py` and, in this project, `.claude/board/page/render_approvals.cjs`
(renders the panel, presses the buttons, checks undo and the told-after-10-seconds rule).

## Standing approval for thread-to-thread interactions (owner, 2026-10-05)
The owner pre-approved every interaction between the project's threads that the work needs, so none of them goes to the
owner as a popup. Covered: a poke (a Routine with no schedule, bound to the target thread's session, fired once, then
deleted), the wake or pause of the hourly sync, a board write that hands work over (an item, an intake entry, a thread
note, a raised approval), a screenshot upload for an approval, and a push to a `claude/` branch the thread owns.
Before a poke, `python3 scripts/brain.py relay --threads <dump>/threads --from <thread> --to <thread>` prints the
target session id (this project's `.claude/board/relay_check.py` is the same command), or exits 2 when the target is not a registered thread, has no valid session id, is the sender, or the
action is not a poke. Exit 2 goes to the owner; it is not retried another way.
Not covered, still the owner's by popup: a design or screenshot approval, the Upload mark, a delete, a merge to `main`,
anything that spends money or changes a customer-facing system, and any change to a thread's relationships. The
authorisation is recorded in the board at `board/standing`. `.claude/settings.json` already lets the trigger tools run
without a prompt; widening it further is a permission change that waits for the owner.

## No item changes release without asking (owner, 2026-10-05)
The owner's words: "dont ship anything to 2.8 unless you bloody well ask me". The optimiser, the hourly sync and the roll-forward
at an Upload mark never move an item into a release other than the one the owner placed it in, and never trim one release into
another, without a popup first. An item left over from a frozen release stays where it is until the owner decides. Recorded at
`board/standing`, field `placementRule`.

## The event log (VH-366-B)
A builder appends one JSON line per fact to `events.jsonl`; the board replays it:
`python3 scripts/brain.py events --log events.jsonl --state state.json` prints what would change, and `--write` applies it.
Each line has an `id`, an `at` (ISO 8601 UTC ending in Z) and a `kind`: `item_state` (`ref`, `state`), `accuracy` (`ref`, `est`,
`actual`), `gate` (`key`, `status`) or `lanes` (`release`, `lanes`, `priced`, `elapsed`, the sample the lane-adjusted forecast reads).
Three rules keep a late or repeated line from moving a forecast: a line with any problem is refused whole and a line that is not
JSON is skipped with its number; an id applied before changes nothing; and an event stamped before the board's last read, not
applied then, is refused as stale. The command exits 1 when anything was skipped, stale or refused. The state file is written
beside itself and renamed over, so a failed write leaves the old file whole. `brain/events.py`, `tests/test_events.py`.

## The relay helper (VH-366-F)
`python3 scripts/brain.py relay --threads <dump>/threads --links <dump>/links --from t-backlog --relation "feeds work to" --message "..."`
prints the poke requests for every thread the sender has that relationship to, so a target is never typed from memory. Each request
is the argument set for the session tool's Routine (no schedule, bound to the target session, fired once, then deleted). A target
that is not a registered thread, has no valid session id, or is the sender is listed under `needs_owner` and nothing is built for
it. The message is stamped from the clock when it is built, never from a time the caller supplies, so a relay cannot carry a time
ahead of the clock. Exit 2 when nothing can be sent without the owner. `brain/relay.py`, `tests/test_relay.py`.

## Robustness (VH-366-E)
- `brain.py check --dump <dir> [--config config.json]` is the freshness guard, generalised: it takes its release names, limits and
  cap from the settings record. It FAILS on a dump older than the limit, a note that places a task where the release field says
  otherwise, a time field that disagrees with the minutes, an umbrella that still carries minutes, a decision nobody can see, a
  closed task in a live release and a board header older than the limit; it only WARNS on a release over its cap, a paused sync and
  a built task still shown in a live release. Exit 0 clean, 1 a fault, 2 unusable input, 3 degraded. `brain/guard.py`.
  The same command reads the other collections of the dump when it holds them (VH-366-H): it FAILS an intake entry that is stale,
  actioned, unresolved or names a release, and a thread structure that breaks the rule (Backlog feeds every development thread, each
  passes back what it cannot solve, one prime thread that is first in order, the others work hand in glove with it, it instructs
  Documentation, which passes tasks to Backlog; the relation words are settings). It prints the release table with the forecast at
  the project's own pace and overhead, the lane-pace lines from the accuracy rows, and an advisory when a release's overhead
  outweighs its build. `--table` prints those; `--state-block FILE` rewrites the marked state block in a markdown file, and only from
  a read that is not stale; `--meta FILE` reads the board header. `.claude/board/parity_check.py` runs this and a project's older
  guard side by side on one dump and on planted faults, which is how a project retires its own copy.
- `brain.py export --dump <dir> --out board.json` writes the whole board as one file with counts and a checksum. Of the `board`
  collection only `meta` and `settings` travel; `board/standing` holds one project's own rules and never does. `check` reads the
  header from the dump's `board/meta` when it holds one, and `--meta` still wins;
  `brain.py import --file board.json --out <empty dir>` refuses the whole file on a wrong schema, count or checksum, and never
  writes into a folder that already holds a collection. `brain/bundle.py`.
- Degrade path: `check --fallback board.json` reads the export when the store cannot be read, prints DEGRADED with the time of the
  export, and exits 3. An old export still fails the freshness rule; with no fallback it exits 2 and reads nothing.
- `brain.py selfcheck` runs on install and on upgrade: the example settings load, a board survives export and import unchanged, and
  the pack's own tests pass. It prints how many tests were skipped and why, because a skipped check proves nothing.

## Install and upgrade (VH-366-G)
`python3 scripts/brain.py install --project <folder> [--name N] [--prefix PRJ-]` reads the project and says what it found: the
language (from package.json, pyproject.toml, go.mod and the like), the source folders, the gates it already runs (a test folder,
a lint config, a Dockerfile) and whether it looks like a container. Without `--write` it only prints the plan. With `--write` it
copies this folder to `<project>/.claude/skills/backlog-brain`, writes the settings record to `<project>/.board/config.json` (never
over an existing one), runs `selfcheck` from the installed copy and prints the exact commands for plan, check, export and relay.
A gate's minutes are left at 0 with a note, because the pack does not know how long this project's gates take until they are
measured. `--upgrade` replaces the pack's code and keeps the settings and data, which live outside the pack folder; if the
self-check then fails, the previous version is put back. A record the pack would refuse is never written. Compiled caches are not
copied. The page arrives with the pack, and the installer prints the steps to publish it (see "The board page"). A Dockerfile's
gate is keyed `container`, because `build` is the page's own node.
`brain/install.py`, `tests/test_install.py`.

## Keeping the backlog accurate (VH-377)
- `brain.py dupes --items <dump folder or file> [--threshold 0.55]` lists open tasks that read like the same job: each task is its
  title (counted three times) and the first 120 characters of its note, every word weighted by how rare it is, compared by cosine.
  A pair in one family (the same parent, or refs on one series such as `VH-366-A` and `VH-366-B`) is a split and is skipped; so is
  a pair where either note already names the other's ref, because that is the recorded relationship this check exists to
  encourage; done and removed tasks are not compared. It exits 1 when it finds candidates and changes nothing.
- `brain.py evidence --items <dump> --repo <tree> [--repo <tree> ...]` lists open tasks whose note cites a file none of the given
  trees has. A path is skipped when the words around it say it is meant to be new (create, add, planned) or already gone
  (retired, removed, does not exist), and when it holds a wildcard or a placeholder. It exits 1 on any and edits nothing.
  Give it every tree a task may live in: a file on a branch not yet merged is missing from the others.
- Measured on 2026-10-06 against 445 tasks (command output, TBC, re-verify when the board changes): `dupes` found one pair at 0.35 and
  above, two follow-ups with the same shape and different jobs, and nothing else; `evidence` found one live stale path outside files
  that exist only on an unmerged branch, a finding that quotes the missing file as its evidence. The owner's concern of 2026-10-03
  was real as a risk; the board does not currently show it.
- A task a decision or a build has overtaken carries `supersededBy`: a ref, or a sentence naming the decision. `brain.py check`
  fails an OPEN task that carries it, and fails a `supersededBy` ref the board does not hold. A pair a person has judged carries
  `distinctFrom` (not the same job) or `relatesTo` (related on purpose) naming the other ref, as one ref, a list or refs separated
  by commas, in any case, on either task; the duplicate scan then skips it, so a pair found once is dismissed once.
- `brain.py check` runs the duplicate scan and the evidence check as well, so the hourly guard runs them, not only their own
  commands. The duplicate threshold is `guard.dupes_threshold` (0.55 by default). Evidence counts a cited path as present when it
  is on disk in the repository that holds the pack, in HEAD, or ADDED by another fetched branch since it left HEAD's history
  (`git diff HEAD...ref`, nothing checked out), so work on an unmerged branch is not called stale and a merged or long-dead branch
  cannot keep a deleted file alive. The branches read are `guard.evidence_refs`, a list of ref prefixes, by default every fetched
  branch (`refs/remotes/origin/`). A branch that cannot be read is named in a WARN, never guessed; when only HEAD could be read,
  every finding is a WARN, because an unfetched branch could hold the file; each FAIL says what was read. `--repo DIR`
  (repeatable) checks folders instead; `guard.evidence: false` turns it off; with no repository and no `--repo` the check says
  EVIDENCE not run rather than passing quietly. `--shared-only` runs only the checks the legacy guard also has, which is how
  `.claude/board/parity_check.py` keeps comparing like with like.
- Measured on 2026-10-07 against 527 tasks (command output, TBC, re-verify when the board changes): `dupes` found no pair at 0.55
  or at 0.35; evidence found 15 apparent stale paths against delivery's tree alone, 8 against this checkout and 0 against every
  fetched branch, so each of the 15 was a file on an unmerged branch. The full check and the `--shared-only` check printed the same
  lines on the live dump, exit 0. After the change's independent review (the evidence rule above), the same dump gives no
  evidence finding: 11 trees read (HEAD and 10 fetched branches, 0 unreadable) in 0.28 seconds, exit 0.
- Still to do from VH-377: `Merge into` on the board page (visual, so it waits on the owner's picture) and the audit of V2.8.

## Rules that must not be relaxed
- Measured or marked: pace comes from rows, never from memory; with nothing measured the output says so.
- A settings record is refused whole if anything is wrong with it; the problems are listed together.
- Re-plans are deterministic. A plan with a warning is shown with the warning, never trimmed to look clean.
- A release name is never written into an item note: the release field is the only current placement.
- The ethos above: speed and efficiency balanced with quality and release standards, zero waste, zero duplication.

## Tests and proof
`python3 scripts/brain.py selftest` runs 198 tests. `python3 tests/mutations.py` reverts each rule in turn and
confirms the suite goes red (200 of 200 caught on 2026-10-07). It first runs the unmutated suite in its copy and refuses to go on if that is red: from VH-380
until VH-377 the copy failed with no mutation applied, so every mutation read as caught. The baseline and every mutation are built from
one snapshot taken at the start, so an edit made during a run cannot reach it, and each run's temporary files stay inside
its copy and go with it. Four checks drive the board page in a real browser wherever node, playwright-core and a Chromium are present:
`tests/test_board_merge_page.py` (Merge into) and the three in `tests/test_board_settings.py`. The harness and `selfcheck` leave
them out, so the rules only a browser can see were proved red by hand on 2026-10-07, 16 of 16, each in a copy of the pack.
`tests/make_example.py` rebuilds the worked example (`assets/example`, the Vendor Fishing backlog classified by hand) from a board dump.

## The board page (VH-584)
`assets/board/board.html` is the board: one file, no build step, published as a claude.ai artifact. It reads the board's 8
collections, `board/meta` and one settings document, `board/settings`. Every setting falls back, field by field, to what this
project's board drew before settings existed, so a board with no settings document draws exactly what it did; a field set to null
switches its feature off. The settings: `organisation` and `project` (the brand line), `refPrefix`, `budget` (`floorMin`, `capMin`:
the budget wording and the over-cap mark, which is a warning and never a limit), `overheadMin` (the guide's words for the fixed time
a release costs), `store` (`{name}`, or null for no store: no upload step, no refusal allowance), `rounds` (`{limit, label}`, or null:
the round-rule line on the gate chart), `horizon` (how many planned releases a roll-forward keeps), `sync` (`staleMin`,
`refreshWaitMin`, `idleChecks`) and `source` (`name`, `detail`, `command`, `onRelease`: where the pipeline is read from and what
Claude is told). Those are the document's names; the settings record spells them in its own style, below. Release names stay
`V<major>.<minor>` and the palette stays Bluestaq's (owner, D2 and D3).
- The settings record's optional `board` section feeds the document: `organisation`, `store` (`{"name": ...}` or null), `rounds`
  (`{"limit": ..., "label": ...}` or null), `horizon`, `sync` (`stale_min`, `refresh_wait_min`, `idle_checks`), `source` (`name`,
  `detail`, `command`, `on_release`) and `url` (the board's link), with the project's name, ref prefix and release figures from the
  rest of the record. The section is checked with the record and refused with it, an unknown key included. The page's own limits on
  the rest of the record (whole minutes up to 100000, a cap above zero, a name of 80 characters, a ref prefix of 1 to 11, `V` release
  names, gate keys the store accepts as document ids, and neither `build` nor `upload`, which the page draws itself) are checked only
  where a board is built, so a record that planned before still plans. `brain.py board settings --config FILE` prints the document;
  `brain.py board seed --config FILE` prints the ArtifactData batch a new board needs: `board/settings`, `board/meta`, the current
  release and the horizon behind it, its releases row, one document per gate, and the store's upload last when there is a store. It
  prints and writes nothing; an agent applies it. An upgrade that keeps a record the page could not draw says what to change.
- Publishing, in order: publish the page with the capabilities in `assets/board/capabilities.json` and no URL; write the link into
  the record as `board.url`; apply the seed batch (the store refuses an update to a missing document, so the page cannot write until
  it has run); have the coordinating session watch the board; set up the hourly sync from `assets/board/SYNC-TEMPLATE.md`. A later
  republish passes the URL and leaves the capabilities out, and an upgrade reaches the page only when it is republished.
- Each project writes its own pipeline feed into `gates` (owner, D4); this project's is `.claude/board/sync_pipeline.py`.
- `brain/board.py` holds the defaults and the wording the page uses, and `tests/test_board_settings.py` runs the page's own settings
  code in node against it. Three browser checks render the page with `assets/board/render_board.cjs`: another project's settings
  reach every place they should, settings that reproduce today's values draw exactly what no settings draws and the strings pinned
  from the page before settings existed, and a board built only from the seed takes the page's own writes against a store that
  refuses an update to a missing document with `invalid_argument`, as the platform does.
- This board needs no settings document: the page's defaults are its values. Its record, `.claude/board/brain.config.json`, has no
  `board` section, so `brain.py board settings` on it gives no organisation line, no store and no round rule, and writing that
  document would change this board. The section that reproduces today exactly is `docs/VH-584-board-section.json`, Backlog's to
  apply or not.
- Measured on 2026-10-07 against the live board's data (TBC, re-verify on any page change): with no settings document and with
  settings that reproduce today's values (`brain.board.PAGE_DEFAULTS`), the page drew 23 of 23 screens byte for byte as today's page
  did. Today's page varied by one pixel between two of its own renders, on the intake form's focus ring.
- Not known yet (TBC, re-verify): which runtime contract a new board receives (this one is pinned at 0.2.54), whether reading a
  never-written collection gives the folder `check` expects, and whether the owner-only write rule is enforced on the server.
