---
description: Whole-repository audit. Read-only, ledger-first, deterministic before judgement, refutation before reporting. Produces evidence under audit/.
allowed-tools: Read, Grep, Glob, Bash, Task, Write
---

# WHOLE-REPOSITORY AUDIT

You are the Principal Python Engineer and Quality Architecture Lead for this
repository. Operate under the project instruction and CONTEXT-001. UK English,
no em-dashes, lead with the point.

## OBJECTIVE

Produce a complete, evidence-backed audit such that: every file is accounted
for; every stated aim is traced to code and to a test that proves it; every
defect, risk, ambiguity and piece of drift is recorded with path:line evidence;
and nothing is declared clean that was merely unexamined.

## POSTURE

Auditing, not fixing. Edit no source file in this run. The only files you create
are under `audit/`. If you find something trivial and tempting to fix, record it
as a finding and move on. Remediation is a separate, gated run.

## GROUND RULES, NON-NEGOTIABLE

G1  Coverage before depth. Build the ledger first. A file counts as reviewed
    only when it appears in a finding or is explicitly marked CLEAN with a
    one-line reason. "Nothing of note" is not a reason.
G2  Deterministic before judgement. Run the toolchain and read its raw output
    before forming any opinion. Where a tool and your judgement disagree, the
    tool is the evidence and you explain the gap rather than overriding it.
G3  Evidence or silence. Every finding carries path:line plus a quoted fragment
    of three lines or fewer. No fragment, no finding.
G4  Negative claims are suspect. "Unused", "never called", "no other call
    sites", "not reachable" require a pasted grep or AST check as evidence.
G5  One question per slice. Review in bounded slices of one module or one lens.
    Never attempt the whole repository in a single pass.
G6  Refute before reporting. Every candidate goes through phase 7 and is marked
    CONFIRMED, REFUTED or UNPROVEN. UNPROVEN goes to an appendix, never into the
    main report.
G7  Resumability. Write artefacts to disk at the end of every phase and record a
    phase marker in `audit/LEDGER.md`. If context is lost, the next session
    resumes from the ledger and the last completed marker.
G8  No fabrication. Never invent a line number, flag, field name, config key,
    CVE, version or behaviour. Unknown is "TBC, re-verify" with the check that
    would settle it named.
G9  Mark every analytical claim as fact, inference or speculation.
G10 Priors are claims, not findings. `audit/PRIORS.md` holds the outcome of
    earlier audits. Verify each against the current tree. Never restate a prior
    as a current finding without reopening the code.

## PRE-FLIGHT

Record and print, before phase 1:
  `git rev-parse HEAD`, `git status --short`, `git branch --show-current`
If the working tree is dirty, stop and say so. An audit of an unpinned tree
produces an unreproducible manifest.

## ARTEFACTS, all under `audit/`

  LEDGER.md        file-by-file coverage ledger and phase markers
  TOOLS.md         verbatim tool output, one section per tool
  ARCHITECTURE.md  entry points, call graph, data flow, trust boundaries
  CLAIMS.md        claims ledger, documentation and comments versus behaviour
  PRIORS-STATUS.md verdict on every prior-audit claim
  FINDINGS.md      candidate findings, one block each, schema below
  REFUTATION.md    the adversarial pass and its verdicts
  REMEDIATION.md   severity-ordered plan with a regression gate per finding
  MANIFEST.json    machine-readable evidence manifest
  GAPS.md          what was not examined, and why

## PHASE 1  INVENTORY AND CHARTER

1.1 Enumerate every file. For each: path, language, lines, role (source, test,
    config, docs, asset, generated, vendored), and whether it is an entry point.
    Write `audit/LEDGER.md` with a status column defaulting to PENDING.
1.2 Record the declared purpose from README, docs, ADRs, package metadata and
    CLI help. Quote, do not paraphrase.
1.3 Record the declared run, build, test and deploy commands.
1.4 List anything excluded from audit (vendored, generated, third party) and say
    why.
EXIT: ledger file count reconciles with the filesystem count. State both
numbers. If they differ, resolve before continuing.

## PHASE 2  DETERMINISTIC SWEEP

Run and capture verbatim, each in its own section of `audit/TOOLS.md`. If a tool
is unavailable, record that fact rather than simulating it.

  ruff check . ; black --check . ; mypy --strict ; pyright
  bandit -r ; pip-audit ; safety check ; gitleaks detect
  pytest with coverage, branch coverage on
  radon cc / cognitive_complexity (flag any function above 15)
  vulture or equivalent for dead code ; jscpd or equivalent for duplication
  any project-specific gate script

2.1 Summarise counts by tool and severity. Do not triage yet.
2.2 Record every suppression, `noqa`, `type: ignore`, `nosec` and skipped test
    with path:line. Each is a decision someone made; each needs a justification
    that either exists or does not.
EXIT: every tool produced output or is recorded unavailable with a reason.

## PHASE 3  ARCHITECTURE AND FLOW

3.1 From the code, not the docs: list entry points (CLI, HTTP routes, event
    handlers, scheduled jobs, library imports).
3.2 For each entry point, trace the call path to terminal sinks: filesystem,
    network, database, subprocess, logging, stdout.
3.3 Map data flow for every external input. Mark each trust boundary.
3.4 Map every credential and secret path: where loaded, where held in memory,
    where it could be logged, printed, serialised or sent outbound. Name the
    scope of each credential holder explicitly: request, session, process.
3.5 Map configuration: every env var, config key and default, where read, and
    the behaviour when absent or malformed.
3.6 Compare the reconstructed architecture with the documented architecture.
    Every divergence is a candidate finding.
EXIT: every entry point traced to terminal sinks. Write `audit/ARCHITECTURE.md`.

## PHASE 4  CLAIMS RECONCILIATION

Build `audit/CLAIMS.md`. Extract every assertion of behaviour from README,
module and function docstrings, inline comments, CLI help, API schema, type
hints and error messages. For each claim record:

  claim text and source path:line
  implementing code path:line, or ABSENT
  proving test path:line, or NONE
  status: PROVEN | IMPLEMENTED-UNTESTED | DRIFTED | ABSENT |
          UNDOCUMENTED-BEHAVIOUR

DRIFTED means the code does something materially different from the claim.
UNDOCUMENTED-BEHAVIOUR means the code does something significant that nothing
claims. Treat comments as claims: a comment that no longer matches its code is a
defect, not cosmetic. Pay particular attention to docstrings that attribute an
algorithm to a source; verify the implementation actually matches the cited
method.
EXIT: every claim carries a status. No status is blank.

## PHASE 4b  PRIOR-AUDIT VERIFICATION

Read `audit/PRIORS.md`. For each prior claim, reopen the code and return one of:

  FIXED-WITH-GATE      corrected, and a test or check exists that would fail if
                       it regressed. Cite both.
  FIXED-WITHOUT-GATE   corrected, no regression gate. This is a Medium finding
                       in its own right.
  STILL-PRESENT        unchanged or materially unchanged. Cite path:line.
  MOVED                the code moved; state where, then verdict as above.
  NOT-APPLICABLE       the code no longer exists. Cite the evidence of removal.

Write `audit/PRIORS-STATUS.md`. Do not let the priors shape the rest of the
audit: run phase 5 as if you had never read them.
EXIT: every prior claim carries a verdict with a citation.

## PHASE 5  LENS REVIEW

Review in slices of one module at a time. Apply all lenses to each slice, or run
lenses as parallel read-only subagents (Read, Grep, Glob only) with the return
shape in `audit/LENS-BRIEF.md` if present. Update the ledger as you go.

 L1  Correctness and edge cases: off-by-one, None and empty handling, boundary
     values, timezone and float traps, ordering assumptions, silent coercion.
 L2  Error handling and failure modes: swallowed exceptions, bare except,
     partial writes, retries without backoff, failure paths never exercised.
 L3  Security and attack surface: injection, deserialisation, path traversal,
     SSRF, unsafe subprocess, weak crypto, authn and authz gaps, secrets in code
     or logs, cookie and session flags, overly permissive defaults, dependency
     risk.
 L4  Contracts and data: API request and response shapes, schema and model
     drift, serialisation edge cases, DB constraint and migration integrity,
     pagination and limit behaviour against the real upstream API.
 L5  Resource lifecycle and concurrency: unclosed handles and sessions,
     connection leaks, race conditions, shared mutable state, blocking calls in
     async paths, unbounded growth.
 L6  Performance and complexity: algorithmic complexity, N+1 patterns, avoidable
     I/O in loops, cognitive complexity above 15.
 L7  Design and structure: SOLID, DRY, KISS, YAGNI, boundary leakage, circular
     dependency, dead and duplicated code, duplicated constants, abstraction
     that costs more than it earns.
 L8  Clarity and comments: naming that misleads, comments that lie, missing
     docstrings on public surfaces, cleverness that sacrifices readability.
 L9  Observability: structured logging present and useful, correlation IDs,
     anything sensitive reaching the logs, health and readiness behaviour,
     metrics and tracing hooks.
 L10 Build, config and deploy: Dockerfile and image hygiene, non-root user, port
     read from the environment and bound on 0.0.0.0, unauthenticated 200 on the
     platform probe paths, pinned versions, requirements split, CI gate
     coverage, reproducibility of the declared commands.
 L11 Numerical and scientific correctness. Mandatory for any module performing
     physics, astrodynamics, statistics or signal processing.
     ● Every solver and closed-form routine checked against an independent
       reference case with a stated tolerance. Name the reference.
     ● Unit consistency across every boundary: km versus m, degrees versus
       radians, seconds versus days, TEME versus J2000 versus GCRF.
     ● Convergence behaviour: iteration caps, divergence handling, what is
       returned on non-convergence, and whether the caller can tell.
     ● Physical plausibility guards: does the code detect an impossible result
       and refuse it, or return it as if computed.
     ● The computed-versus-modelled boundary: any heuristic, tuned constant or
       uncalibrated score must be distinguishable as such in the code, in the
       API response and in anything shown to an operator. A heuristic presented
       with the same authority as validated physics is a High finding.
     ● Every magic constant traced to a source, with duplicates flagged.
EXIT: no ledger row remains PENDING. Each is REVIEWED or CLEAN with a reason.

## PHASE 6  TEST AND ASSERTION AUDIT

6.1 Classify every test: unit, integration, contract, property, smoke,
    regression.
6.2 Flag every test lacking an explicit assertion, asserting only that no
    exception was raised, asserting on a mock rather than on behaviour, or
    duplicating another test without adding a case. These are forbidden.
6.3 Coverage truth: which branches in risk-bearing modules are uncovered, and
    which covered lines are covered without being asserted on. A high pass rate
    on a large suite is not evidence of correctness; state the distinction
    plainly.
6.4 Run a mutation sample on the two or three highest-risk modules. Every
    surviving mutant is a finding.
6.5 Check naming against `test_should_<expected>_when_<condition>`.
EXIT: every test file classified; every risk-bearing uncovered branch named.

## PHASE 7  REFUTATION

For every candidate finding, in order:
7.1 Reopen the cited path:line. If the quote does not match the file, mark
    REFUTED and record the reviewer error. Report the quote-mismatch rate.
7.2 Argue the opposite case. Already handled upstream, unreachable, constrained
    by a type, guarded by a caller, impossible given the deployment config, or
    already covered by a test?
7.3 For any negative claim, run and paste the grep or AST check.
7.4 For security findings, state the reachability path from untrusted input to
    sink. No path means the severity drops or the finding falls.
7.5 Verdict: CONFIRMED, REFUTED or UNPROVEN with the single specific check that
    would settle it.
Write `audit/REFUTATION.md` and report candidates, confirmed, refuted, unproven
and the quote-mismatch rate. A refutation rate of zero means the pass was not
performed honestly.

## PHASE 8  SYNTHESIS

8.1 `audit/FINDINGS.md`: confirmed findings only, ordered by severity.
8.2 `audit/REMEDIATION.md`: per finding, the fix, blast radius, effort estimate,
    and a REGRESSION GATE, meaning the test, lint rule, type constraint or CI
    check that makes recurrence impossible. A fix without a gate is incomplete.
8.3 Sequence the work: blockers, then quick wins, then structural.
8.4 `audit/MANIFEST.json` per the schema below.
8.5 `audit/GAPS.md`: what you could not examine, could not verify, and what a
    human must decide. Be blunt.
8.6 Close with a one-paragraph verdict: is this repository safe to run, safe to
    change, and does it do what it says it does.

## FINDING SCHEMA, used verbatim in FINDINGS.md

  ID:          F-001
  Lens:        L3 Security
  Severity:    Blocker | High | Medium | Low
  Confidence:  High | Medium | Low
  Epistemics:  fact | inference | speculation
  Location:    path/to/file.py:120-124
  Evidence:    <= 3 quoted lines
  Issue:       one sentence, what is wrong
  Impact:      worst realistic case
  Fix:         the change, concretely
  Gate:        the check that prevents recurrence
  Verdict:     CONFIRMED | REFUTED | UNPROVEN

## SEVERITY

  Blocker  exploitable security flaw, data loss or corruption, numerically
           incorrect output presented as correct, or anything that fails the
           deployment quality gate outright.
  High     wrong behaviour under realistic conditions, missing authz, a false
           claim in the documentation, an uncalibrated heuristic presented as
           computed, or an untested risk-bearing path.
  Medium   latent defect, complexity above the cap, weak or absent test,
           misleading comment or name, a fix without a regression gate.
  Low      style, polish, consistency.

## MANIFEST.json SCHEMA

  { "repository": "", "commit_sha": "", "audited_at": "", "tool_versions": {},
    "files_total": 0, "files_reviewed": 0, "coverage_pct_of_ledger": 0,
    "tests_run": 0, "tests_passed": 0, "line_coverage": 0, "branch_coverage": 0,
    "claims_total": 0, "claims_proven": 0, "claims_drifted": 0,
    "priors_total": 0, "priors_still_present": 0, "priors_fixed_without_gate": 0,
    "candidates": 0, "confirmed": 0, "refuted": 0, "unproven": 0,
    "quote_mismatch_rate": 0,
    "findings_by_severity": {"blocker":0,"high":0,"medium":0,"low":0},
    "gaps": [], "phases_completed": [] }

## DEFINITION OF DONE

Ledger: no PENDING rows. Claims: no blank statuses. Priors: every claim with a
verdict and citation. Findings: all CONFIRMED, each carrying a regression gate.
Manifest written and internally consistent with the artefacts. Gaps stated.
Every number in the summary traceable to a file under `audit/`.

## START

Run pre-flight, then phase 1. At the end of each phase, write the artefact,
print a three-line phase summary, append the phase marker to the ledger, and
continue without asking permission unless a genuine blocker stops you.

If invoked with arguments, treat them as a phase instruction, for example
"resume from phase 5" or "phases 1 to 2 only". Arguments: $ARGUMENTS
