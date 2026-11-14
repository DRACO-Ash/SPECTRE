# Mutation report: spectre/astro and the web security core (SPC-071)

Coverage says a line ran; mutation says whether a test would notice the line
being wrong. Every mutant the operators below can make was generated for the
22 modules of spectre/astro and the six files of the web security core, and
each was run against the tests that execute its line, on 724a897 plus the
tests this change adds.

The two scopes come from different runs. The web security core was re-run on
2026-11-05 with runner version 4 (`HARNESS = 4` in scripts/mutate.py), which
checks every kill with the killing test alone. The spectre/astro figures were
not re-run: they come from the run of 2026-11-04 with runner versions 1 to 3,
before that check existed, and may include order-dependent false kills. The
astro section says how many of its kills were checked alone and how many
were not.

## Result

| Scope | Mutants | Killed or timed out | Survived | No covering test |
|---|---:|---:|---:|---:|
| Web security core (re-run 2026-11-05, runner version 4) | 465 | 417 | 44 | 4 |
| spectre/astro (2026-11-04, runner versions 1 to 3, not re-run) | 5,455 | 3,161 | 2,102 | 192 |

The security core's 48 remaining mutants are all accounted for below: 37 are
equivalent, six are on the PostgreSQL row lock and are killed there, one is
unreachable, and four are order-dependent false kills the re-run uncovered,
each of which an existing test kills when run alone. The astro survivors in the core geometry modules are killed or
shown equivalent; the rest are listed in
[MUTATION-SURVIVORS-ASTRO.md](MUTATION-SURVIVORS-ASTRO.md).

## How it was run

`scripts/mutate.py` is the runner, committed with this report. It needs
nothing beyond the dev requirements (pytest, pytest-cov, coverage). The
audit's mutate.py (audit/working/tools/mutate.py) held 21 hand-written
mutants; this one generates every mutant its operators can make.

1. `map` runs pytest under coverage with a context per test and a JUnit file,
   so the runner knows which tests run each line and how long each takes.
2. `run` forks one child per mutant, four or five at a time. The child serves
   the mutated module from memory through an import hook, so the working tree
   never changes, and runs the covering tests with `-x`: the module's own test
   files first, then unit before integration, then the cheapest file first,
   each file's tests in their own order. A mutant that survives a short quick
   pass is run again against every covering test, or for the larger astro
   modules against up to 10 to 20 s of them, before it is recorded as
   surviving. Results append to a JSON lines file, so a run resumes.
3. `report` prints the tables in this document.

Operators: arithmetic, augmented assignment, comparison, `and` and `or`,
removal of `not` and of unary minus, integer n to n plus 1, float 0.0 to 1.0
and f to 1.5 f, True and False swapped, `return x` to `return None`, a bare
call statement to `pass`, and in the security core a string s to "XX" s "XX".
Not mutated: docstrings, annotations, f-strings, logging calls, code under
`TYPE_CHECKING`, `__all__` and lines marked `pragma: no mutate`.

Six faults in the runner were found and fixed, each of which had inflated
the score. They are recorded because a mutation score is only as
good as the harness behind it.

● Tests from different modules were interleaved, which tore down a
  module-scoped app fixture mid-module and failed the unmutated code. The
  runner now refuses to start when the unmutated file fails its own quick pass.
● A module-level line was attributed by coverage to whichever test first
  imported the module, so a constant was run against one or two tests. Such
  lines now select every test that reaches the module, and every test file
  that imports it by name.
● Two children starting the app at once raced on the SQLite probe file the
  app writes into ./data at start-up. The loser failed a test unrelated to the
  mutant, a false kill: 124 astro mutants and ten in the security core
  had been recorded as killed this way. Each child now has its own data,
  SQLite and temporary directories, and every kill made by a test that starts
  the app was run again.
● Parametrised test ids built from the mutated values no longer resolved. The
  runner now falls back to running those test files whole.
● A test that leaned on an earlier test failed whenever the mutant's run left
  that test out, whatever the mutant did. Three admin route tests edited an
  account another test created, and 45 security-core kills had been credited
  to them; a race test failed after them for the accounts they left behind.
  A kill now counts only once the tests that ran, up to and including the
  one that failed, pass on the unmutated code; where they do not, the mutant
  is run against its covering files whole. Every kill in both scopes was
  checked again this way: a recorded killer was run alone against the mutant
  and then against the unmutated code, and any kill that did not hold went
  back through the full run. The three tests now make their own account, and
  test_admin_routes.py removes every account it creates. 22 security-core
  kills did not hold. Nine are now killed: one by the self-contained admin
  tests, five by the new tests below, and three, on the PostgreSQL row lock,
  on PostgreSQL. The other 13 are equivalent and listed. Every astro kill
  rechecked this way held.
● That control proves the unmutated code passes the tests that ran; it does
  not prove the mutant is what failed the killing test. A test that fails
  only because of what earlier tests in the run left behind (an account, a
  bumped session generation) passes the control and still credits a kill.
  Runner version 4 runs the killing test alone against the mutant before it
  records a kill. If it passes alone, the kill was order-dependent and the
  mutant is recorded as a survivor, marked "killed only after other tests" in
  the report. A killer that was the first test of its run has already run
  alone. tests/unit/test_mutation_runner_kills.py pins the rule. In the
  security core re-run, 185 kills needed that second, solo run: 181 held and
  four did not.

To repeat the run:

```
python scripts/mutate.py map --state STATE --target spectre/astro --target spectre/web tests/unit
python scripts/mutate.py map --state STATE --target spectre/astro --target spectre/web tests/integration
python scripts/mutate.py run --state STATE --strings spectre/web/auth.py spectre/web/csrf.py ...
python scripts/mutate.py run --state STATE --quick-seconds 2 --full-seconds 10 spectre/astro/*.py
python scripts/mutate.py report --state STATE --survivors FILE ...
```

Each `run` stops starting new mutants after `--budget` seconds and resumes
where it stopped. The full set took about two hours of four cores. The
security core re-run took 10 minutes to map, in five parts, and 27 minutes to
run, in four parts of under 10 minutes each.

The runner stops a mutant's run at the first failing test. When that test
passes alone, the mutant is recorded as a survivor even if a later test, which
the run never reached, would kill it alone. Such a survivor is a lower bound
on the suite, not proof of a gap, so each one is checked by hand below.

## The web security core

| Module | Mutants | Killed | Timed out | Survived | No covering test | Score |
|---|---:|---:|---:|---:|---:|---:|
| spectre/web/auth.py | 92 | 84 | 0 | 8 | 0 | 91.3% |
| spectre/web/csrf.py | 59 | 54 | 0 | 5 | 0 | 91.5% |
| spectre/web/rate_limit.py | 48 | 45 | 2 | 1 | 0 | 97.9% |
| spectre/web/log_safety.py | 18 | 12 | 0 | 6 | 0 | 66.7% |
| spectre/web/routes/login.py | 64 | 61 | 0 | 3 | 0 | 95.3% |
| spectre/web/routes/admin.py | 184 | 159 | 0 | 21 | 4 | 86.4% |

These figures are on SQLite, the database the mutation run uses, where the
PostgreSQL tests are skipped. Seven of admin.py's survivors and untested
mutants are on the PostgreSQL row lock: six are killed on PostgreSQL 16 by
tests/integration/test_postgres_admin_lock.py, and the seventh is equivalent,
as the table of what remains says.

Before the tests below, once the runner's faults were fixed, 103 mutants
survived here. The gaps they showed, and the tests that close them:

● The plain HTML form path of the CSRF check was untested: every test sent
  the token in the header. Removing the form fallback, mis-parsing a content
  type with a charset, or dropping multipart forms left the suite green.
  tests/unit/test_csrf_request_paths.py drives both dependencies with real
  requests, including a forged login with no cookie, no field or an empty
  field, and a request with no session cookie.
● No test let a rate-limit window elapse, so deleting the line that forgets
  an old call, in either is_allowed or is_blocked, survived (as a hang), as
  did evicting a key on the window's exact edge and every tier's budget and
  window. tests/unit/test_rate_limit_windows.py runs the module's own
  limiters on a held clock.
● The login route's address window, the sentence a locked-out operator reads,
  the "unknown" caller, the login token cookie's lifetime, the sign-in id's
  length, and a second sign-out were unpinned. An account from before the
  nonce column, whose sessions carry an empty nonce, was untested, so a
  default other than the empty string would have locked such accounts out.
  tests/integration/test_login_outcomes.py.
● The admin routes: the inline edit row was never requested (the test named
  for it fetched the list page), no route was given an id that does not
  exist, the 64-character username bound was tested on neither side, and
  every refusal was matched on a lowercase fragment a reworded or misfiled
  message still contains. tests/integration/test_admin_route_outcomes.py
  reads each answer as the admin does: the sentence, and whether it is styled
  as an error or a success.
● The refusal a failed sign-in gets when concurrent failures spend the
  budget between the up-front check and the charge had no test.
  tests/integration/test_concurrent_sign_ins.py (SPC-073) holds four attempts
  at a barrier to reach it.
● log_safe's marker rule at a limit of three or fewer characters.
  tests/unit/test_log_safety.py.
● Found once the false kills were removed: the login page's token was never
  checked to differ between pages (a constant token is one a forging site
  can fill in); the refusal sentence was matched as a substring, so text
  around it went unnoticed; the sweep that drops quiet rate-limit keys was
  not pinned to once a window; and the last admin resetting their own
  password, keeping the admin role, was untested, so a guard that refused it
  as a demotion survived. test_login_outcomes.py, test_rate_limit_windows.py
  and test_admin_route_outcomes.py.
● The PostgreSQL lock on the demotion path (admin.py:233) had no test that
  could fail without it: holding every admin row also holds the row being
  demoted, which the write waits on with or without the lock.
  test_postgres_admin_lock.py now holds only the acting admin's row, which
  neither write touches, so only a write that takes the lock waits.
● That test shows the demotion takes the lock, not that the lock stops the
  race it exists for (audit F-149). test_postgres_admin_lock.py now also runs
  that race: two demotions of the last two admins, in two transactions, the
  second started while the first has written and not committed. With the lock
  the second waits, counts one admin and is refused. With the call at
  admin.py:233 removed it counts two in its own snapshot and both commit,
  and the test fails with "two overlapping demotions left 0 admins".

The re-run with runner version 4 recorded four kills from the 2026-11-04
run as order-dependent: the first test to fail each mutant passes when run
alone against it. Each is killed by another existing test run alone, checked
against the mutant and against the unmutated code, so none is a gap in the
suite. They stay in the table above as the runner recorded them.

| Mutant | Change | First failing test, which passes alone | Killed alone by |
|---|---|---|---|
| auth.py:94 | `username_taken` returns None | test_last_admin_race.py::test_a_racing_delete_cannot_remove_the_last_admin | test_username_case.py::TestCreationRefusesANameThatDiffersOnlyInCase::test_a_lower_case_copy_of_an_existing_name_is_refused |
| auth.py:158 | the token's "gen" key written as "XXgenXX" | test_web_routes.py::TestAssetAddAndRemoveF267::test_an_empty_name_is_refused[blue] | test_login_hardening.py::TestRevocationDoesNotRefuseTheNextSession::test_signing_straight_back_in_after_logout_works |
| auth.py:175 | the token's "gen" key read as "XXgenXX" | test_decision_custody_wait.py::test_a_bound_evaluation_refetching_a_stale_history_says_it_is_a_fresh_fetch | the same sign-back-in test |
| admin.py:340 | the delete guard `User.id == user.id` to `!=` | test_admin_routes.py::TestDeleteUser::test_cannot_demote_the_last_admin | test_admin_route_outcomes.py::TestDeleting::test_one_of_two_admins_can_be_deleted |

The two "gen" mutants read every token as generation 0, so once an account
has signed out once, every later sign-in is refused. The first failing tests
saw that only because earlier tests had signed the shared admin out; the
sign-back-in test makes its own account and signs it out itself.

What remains, each with the reason it is equivalent or out of reach:

| Mutant | Change | Why it stays |
|---|---|---|
| auth.py:35 | session signer salt "spectre-session" altered | Equivalent within a process: every token is signed and checked with the same salt, and the CSRF signer's salt stays distinct. |
| auth.py:124 | `SessionClaims` no longer frozen | Equivalent: nothing assigns to a SessionClaims or hashes one. |
| auth.py:141 (three) | make_session_cookie's defaults for generation, nonce and sign-in id | Equivalent: its only caller, the login route, passes all three. |
| csrf.py:93, csrf.py:123 | content-type default "" to "XXXX" | Equivalent: with no Content-Type header both values are not a form type. |
| csrf.py:127 (two), csrf.py:130 | token default "" to "XXXX" | Equivalent: "XXXX" is not a signed value, so it can never verify, exactly as the empty string cannot. |
| log_safety.py:74 (six) | the literals of `_without_line_breaks` | Equivalent: the helper is a no-op on what log_safe built, which already holds no line break. It exists so CodeQL recognises a sanitiser, as its docstring says. |
| rate_limit.py:124 | `return False` to `return None` in is_blocked | Equivalent: every caller tests the result for truth. |
| login.py:100 | the throwaway secret behind the absent-user hash, 32 to 33 bytes | Equivalent: any unguessable secret serves; nothing reads its length. |
| login.py:236 (two) | the generation step at sign-out, start 0 to 1 and step 1 to 2 | Equivalent: revocation compares a token's generation with the stored one by `<`, so any strictly rising step revokes every earlier token. A step that did not rise is killed by the repeated sign-out test. |
| admin.py:83, 85, 205, 224 | the "request" key in a template context | Equivalent: none of the three partial templates reads `request`. |
| admin.py:187, 303, 364 (two each) | the success flash's "type" key or "success" value | Equivalent: the flash template asks only whether the type is "error". Every error-flash mutant is killed. |
| admin.py:135 | the list page's "flash" key | Equivalent: the template reads an absent flash as it reads None. |
| admin.py:232 (two) | `and` to `or`, and the second "admin" in the demotion test of `_set_role` | Equivalent: `_set_role` runs only when the role changes, so the role it is given differs from the account's, and both changes give the same answer for every such pair. The same "admin" in update_user (admin.py:272) is reachable and is killed. |
| admin.py:237, 345 | the rollback after a refused write | Equivalent: nothing is pending when the guarded write matches no row, and the request's session ends its transaction when it closes. |
| admin.py:238 | `return False` to `return None` | Equivalent: the caller tests the result for truth. |
| admin.py:117 | "sqlite" to "XXsqliteXX" | Equivalent: on SQLite the lock statement then runs, but SQLAlchemy renders no FOR UPDATE for SQLite; on PostgreSQL nothing changes. |
| admin.py:117 (`!=` to `==`), 118 (three), 233, 339 | the PostgreSQL row lock: whether it is taken, the statement, and each call | Run only on PostgreSQL, so SQLite cannot tell. tests/integration/test_postgres_admin_lock.py, which runs in the PostgreSQL CI job, kills all six: each mutant was run on PostgreSQL 16 against that test and failed it, and the unmutated code passed. Its race test, two concurrent demotions of the last two admins, kills five of the six on its own, admin.py:233 among them, by leaving no admin; the sixth, at 339, is on the delete path, which the delete test kills. |
| admin.py:164 | "Password is required." | Unreachable: the form layer answers 422 for an empty field before the route runs. The 422 is now tested. |

## spectre/astro

| Module | Mutants | Killed | Timed out | Survived | No covering test | Score |
|---|---:|---:|---:|---:|---:|---:|
| along_track.py | 47 | 43 | 0 | 4 | 0 | 91.5% |
| catalogue.py | 18 | 17 | 0 | 1 | 0 | 94.4% |
| closest_approach.py | 107 | 92 | 0 | 15 | 0 | 86.0% |
| constants.py | 53 | 43 | 0 | 10 | 0 | 81.1% |
| cw_geometry.py | 202 | 128 | 0 | 74 | 0 | 63.4% |
| dv_estimation.py | 476 | 296 | 0 | 161 | 19 | 62.2% |
| elset_approach.py | 37 | 36 | 0 | 1 | 0 | 97.3% |
| events.py | 71 | 28 | 1 | 42 | 0 | 40.8% |
| kepler.py | 80 | 73 | 0 | 7 | 0 | 91.2% |
| lambert.py | 255 | 159 | 2 | 94 | 0 | 63.1% |
| maneuvers.py | 613 | 205 | 4 | 383 | 21 | 34.1% |
| monte_carlo.py | 665 | 312 | 7 | 258 | 88 | 48.0% |
| notso.py | 239 | 140 | 0 | 94 | 5 | 58.6% |
| pattern_of_life.py | 511 | 308 | 2 | 196 | 5 | 60.7% |
| phase_angle.py | 8 | 8 | 0 | 0 | 0 | 100.0% |
| photometry.py | 454 | 268 | 0 | 174 | 12 | 59.0% |
| propagator.py | 214 | 156 | 0 | 46 | 12 | 72.9% |
| response_burn.py | 90 | 69 | 1 | 20 | 0 | 77.8% |
| tactical.py | 1,110 | 618 | 0 | 470 | 22 | 55.7% |
| tle_filter.py | 63 | 52 | 0 | 10 | 1 | 82.5% |
| tle_preprocessing.py | 93 | 45 | 0 | 41 | 7 | 48.4% |
| transfers.py | 49 | 46 | 2 | 1 | 0 | 98.0% |

These figures were not re-run with runner version 4. They come from the run
of 2026-11-04, with runner versions 1 to 3, and may include order-dependent
false kills. Of the 3,161 kills and timeouts, 3,049 were rechecked by runner
version 3 with the killing test alone against the mutant, the same check
version 4 makes, and held. The other 112 were not: 82 kills recorded by
version 3 from a full run, 11 kills from whole test files and 19 timeouts
recorded by version 1. The survivors were not affected by the change, as it
can only turn a kill into a survivor. Re-running spectre/astro with version 4
is the way to settle those 112.

### Killed, because a real defect could hide there

tests/unit/test_astro_edges_from_mutation.py, each a place an operator's
figure or flag would change without a test noticing:

● The element set the sweep re-solves with when it moves an orbit along
  track (shift_along_track): its checksum was never checked, a named
  three-line set lost its name and first line, and a mean anomaly carried
  past 360 degrees did not have to wrap.
● The closest-approach search: its default one-minute grid (a 90 s grid steps
  over a 50 s encounter), which of two encounters it reports when the window
  starts and ends at the same separation, and whether a refined point in a
  one-step window is called the window's edge.
● The transfer formulas' bounds: a radius on the Earth's surface, an
  intermediate radius equal to the outer orbit, and a Hohmann transfer's
  third burn.
● Orbit regime classification, which decides which targets a sweep flies
  against a red object: ten of its survivors, including the LEO ceiling, the
  GEO band's width, the final fallback, the 0.3 eccentricity rule and the
  default of a circular orbit, are killed by a table of representative orbits.
  Two more are killed by element sets exactly at the 0.25 and 0.3
  eccentricity bounds: a TLE's seven-digit field gives those values exactly,
  and at the bound the orbit is MEO, not HEO.
● The geostationary radius behind the graveyard raise: a 300 km raise costs
  10.9 m/s.

### Equivalent, in the modules where a defect matters most

● along_track.py (4): the two TLE field slices one column wider pick up a
  blank or the first digit of the revolution number, a change in the tenth
  significant figure; a minus sign never occurs in line 2; the line padding
  width is never read past column 68.
● closest_approach.py (15): the golden-section and grid comparisons at exact
  equality, which only change the order of equal values; the grid slack and
  the run-merging test, which give the same candidate for every plateau; the
  sample count in an error message; the frozen flag on the result, which
  nothing assigns to; and the 0.01 s default refinement tolerance, which
  changes a reported TCA by milliseconds. The refined-point index mutant that
  could mark an interior point as the edge is killed.
● kepler.py (7): the iteration cap, the convergence tolerance and the
  near-parabolic starting guess, none of which changes a converged answer for
  the closed orbits the sweep flies.
● constants.py (10, now 9): comparisons of a perigee or apogee altitude at
  exactly a band edge. None is equivalent: each changes the regime of an orbit
  whose altitude lands on the edge to the bit. They are left because nothing
  relies on which side of an edge such an orbit falls, with two exceptions
  that were judged on their own. The earlier reason, that altitudes come from
  the mean motion and so never land on an edge, was wrong: the threat route
  and the Monte Carlo sampler pass a Keplerian semi-major axis, which can.
  ■ constants.py:91, `apogee_alt > _MEO_MAX_ALT` to `>=`, inside the 0.25
    eccentricity rule. With e above 0.25 and at most 0.3, only that rule can
    call an orbit HEO, so an orbit with e = 0.28 and its apogee exactly on the
    GEO band's floor (35,386 km) is MEO by the code and HEO by the mutant. It
    is a real orbit, with its perigee at 17,114 km, so it is now killed:
    test_astro_edges_from_mutation.py::TestRegimeClassification::test_an_eccentric_orbit_with_its_apogee_exactly_on_the_geo_floor_is_not_heo
    fails on the mutant and passes on the code. The eccentricity comparisons
    on lines 91 and 94 were already killed by the 0.25 and 0.3 bound tests.
  ■ constants.py:94, `apogee_alt > _LEO_MAX_ALT` to `>=`, inside the 0.3
    eccentricity rule. It differs only for an apogee of exactly 2,000 km with
    e above 0.3. Such an orbit's perigee radius is under 8,378 km times
    0.7 / 1.3, about 4,511 km, so its perigee is at least 1,867 km inside the
    Earth. No orbit that exists reaches it, so it stays, unkilled, for that
    reason.
● transfers.py and elset_approach.py (one each): a default no constructor
  relies on, and the message argument of an internal exception.

Not equivalent, and left as it is: catalogue.py:26, `set(text) <= _DIGITS`
to `<`. It differs only for a word that holds every one of the ten digits, so
ten characters or more. intel.py and pattern_of_life.py pass a TLE's columns
3 to 7, five characters, and cannot reach it. notso._norad_id_of passes the
first word of a NOTSO's catalogue-number field, which can be any length, and
there it changes the answer: "1234567890" is read as 1234567890 by the code
and as no number by the mutant, so that NOTSO goes uncorrelated, and
"0123456789" is read as 123456789 by the code and as no number by the mutant.
"1111111111" is read as a number by both, so the mutant is not a length rule.
It stays because no catalogue number in use has ten characters, so no real
NOTSO is filed differently, and a test would pin an answer nothing relies on.
Whether notso.py should refuse a catalogue field longer than nine digits is
for its owner.

### Listed, not yet judged

The other 2,061 survivors and 192 mutants on lines no test runs are in
[MUTATION-SURVIVORS-ASTRO.md](MUTATION-SURVIVORS-ASTRO.md), for the owners of
those modules. By operator they are mostly numeric constants (about half) and
arithmetic and comparison changes (about a fifth each). The largest groups
are in tactical.py, maneuvers.py, monte_carlo.py and pattern_of_life.py, where
many tests assert only that a figure is finite or ranked, not its value. That
is the next place to look.
