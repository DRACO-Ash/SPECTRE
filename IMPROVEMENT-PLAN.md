# Improvement plan: folding the SPECTRE retrospective back into the baseline

Produced by the `learn-from-feedback` loop on 2026-09-09. **Proposal only.** Nothing
here has been applied, and nothing should be until a human picks the items.

## Two limits on this plan, stated before anything else

**The corpus is one report.** The skill is explicit that a single report is a data
point rather than a theme, and that it should be used alone "only if it names
something sharp and specific". The SPECTRE retrospective does, so the loop has been
run, but nothing below is a *recurring* theme and none of it should be treated as
one. Every item is marked with whether anything outside this single report supports
it. When the next two or three reports land, re-run the synthesis before applying
anything marked "uncorroborated".

**This is not the baseline repository.** The loop was run inside SPECTRE
(`/home/user/SPECTRE`), which is a consumer of the Foundations bundle, not the
bundle itself: there is no `.claude/` tree and no `CLAUDE.md` here. Every item below
targets a baseline skill that this repository cannot edit. The plan is a document to
carry to the baseline repo and apply there, under the normal gates.

## Themes found

One report, so these are the sharp specifics rather than clusters. Three carry across
projects; the rest are single-instance.

● **A green pipeline is not working software.** Nine passing App Store gates shipped
  an image with a capability switched off and an admin page that could not display a
  record it had just written. Both were invisible to 850 tests because both were
  failures of what a browser did with a correct 200 response.
● **Guards are written and never watched to fail.** Not one check written in the
  eight-day window has a committed case proving it can go red, including the five
  fail-closed branches that decide whether an artefact ships at all.
● **Rules that read a file nothing tracks, and floors set below the standard they
  claim to enforce.** Two separate instances of a gate that cannot do its job.

## Prioritised items

Ordered by the size of the class each closes, and by whether anything beyond this one
report supports it.

### 1. A browser smoke probe in the standard checks, for any archetype with a UI

● **Target:** `app-store-readiness`, and the quality-loop template it ships.
● **Change:** For any project whose archetype is a UI-bearing service, add a probe
  that drives a real browser against a running instance: log in, load the primary
  page, perform one mutation, and assert zero console errors and zero unhandled
  rejections. Fail the check on any console error, not just on a bad status code.
● **Rationale:** This is the class that shipped two live defects. Both returned HTTP
  200 and both were invisible server-side. A status-code assertion cannot see them;
  a console-error assertion sees both immediately.
● **Evidence:** Ashley Higgins, 2026-09-09, SPECTRE 0.4.0 to 0.5.9. "850 test
  functions across 40 files, and not one of them drove a browser." **Corroborated
  outside this report:** the `learn-from-feedback` skill itself cites "a browser
  probe" as one of four executable guards that each "closed a class outright" on a
  previous project. That makes this the only item here with support beyond n=1, which
  is why it is first.
● **Size:** M. Executable.

### 2. A guard ships with the case that proves it goes red

● **Target:** the engineering guidance in the baseline, plus the quality-loop
  template.
● **Change:** Establish the convention that a new check, test-as-guard or budget is
  incomplete until a committed case demonstrates it failing, and add a reporting step
  to the quality loop that lists guard-style tests with no paired negative case. Ship
  it as a warning first, not a hard gate, so it can be calibrated before it blocks.
● **Rationale:** The retrospective's own guards section is the finding. Several
  guards *were* watched to fail by hand, and the mutation was then reverted rather
  than committed, so nobody can re-run any of them. The `project-retrospective` skill
  already asks the right question at the end of a build; the gap is that nothing asks
  it at the moment the guard is written.
● **Evidence:** Ashley Higgins, 2026-09-09. "Nothing written in this window has a
  committed failing case." Uncorroborated beyond this report, but note the skill's
  own remark that this is "the most commonly absent section across the reports
  received so far", which suggests the underlying gap is not unique to SPECTRE.
● **Size:** M. Partly executable; the pairing check is a naming-convention scan, and
  it will need tuning.

### 3. A test harness for the packaging script's fail-closed branches

● **Target:** the packaging template in `app-store-readiness`.
● **Change:** Ship fixture trees and a harness that runs the packager against each
  and asserts every `FAIL` branch fires: missing ledger entry, more than one probe,
  a recognised manifest present in a docker-only build, a credential-shaped file, a
  populated secret.
● **Rationale:** These five branches decide whether an artefact ships. No test
  executes the script at all, so they are the least covered code in the project and
  the most consequential. This is item 2 applied to the highest-stakes guard in the
  bundle.
● **Evidence:** Ashley Higgins, 2026-09-09. "No test executes the packager at all.
  These are the guards that decide whether an artefact ships, and they are the least
  covered code in the project." Uncorroborated.
● **Size:** M. Executable.

### 4. A gate may not depend on a file that is not tracked

● **Target:** the packaging template and any gate script in the bundle.
● **Change:** Before a gate reads a file, assert the file is tracked
  (`git ls-files --error-unmatch`). Fail with a message naming the file.
● **Rationale:** `docs/` is gitignored by the standard template, and the change-ledger
  gate reads a file in `docs/`. The gate therefore passed on one machine and would
  have failed everywhere else until the file was force-added. Two baseline rules
  interacting to produce a gate that silently does not run.
● **Evidence:** Ashley Higgins, 2026-09-09. "A gate whose input is untracked is not a
  gate." Uncorroborated, but the failure mode is generic to any bundle that both
  gitignores a directory and gates on a file inside one.
● **Size:** XS. Executable. Best value-to-effort ratio in this plan.

### 5. A local floor may not sit below the standard it reproduces

● **Target:** the quality-loop template and the `pyproject.toml` template.
● **Change:** Source the coverage threshold from one place and fail the loop if the
  project-local floor is below the house standard.
● **Rationale:** `fail_under = 70` against a house standard of 80, with actual
  coverage at 74.3 per cent. The loop reported green while sitting under the bar it
  exists to enforce.
● **Evidence:** Ashley Higgins, 2026-09-09, citing `pyproject.toml` and
  `coverage.xml`. Uncorroborated.
● **Size:** XS. Executable.

### 6. Treat the submission archive as the analysis scope

● **Target:** `app-store-readiness`, packaging template and preflight check.
● **Change:** Document that the platform's Code Quality stage analyses every file in
  the uploaded archive and does not honour `sonar.sources`, and add a preflight check
  that fails when the staged archive contains build tooling, CI configuration or
  internal documentation.
● **Rationale:** The source declaration was ignored and build tooling was graded as
  application code, producing five findings against files that never run in
  production. The fix was forced rather than chosen.
● **Evidence:** Ashley Higgins, 2026-09-09. "Our `sonar.sources` was ignored; the
  platform scans the whole archive." Uncorroborated, but it is a property of the
  platform rather than of SPECTRE, so it will affect every Python submission.
● **Size:** S. Executable.

### 7. Lift the change ledger into the baseline

● **Target:** a new small artefact in the bundle, plus the packaging template.
● **Change:** Generalise SPECTRE's change ledger: a file that classifies every change
  as EVIDENCED, PROBE or HYGIENE, states what a failure would rule out, caps a
  submission at one probe, and blocks the build when the current version has no entry.
  The gate already exists and works; it needs lifting and de-projecting.
● **Rationale:** This is a contribution from the project rather than a complaint about
  the baseline. It was introduced at release 0.5.2 after a stretch of unforced errors,
  and both probes it governed produced a definite answer rather than a shrug. It is
  the mechanism that converted guessing into measurement.
● **Evidence:** Ashley Higgins, 2026-09-09. "Eight entries, nine evidenced changes,
  three probes, two recorded outcomes." Uncorroborated as a baseline need, but its
  effect within the project is documented across `docs/CHANGE-LEDGER.md`.
● **Size:** S. Executable; the gate is roughly fifteen lines of shell.

### 8. A failure-signature reference for the App Store stages

● **Target:** `app-store-readiness`, and `glossary` for the terms.
● **Change:** For each pipeline stage, record what artefacts a successful run
  produces, so their absence is diagnosable. Lead with the one that cost most:
  Dependency Scanning writes `gl-sbom-*.cdx.json` before it looks anything up, so no
  SBOM and no report means the analyser crashed, and the interface's "Vulnerable
  dependencies found" is then wrong.
● **Rationale:** Roughly twelve of twenty releases in this window went on reading a
  crash as a finding. The distinguishing evidence was in the first failure log.
● **Evidence:** Ashley Higgins, 2026-09-09. "A missing report artefact is a crash."
  Uncorroborated within the corpus, but the platform-side defect has been raised
  separately.
● **Size:** S. Prose, with a small diagnostic helper. **Mark as an unenforced
  convention**: the reference itself cannot fail a build.

### 9. A local reproduction of a gate must carry a calibration table

● **Target:** `app-store-readiness`.
● **Change:** Any locally built reproduction of a gate the project cannot obtain must
  ship a calibration table against known-pass and known-fail samples, and must be
  advisory unless it matches on all of them.
● **Rationale:** The open-source analyser built to stand in for the platform's fork
  disagreed with the real gate on two of three control samples, including calling a
  passing package a failure. It was demoted to advisory only after it had been
  trusted.
● **Evidence:** Ashley Higgins, 2026-09-09. "Confidence in a local reproduction of a
  gate you cannot obtain should start at zero." Uncorroborated.
● **Size:** S. Prose. **Mark as an unenforced convention.**

## Declined, with the measurement that declines them

● **More prose rules about honesty or self-correction in the retrospective skill.**
  The existing calibration floors already worked: they forced the guards section,
  which produced the most valuable finding in the report. Adding rules here grows the
  prose count without closing a finding, which is exactly the residuals ratio the
  skill warns about.
● **A baseline rule adopting `htmx.config.useTemplateFragments`.** It would have
  fixed the swap defect in one line, but it changes fragment parsing for every swap
  in an application, and the session that found it could not smoke-test the rest.
  One project, one framework version, one occurrence. Item 1 catches the same class
  without betting on a config flag.
● **A prose rule saying "always reproduce before fixing".** It is the behaviour that
  worked in this window, but as a sentence it is unenforceable and adds to the
  backlog. Item 1 is its executable form; ship that instead.
● **Everything SPECTRE-specific.** Case-sensitive usernames, the absent
  `HRR_List.json`, and the missing self-service password reset are application
  findings, not baseline findings. They belong in the SPECTRE backlog and are
  recorded in `RETROSPECTIVE.md`. Folding them into the bundle would make it worse.

## Ratio check

Seven of the nine proposed items are executable; two are prose and are marked as
unenforced conventions. Items 1 to 6 each close a class rather than adding a rule.
That is the right side of the residuals ratio, but it only holds if items 1 to 3
actually get built: they are the ones that carry the weight, and they are also the
three largest.

## Credits

● **Ashley Higgins**, 2026-09-09, SPECTRE (Python 3.12 and FastAPI, container
  service), releases 0.4.0 to 0.5.9. Sole contributor to this synthesis.

## Before applying

Re-run the loop when two or three more reports have accumulated. Items 2 to 9 are
uncorroborated single-report findings, and the skill is right that one report is not
yet a theme. Item 1 is the exception and can be taken now.
