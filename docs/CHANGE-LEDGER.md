# Change ledger

Every version that goes to the App Store gets an entry here BEFORE it is built.
`scripts/package-appstore.sh` refuses to build a version that has no entry.

The point is to stop shipping changes that teach nothing when they fail. Each
entry must answer three questions, and the classification is the honest part:

● **EVIDENCED** - something in a job log, a source file, or a reproduced run
  names this as the cause. Name it. A failure after an EVIDENCED fix means the
  evidence was misread, which is itself informative.
● **PROBE** - a reasoned guess. Allowed, but only ONE per submission, and only
  when the row below says what a failure would rule out. A submission carrying
  two probes cannot tell you which one mattered.
● **HYGIENE** - unrelated to any gate. Must not change what the gate sees.

If a gate has no evidence and no useful probe, the correct entry is "no change,
no hypothesis". Say that instead of inventing one.

---

## 0.5.2

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **EVIDENCED** | Stop shipping `scripts/` and `.github/` | The job log names `scripts/preflight-gate.py:213` (hotspot), `:34`, `:50`, `:234` and `scripts/package-appstore.sh:246`. All five findings are in files that are build tooling, not application code. `sonar-project.properties` declares `sonar.sources=spectre,tle_clustering`, so the platform is analysing the whole archive and ignoring our declaration. | Then the platform analyses files we do not ship, or `sonar-project.properties` is being honoured after all and the findings came from somewhere else. Either is a real, narrow answer. |
| Dependency Scanning | **NO HYPOTHESIS** | None | Seven failures. The contract from the gate skill is satisfied and its preflight reports 0 blocking. Every content hypothesis I have held has been wrong: header form, pyproject presence, `requirements.lock`, manifest count, lock generator. | n/a. I am not shipping a change for this gate without evidence. The analyser image is not public and its error text has never been read. |

**Standing note on Dependency Scanning.** Do not add a change for this gate to a
future entry unless one of these arrives: the analyser's real error text, the
`.pre` resolution job's log, or a file-level diff against a package that passes.
Anything else is a guess dressed as work.
