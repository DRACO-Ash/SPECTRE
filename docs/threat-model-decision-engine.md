# Decision Engine threat model

**Status: DRAFT for the owner's security lead to review, correct and sign. It is not signed and it does not close
gate G9 by itself.** Drafted for SPC-199 against evaluation finding F-08 (Critical, gate G9: "Threat model and
integrity controls for inputs, configuration and decision records, consistent with ISN 2023/09"). G9 stays Red until
the security lead has reviewed and signed this model, a dated and owned plan exists for what remains, and the
evaluation is repeated.

**Basis.** Every "what exists" below is read from the code at the path named, at commit `adeb112` (release
0.31.0) with the SPC-199 change on top, uncommitted when this draft was written. Every "what remains" is the drafter's view, offered for the security lead to accept, change or reject; none
is a ruling. Every owner is "the owner's security lead" because no other owner is recorded for any of these threats.

## Scope

● **In scope.** The Decision Engine (the modules in `spectre/domain/` listed in `docs/lookup-register.md`), the inputs
  it reads, the records and stored inputs it writes, and the console that carries them: the browser pages, the
  routes in `spectre/web/routes/decision.py`, and the UDL credential an operator lends the session.
● **Out of scope.** The hosting platform, its router and TLS, the network, the database server and the operating
  system; training mode, whose objects are synthetic; GCAT except as a source of names.
● **What the engine is.** Advisory: every outbound call in `spectre/` is a GET, to UDL or to GCAT (`spectre/web/routes/gcat.py`), so no engine output reaches an
  effector (evaluation gate G1, advisory half). A wrong recommendation therefore harms through the operator who
  trusts it. That is why integrity is the property this model weighs most.

## What is protected

| Asset | Why it matters | Where it lives |
|:-|:-|:-|
| The recommendation and its figures | Confident wrong advice is the harm F-08 names | Computed per evaluation; shown on the results |
| Element sets | Every computed figure rests on them | `SessionState` in `spectre/web/planning_state.py`; stored inputs |
| Weights, rule, vetoes and P | They decide the pick among the figures | Each evaluate request; stored inputs |
| Decision records and stored inputs | Accountability (G1) and replay (G2) | `decision_records` table, `spectre/web/models.py` |
| Friendly priorities | Responses, weights, vetoes and rationale reveal what we would do and what we value | Records, stored inputs, the process log |
| The UDL credential | Reaches an authoritative external service in the operator's name | Session memory, `spectre/web/planning_state.py` |
| The operator's session | Every control above is reached through it | Signed cookie, `spectre/web/auth.py` |

## Threat register

| ID | Threat | What exists (path) | What remains | Owner |
|:-|:-|:-|:-|:-|
| T1 | Poisoned or corrupted element sets from UDL, from an operator's paste or from the background refresh | One acceptance check on every ingest path since SPC-201: line structure, both checksums, one catalogue number and every field in range, with a refusal sentence naming the object; on a refused refresh the held set is kept (`spectre/astro/elset_check.py`, `spectre/web/elsets.py`, `tests/integration/test_elset_ingest_paths.py`). The operating envelope flags what the engine is not fit for (`spectre/domain/decision_envelope.py`, `docs/decision-engine-envelope.md`). Each set's data mode and age are shown and stored | The checksum is a modulo 10 digit: it catches a slip, not a forgery, so a set altered on purpose with its checksums recomputed passes. Nothing checks a set against the object's own history (a jump in elements no manoeuvre explains). UDL answers over TLS with no signature of its own, so the integrity of a set rests on UDL and the transport | The owner's security lead |
| T2 | Tampered weights, rule, vetoes or P in the evaluate request | Per-request form values behind the session and the CSRF token (`spectre/web/auth.py`, `spectre/web/csrf.py`), bounded and parsed by name (`spectre/web/routes/decision.py`); every value used is shown under Judgement inputs and stored with the record (SPC-196, SPC-193); a ticked veto needs a reason and is never picked (SPC-195) | Nothing ties a weight set to an approved one: an operator, or script running in the operator's session, can submit any weights in bounds. Whether weights and the rule should come from signed configuration rather than the form is a decision for the security lead with the owner (SPC-151 sources the weights) | The owner's security lead |
| T3 | Tampered priors: the NOTSO notices behind a suggested P | NOTSO records are fetched with the operator's UDL credential and cached in `notso_cache.json` in the data directory (`spectre/data/notso_cache.py`); a suggestion is only applied when the operator ticks it, and the notices behind it are listed with their dates (SPC-131) | The cache file is plain JSON on disk with no integrity check: anyone who can write the data directory can change the history a suggestion is drawn from. It is shared by every operator | The owner's security lead |
| T4 | Tampered lookups: the constants that set a figure, a score or a pick | Each is listed with its value, source and owner in `docs/lookup-register.md`, and `tests/unit/test_lookup_register.py` fails when a value in the code and the register differ or a new constant is unlisted | The register holds a value against accidental change in review; it does not stop a change made in both places. The protection is the code review and the release process | The owner's security lead |
| T5 | Integrity of decision records and stored inputs | One record per finished evaluation (`spectre/web/decision_record.py`, SPC-192); the stored inputs are canonical JSON with their SHA-256, read strictly (`spectre/domain/decision_inputs.py`, SPC-193); a replay sets the record's own columns and the input hashes held apart against the replay's (`spectre/domain/decision_replay.py`, `scripts/replay_decision.py`); a decision is taken once and refused a second time | The SHA-256 sits beside the text it covers, so it shows accidental change only; an edit that rehashes passes it, and the hashes held apart are in the same row. Nothing makes the table append-only, nothing signs a record, and nothing records who changed a row. Anyone with write access to the database can alter history | The owner's security lead |
| T6 | Non-repudiation: an operator denying a decision, or one made in another's name | The record carries the account id and username from the signed session, and the decision its own UTC time; only the operator who ran the evaluation may decide it (`spectre/web/routes/decision.py`) | No signature binds the operator to the record, and an administrator of the database can rewrite it. Sessions are revoked on logout and password change, which limits a stolen cookie to 8 hours at most | The owner's security lead |
| T7 | Confidentiality of what the records reveal: friendly priorities | Records are read through the console only: an operator sees their own, an admin every one (`/plan/decision/records`). The process log holds one line per evaluation naming the recommendation and rule | No encryption at rest beyond what the database server gives; no retention is applied (SPC-228 is the owner's open ruling); the classification of a record follows the deployment's marking and no more. Who may read the records, and for how long, is for the security lead with the data protection lead | The owner's security lead |
| T8 | The UDL credential: theft, misuse or leakage | Entered per sign-in, held only in that sign-in's memory, never written to disk or logged; blanked on logout, password change and account deletion (`spectre/web/planning_state.py`, `clear_account_state`); a custom repr hides the password. The audit's record of how it was held is `audit/ARCHITECTURE.md` section 3.4 | The password is plaintext in process memory for the life of the sign-in and is handed to background tasks that outlive the request. Data fetched with one operator's entitlement (the on-orbit catalogue, the NOTSO cache) is served to every operator. A service credential, or a token with a narrower scope, would remove both | The owner's security lead |
| T9 | Browser-side injection: script in a name, a note or a fragment running in an operator's session | Output escaping under autoescape (`tests/integration/test_xss_escaping.py`); since SPC-199 a Content Security Policy whose `script-src` is `'self'` alone: no inline script, no handler attribute, no `hx-on`, no eval, and htmx with `allowEval` and `allowScriptTags` off (`spectre/web/app.py`, `spectre/web/templates/base.html`, `spectre/web/static/js/`). `tests/unit/test_no_inline_script_or_handler.py` holds the templates to it and `tests/browser/` drives every moved behaviour under the policy, and shows an injected handler, script block and `hx-on` refused | The policy stops injected script, not injected markup. Markup that got past the escaping still acts through htmx and the console's own scripts without running any script of its own: an element carrying `hx-get` or `hx-post` with `hx-trigger="load"` sends a same-origin request when it lands, and inherits the CSRF token from `hx-headers` on `<body>` (`spectre/web/templates/base.html`), so it reads or changes whatever the operator's session can, records included; an element carrying `data-init`, `data-action` or the other names in `spectre/web/static/js/core.js` runs that registered behaviour on landing or on a click. A review of SPC-199 showed an injected `hx-get` to `/plan/decision/records` sending the token and rendering the records with no policy violation. Nothing sets `hx-disable` where outside text lands. The escaping is therefore still the control against this class; the policy narrows what an escaping defect gives an attacker but does not close it. `style-src` still allows inline style, so injected markup can also restyle the page and hide or mimic a control. The browser tests need Chromium, which the CI runner does not install, so in CI they skip and say so | The owner's security lead |
| T10 | A compromised dependency | Python dependencies are hash-locked (`requirements.txt`, `requirements-dev.txt`); the vendored scripts are pinned by SHA-256 in `spectre/web/static/vendored.json` and checked against OSV (`scripts/audit-vendored-js.py`); the SBOM is checked (`scripts/check-sbom.py`); Dependabot watches the pip dependencies and the workflow actions weekly (`.github/dependabot.yml`) | No assessment of the suppliers themselves; UDL and GCAT are external services whose own assurance is not recorded here | The owner's security lead |
| T11 | Exhausting the engine: an evaluation built to run for ever | A 300 s budget per evaluation and a sample-hour cap, refused with a sentence (`spectre/domain/decision.py`, `docs/decision-engine-envelope.md`); one sampled evaluation runs on the server at a time, the rest wait QUEUED with their budget not yet started, and each sign-in holds at most one job, a newer evaluation stopping the earlier one (`spectre/web/decision_job.py`); rate limits on sign-in and UDL calls (`spectre/web/rate_limit.py`) | The queue has no cap of its own and no fairness between operators: every sign-in may hold one queued job, so one account signed in many times, or many accounts, can keep others waiting up to 300 s per job ahead of them. Evaluate has no rate limit (`spectre/web/routes/decision.py`) | The owner's security lead |

## The 7 principles of ISN 2023/09

The evaluation's framework names the 7 Secure by Design principles of ISN 2023/09 (21 July 2023). Each is set out
below with what the repository shows and what it does not.

### 1. Understand and Define Context

● **What exists.** The engine is advisory and decides nothing (G1, advisory half). Its trust boundaries are listed in
  `audit/ARCHITECTURE.md` section 3.3; its operating envelope in `docs/decision-engine-envelope.md`; this model
  adds the threats to the engine itself (T1 to T11).
● **What remains.** The deployment's classification, the system's security owner, its accreditation route and the
  Security Operating Procedures are not in the repository. Whether the engine is safety-related (G8) is open.
● **Owner.** The owner's security lead.

### 2. Plan the Security Activities

● **What exists.** Security work is carried as backlog items with an evaluation finding each (F-08, F-25 and others).
● **What remains.** No security plan with dates and owners exists, which is also why several gates are Red rather
  than Amber. The "what remains" column above is a starting list for one.
● **Owner.** The owner's security lead.

### 3. Implement Continuous Risk Management

● **What exists.** This register, the audit's findings (`audit/FINDINGS.md`) and the evaluation's register.
● **What remains.** No one owns the register or reviews it on a cadence; no risk has an accepted level. Each threat
  above needs a likelihood, an impact and a decision: treat, tolerate, transfer or terminate.
● **Owner.** The owner's security lead.

### 4. Define Security Controls

● **What exists.** The controls named under "what exists" in the register: the acceptance check on every element
  set, the session and CSRF controls, the record and its stored inputs with their hash and replay, the lookup
  register, the strict script policy, and the bounds on every engine input.
● **What remains.** Record integrity beyond accidental change (T5, T6), integrity of the NOTSO cache (T3), approved
  weights (T2) and the UDL credential (T8) have no control designed for a deliberate attacker. The script policy
  does not stop injected markup that acts through htmx attributes or the console's registered behaviours (T9), so
  output escaping remains the only control against that; whether to add `hx-disable` around outside text, or to
  move the CSRF token off `<body>`, is for the security lead.
● **Owner.** The owner's security lead.

### 5. Engage and Manage the Supply Chain

● **What exists.** Hash-locked dependencies, pinned vendored scripts with an OSV check, an SBOM check (T10).
● **What remains.** No supplier assessment of UDL, GCAT or the library maintainers is recorded; the element sets and
  notices from UDL are trusted as UDL serves them (T1, T3).
● **Owner.** The owner's security lead.

### 6. Assure, Verify and Test

● **What exists.** The developer suite, including the ingest refusals, the escaping tests, the policy pinned
  character for character (`tests/integration/test_security_headers.py`) and, since SPC-199, the browser tests
  under the policy; an independent evaluation (`evaluation/`).
● **What remains.** No penetration test and no data-poisoning test (a set altered with its checksums recomputed,
  T1) have been run; framework level 4 for L7 asks for both. The browser tests do not run in CI (T9).
● **Owner.** The owner's security lead.

### 7. Enable Through Life Management

● **What exists.** Refusals and evaluations are logged with operator-supplied values neutralised
  (`spectre/web/log_safety.py`); records are kept with no retention applied.
● **What remains.** No monitoring of the logs, no alert on a burst of refused element sets or on a record changed
  after it was written, no patch cadence and no plan for retiring records.
● **Owner.** The owner's security lead.

## Decisions taken drafting this

These are the drafter's, not rulings, and each is for the security lead to confirm or change.

● Integrity is weighted above confidentiality and availability, because the engine is advisory and its harm is
  confident wrong advice.
● The register names only threats to the engine and what carries it; platform and network threats are left to the
  deployment's own model.
● Every owner is the owner's security lead, because no other is recorded; the security lead may delegate.
● A threat is listed even where a control exists, so the control and its limit are both on the page.
