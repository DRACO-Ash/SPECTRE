# PRIORS: outcome of the SPECTRE audit of 16 July 2026

**Status of this file:** claims to verify, not findings to repeat. Each entry
was confirmed against the tree as it stood on 16 July 2026. Whether it holds
today is unknown from here. Phase 4b reopens each one and returns a verdict.

**Verdicts:** FIXED-WITH-GATE | FIXED-WITHOUT-GATE | STILL-PRESENT | MOVED |
NOT-APPLICABLE. Every verdict carries a path:line citation. FIXED-WITHOUT-GATE
is itself a Medium finding, because a corrected defect with no regression check
is a defect waiting to return.

**Anchoring warning:** read this file only at phase 4b. Run phase 5 as if you
had never seen it. A reviewer primed with a defect list finds that list and
little else.

**Provenance caveat:** these entries are reconstructed from the record of the
July 2026 session, not from the original audit document. Identifiers D1 to D10
were used in that session; D4 is not recovered here. If the original audit
artefact exists, reconcile against it before relying on this file, and record
any entry you cannot reconcile as TBC, re-verify.

---

## P1 (D1) Lambert solver universal-variable error

**Claim, fact as at July 2026.** The Lambert solver substituted the square root
of y over mu in place of the correct universal-variable relation, the square
root of y over C(z). Velocity vectors were approximately 25 per cent off, and
co-altitude LEO transfers produced physically impossible delta-V values. The
`_solve_z` routine and its dF/dz derivative were both implicated, and the
docstring attributed the algorithm to a method the implementation did not match.

**Agreed remediation at the time.** Correct the relation and the derivative,
correct the docstring attribution, and add a hard regression test asserting
against Curtis example 5.2 to within 1e-3 km/s.

**Verify now.**
● Does the implementation use C(z) in the chi relation? Cite the line.
● Does the dF/dz derivative match the corrected form?
● Does the docstring attribution match what the code actually does?
● Is there a regression test pinning the solver to an independent reference
  case with a stated tolerance? If there is no such test, the verdict is
  FIXED-WITHOUT-GATE even if the maths is now right.
● Severity if still present: Blocker. Incorrect numerical output presented as
  computed truth.

---

## P2 (D2, D5) Heuristics presented with the authority of physics

**Claim, fact as at July 2026.** The Decision Engine was built on hardcoded
arbitrary constants presented to the operator as analysis. Uncalibrated
heuristic scoring functions were not differentiated from validated physics
anywhere in the operator interface.

**Agreed remediation at the time.** A "modelled estimate, not a computed
solution" banner on the Decision Engine output and on every heuristic score.

**Verify now.**
● Is the computed-versus-modelled distinction present in the code, in the API
  response payload, and in the rendered interface? All three, not one.
● Is every tuned constant traceable to a stated source or calibration run, or
  is it still asserted?
● Does any API consumer receive a heuristic score with no accompanying
  provenance field?
● Severity if still present: High.

---

## P3 (D3) Silent failure sinks in the threat sweep

**Claim, fact as at July 2026.** `except Exception: pass` sinks in `threat.py`
swallowed errors, dropping targets from the sweep without the operator knowing.

**Agreed remediation at the time.** Replace with logged, operator-visible
"target dropped: reason" flags.

**Verify now.**
● Grep the whole tree for bare `except`, `except Exception` with `pass`, and
  `contextlib.suppress` on broad exception types. Paste the output.
● For each remaining sink, state whether the operator can tell that something
  was dropped.
● Severity if still present: High. An analysis tool that silently discards
  inputs produces confident, incomplete answers.

---

## P4 (D6) Session cookie without the secure flag

**Claim, fact as at July 2026.** The session cookie was set without
`secure=True`.

**Verify now.**
● Cite the cookie-setting call and every flag on it: secure, httponly,
  samesite, domain, path, max-age.
● Confirm there is no environment-dependent branch that disables the flag
  outside development.
● Severity if still present: High.

---

## P5 (D-unnumbered) UDL credentials in a process-global in-memory dict

**Claim, fact as at July 2026.** UDL credentials were stored in plaintext in a
process-global in-memory dictionary. The agreed target was session-scoped,
encrypted in memory, never process-global.

**Verify now.**
● Trace the credential from entry to use. Name the holder and its scope:
  request, session, or process.
● Can the credential reach a log line, an exception traceback, a serialised
  response, a debug endpoint, or a crash dump?
● Does the App Store deployment inject credentials as environment variables, and
  if so is the in-process path still present as well?
● Severity if still present: High, and a security boundary worth flagging
  separately in the summary.

---

## P6 (D7) No provenance stamping at module boundaries

**Claim, fact as at July 2026.** Module outputs were not stamped with version
and inputs. The decomposition plan identified module boundaries as exactly where
provenance gets lost.

**Verify now.**
● Does any computed product carry the version of the code and the identity of
  the inputs that produced it?
● Is the recorded assertion manifest discipline implemented anywhere, or still
  aspirational?
● Severity if still present: Medium, rising to High for anything an analyst
  would cite downstream.

---

## P7 (D8) Duplicated Earth radius constant

**Claim, fact as at July 2026.** The Earth radius was defined in more than one
place.

**Verify now.**
● Grep for every physical constant definition. Paste the output.
● For each duplicate, confirm the values agree to full precision and name the
  single source they should come from.
● Severity if still present: Medium. Duplicated constants diverge silently and
  the divergence surfaces as a physics bug.

---

## P8 (D9) Unresolved STK dependency question

**Claim, fact as at July 2026.** It was undecided whether SPECTRE is pure
Python or STK-backed. Astrogator notes and COM references remained in the tree.

**Verify now.**
● Are Astrogator notes, COM references or STK imports still present?
● If pure Python, this is dead weight and a claims-ledger problem, because the
  documentation implies a capability that does not exist.
● Severity if still present: Medium, and route it to the claims ledger as well
  as to findings.

---

## P9 (D10) Regression test coverage on the critical physics path

**Claim, fact as at July 2026.** The `astro` package lacked a textbook
regression suite. `tle_clustering` had one. The closed-form solvers (Hohmann,
bi-elliptic, vis-viva, plane change, J2, Clohessy-Wiltshire) validated correctly
when tested by hand during the audit, but that validation was not captured as
tests in the repository.

**Verify now.**
● For each solver, is there a test asserting against an independent reference
  case with a stated tolerance, or only a test that the function runs?
● Hand validation that is not in the suite is not a gate. Record which solvers
  are gated and which are merely believed correct.
● Severity if still present: High for the solvers on the critical path,
  Medium elsewhere.

---

## P10 Static quality baseline

**Claim, fact as at July 2026.** 601 tests passing, ruff clean, mypy strict
clean, bandit reporting no medium or high findings.

**Verify now.** Re-establish the numbers in phase 2 and compare. This is a
baseline, not a defect.

**Judgement note.** A repository with this profile produces a low finding count
and invites a clean verdict. Judge this run by the claims-ledger drift count,
the number of solvers without a reference-case gate, and the refutation rate,
not by the finding total. The July 2026 audit found a Blocker-class numerical
defect in a repository that was ruff clean, mypy strict clean and passing 601
tests. Static cleanliness and correctness are different properties.
