ID:          F-S08-01
Lens:        L3 security
Severity:    Blocker
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/login.py:132-141
Evidence:
    matched = await run_in_threadpool(verify_password, password, hashed)
    if user is None or not matched:
Issue:       The password is verified before either limiter is consulted, and the limiters are consulted only on failure, so an account that has exhausted its budget still accepts a correct password with 302; the 429 is just a renamed 401.
Impact:      Online password guessing is bounded only by bcrypt throughput in the threadpool (inference: of the order of 100 guesses a second per pod), and the guessing loop learns the answer the moment it lands, against a public, CSRF-exempt endpoint; the comment at login.py:54-55 claims the opposite.
Fix:         Call both `is_allowed` checks (or a read-only "is blocked" check) before `run_in_threadpool(verify_password, ...)` and return 429 without verifying when either budget is exhausted; keep charging only on failure.
Gate:        Integration test: exhaust the username tier with 10 wrong passwords, then post the correct password and assert 429 and no `spectre_session` cookie.
Negative-check:Grep `status_code == 429` in tests/integration/test_login_hardening.py: 2 hits (lines 95, 115), both with verify_password stubbed to False; no test posts a correct password after exhaustion.

ID:          F-S08-02
Lens:        L3 security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/auth.py:59, spectre/web/auth.py:102, spectre/web/routes/admin.py:144
Evidence:
    return str(_serializer().dumps({"sub": username, "gen": int(generation)}))
    return generation < (user.session_generation or 0)
    new_user = User(username=username, hashed_password=hash_password(password), role=role)
Issue:       The token binds only the username and a generation counter, and a recreated account restarts at generation 0 (models.py:53-58), so any unexpired token from a deleted account with the same name authenticates as the new account.
Impact:      An admin deletes a compromised or departed "alice" and recreates "alice" (possibly as admin) within 8 hours; every captured token of the old account is accepted, with the new account's role.
Fix:         Put the immutable user id (or a per-account random nonce set at creation) in the payload and require it to match the loaded row; alternatively never reuse a generation by seeding new rows from a global monotonic value.
Gate:        Integration test: log in as X, admin deletes X and recreates X, replay the old cookie, assert 302 to /login.
Negative-check:Grep `"sub"` in spectre/web/auth.py: payload keys are only `sub` and `gen` (auth.py:59, 72).

ID:          F-S08-03
Lens:        L5 resource lifecycle and concurrency
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/admin.py:283-285, spectre/web/planning_state.py:126-133
Evidence:
    username = user.username
    await db.delete(user)
    await db.commit()
Issue:       Deleting a user (and session expiry, and a password reset) never clears that username's `SessionState`, which holds the UDL username and password, so the state outlives the account and is handed to any later account created with the same name.
Impact:      A recreated or reassigned username inherits the previous holder's live UDL credentials, planning results and caches; a removed operator's UDL password stays in process memory until restart, contradicting planning_state.py:55.
Fix:         Call `clear_session_state(username)` in `delete_user` and whenever the generation is advanced (password change listener, logout); key the store by user id rather than username.
Gate:        Integration test: set UDL credentials on X's state, delete X, assert `planning_state._store` has no entry for X; recreate X and assert `udl_password is None`.
Negative-check:Grep `clear_session_state` in spectre/: only login.py:200, login.py:212 and the definition at planning_state.py:143.

ID:          F-S08-04
Lens:        L9 observability
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/csrf.py:94
Evidence:
    logger.warning("CSRF check failed — method=%s path=%s", request.method, request.url.path)
Issue:       The one unauthenticated log line outside login is not passed through `log_safe`, and the path is percent-decoded by the ASGI server, so `%0a` in a string path parameter (for example `DELETE /assets/blue/{name}`, operator.py:224) writes a forged second record without a CSRF token or a session.
Impact:      Anonymous audit-log forging, the exact class log_safety.py exists to stop.
Fix:         log_safe(request.url.path)` (and the method) in this call.
Gate:        Test: `client.delete("/assets/blue/x%0aFORGED")` with caplog, assert the CSRF warning is one line.
Negative-check:Grep `log_safe` in spectre/web/csrf.py: no matches. TBC, re-verify: run that test to confirm the decoded newline reaches the record under Starlette 1.6.0.

ID:          F-S08-05
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  inference
Location:    spectre/web/routes/admin.py:221-231
Evidence:
    if user.role == "admin" and role != "admin":
    admin_count = await _admin_count(db)
    if admin_count <= 1:
Issue:       The last-admin guard is a read-then-write with no lock or conditional update, so two concurrent demotions (or a demotion racing a delete) each see a count of 2 and both commit; the delete guard at admin.py:274-281 is unreachable except under this race, because self-delete is refused first.
Impact:      Zero admin accounts; recovery needs SPECTRE_ADMIN_RESET and a redeploy.
Fix:         Perform the demotion or delete as a single conditional statement (`UPDATE ... WHERE (SELECT count(*) ... role='admin') > 1`) or take a row lock (`SELECT ... FOR UPDATE`) on admin rows inside the transaction.
Gate:        Concurrency test issuing two simultaneous demotions of two remaining admins, asserting at least one admin remains.
Negative-check:Grep `with_for_update\|FOR UPDATE` in spectre/web: no matches.

ID:          F-S08-06
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/auth.py:39, spectre/web/auth.py:45
Evidence:
    hashed: bytes = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt())
    return bool(bcrypt.checkpw(plaintext.encode(), hashed.encode()))
Issue:       The pinned bcrypt is 5.0.0 (requirements-runtime.txt:81), which raises ValueError for inputs over 72 bytes instead of truncating, and nothing bounds or catches it.
Impact:      A long password at POST /login raises before the limiter is charged (unmetered 500 on an unauthenticated endpoint); a long admin-set password gives a 500; a long SPECTRE_ADMIN_PASS stops the boot in `_bootstrap_admin` (database.py:245).
Fix:         Reject passwords over 72 UTF-8 bytes with a form error at create/update and bootstrap, and treat an over-long login password as a failed attempt (charged to the limiter) without calling bcrypt.
Gate:        Unit test `verify_password("x"*100, h)` path and integration test posting a 100-byte password to /login asserting 401, not 500.
Negative-check:Grep `72.byte\|72 byte\|len\(password\|password\.encode\|maxlength="72"` in *.py and *.html: no matches. TBC, re-verify against the bcrypt 5.0.0 changelog.

ID:          F-S08-07
Lens:        L3 security
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/csrf.py:25
Evidence:
    _EXEMPT_PATHS = frozenset({"/login"})
Issue:       POST /login has no CSRF, Origin or Referer check, so a cross-site page can sign the victim's browser into an attacker-owned account (login CSRF); SameSite=Lax does not stop a cookie being set on a top-level cross-site POST response.
Impact:      Speculation: an operator who does not notice the username then enters UDL credentials and planning inputs into the attacker's session, where they are stored under the attacker's username (planning_state.py:113).
Fix:         Require `Origin` (or `Referer`) to match the host on POST /login, or issue a pre-session CSRF cookie on GET /login and verify it on POST.
Gate:        Integration test: POST /login with `Origin: https://evil.example` asserts 403.
Negative-check:Grep `origin\|referer` (case-insensitive) in spectre/web/csrf.py and routes/login.py: TBC, re-verify; none seen on reading both files in full.

ID:          F-S08-08
Lens:        L3 security
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/login.py:202-212, spectre/web/deps.py:48-49
Evidence:
    cookie = request.cookies.get(_COOKIE_NAME)
    if cookie:
    username = decode_session_cookie(cookie)
Issue:       Logout decodes the cookie without the generation check, and `render` mints a valid CSRF token for whatever cookie is presented (GET /login renders base.html's meta tag), so a holder of a revoked but unexpired token can obtain a token and call /logout repeatedly.
Impact:      The very attacker logout was meant to cut off can keep ending the operator's live sessions for up to 8 hours after the token was issued.
Fix:         In `post_logout`, resolve the user and skip `_revoke_sessions` when `_session_revoked(user, gen)` is true; mint CSRF tokens in `render` only for a cookie that decodes to a current session.
Gate:        Integration test: capture cookie A, log out, log in as B session, replay logout with A and its token, assert B's session still answers 200.
Negative-check:Grep `_session_revoked` in spectre/web/routes/login.py: no matches.

ID:          F-S08-09
Lens:        L2 error handling and failure modes
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/health.py:111-118
Evidence:
    settings = get_settings()
    healthy, detail = await check_storage(settings.data_dir)
Issue:       Readiness probes only the data directory, never the database, so a pod whose PostgreSQL is unreachable reports ready.
Impact:      The platform routes logins to a pod that 500s on every authenticated request; the probe stays green during a database outage.
Fix:         Add a bounded `SELECT 1` through `AsyncSessionLocal` under the same timeout and fold it into the 503 diagnosis.
Gate:        Unit test monkeypatching the engine to raise, asserting /readyz returns 503.
Negative-check:Grep `engine\|AsyncSession\|database` in spectre/web/health.py: no matches.

ID:          F-S08-10
Lens:        L3 security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/config/settings.py:230-238
Evidence:
    elif sslmode and sslmode not in _SSLMODE_NEGOTIATE:
Issue:       Any unrecognised sslmode (a typo such as `verify_full`) falls into the `require` branch and builds a context with `CERT_NONE`, silently downgrading a requested verification to none, and `sslcert`/`sslkey` are dropped without warning.
Impact:      An operator who asked for certificate verification gets an unauthenticated TLS channel to the database, open to interception, with no log line.
Fix:         Treat only `require` as encrypt-without-verify and raise ConfigurationError for any other unknown value; log dropped client-certificate parameters.
Gate:        Unit test: `split_database_url(...?sslmode=verify_full)` raises ConfigurationError.
Negative-check:Grep `"require"` in spectre/config/settings.py: no explicit match; the branch is reached by elimination.

ID:          F-S08-11
Lens:        L5 resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/planning_state.py:51, spectre/web/planning_state.py:108-109
Evidence:
    log_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    with contextlib.suppress(asyncio.QueueFull):
    self.log_queue.put_nowait(message)
Issue:       The queue is unbounded and has no consumer, so every log line a session ever writes is retained, and the `QueueFull` suppression is dead code because an unbounded queue never raises it.
Impact:      Per-session memory grows without limit across a long shift while the docstring claims a 200-entry bound.
Fix:         Remove `log_queue` or give it `maxsize=_MAX_LOG_ENTRIES` and drop the oldest on full.
Gate:        Unit test appending 1000 entries and asserting `log_queue.qsize() <= _MAX_LOG_ENTRIES`.
Negative-check:Grep `log_queue` in spectre/: per ARCHITECTURE.md only planning_state.py:51,108 (no `.get(` consumer).

ID:          F-S08-12
Lens:        L4 contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/auth.py:71
Evidence:
    data = _serializer().loads(token, max_age=_SESSION_MAX_AGE)
Issue:       Session expiry, the only server-side bound on a token not revoked by logout, has no test at any layer.
Impact:      A refactor that drops `max_age` (or changes the constant) turns every session into a permanent one with the suite green.
Fix:         Add a unit test that freezes or patches time beyond 28 800 s and asserts `decode_session_cookie` returns None, and one at 28 799 s that it does not.
Gate:        That test.
Negative-check:Grep `_SESSION_MAX_AGE|max_age|expired|Expired` in tests/: one unrelated hit (test_web_routes.py:172).

ID:          F-S08-13
Lens:        L8 clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/_entrypoint.py:40-44
Evidence:
    # Keycloak single-sign-on gateway in front of the service, not by this bind.
    access_log=False,  # request logging is handled by the application's own audit path
Issue:       Both justifications for the bind and for disabling the access log point at controls that do not exist in the code: there is no request-logging middleware, and nothing in the repository configures or depends on a Keycloak gateway.
Impact:      A reviewer accepts the 0.0.0.0 bind and the missing access log on the strength of two absent controls; requests other than login and admin actions leave no trace.
Fix:         Either add a request-logging middleware (method, path via log_safe, status, user) or re-enable the uvicorn access log; replace the Keycloak sentence with what actually bounds exposure, or cite where the gateway is configured.
Gate:        Test asserting one log record per request; review checklist on security-hotspot justifications.
Negative-check:Grep `middleware` in spectre/: only app.py:327 (security headers). Grep `Keycloak|keycloak`: _entrypoint.py, READINESS.md, audit/ only.

ID:          F-S08-14
Lens:        L4 contracts and data
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_admin_routes.py:178-196, tests/integration/test_admin_routes.py:257-260
Evidence:
    for uid in matches:
    edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
    if b"new_op" in edit_resp.content:
Issue:       Four admin tests (password reset, delete, self-delete, last admin) search in a loop and `break` with no assertion after the loop, so they pass vacuously if the row is absent; `test_cannot_delete_last_admin` tests demotion, not deletion; `test_update_role` posts the role the user already has and asserts only 200; `test_login_is_exempt_so_a_session_can_be_established` asserts only `!= 403` (test_csrf.py:118); test_csrf.py:121-164 duplicates tests/unit/test_auth.py:18-49.
Impact:      The admin authz and last-admin guards look covered while their regressions can pass.
Fix:         Add `else: pytest.fail(...)` (or a `found` flag) to each loop, add a real delete-last-admin case and a real role change asserted by re-reading the row, assert `401` on the exempt-login test, delete the duplicate class.
Gate:        Ruff PT rule set, plus a custom check that a `for ... break` in a test is followed by an assertion.
Negative-check:Grep `found` in tests/integration/test_admin_routes.py: only test_update_role uses one (lines 157, 168, 170).

ID:          F-S08-15
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/login.py:28
Evidence:
    _SESSION_COOKIE_MAX_AGE = 28_800
Issue:       The session lifetime is defined twice (auth.py:22 and here), kept in step only by a comment.
Impact:      Changing one leaves the browser cookie and the server-side expiry disagreeing.
Fix:         Import `_SESSION_MAX_AGE` from auth.py.
Gate:        Test asserting the Set-Cookie Max-Age equals `auth._SESSION_MAX_AGE`.
Negative-check:Grep `28_800` in spectre/: auth.py:22 and login.py:28.

ID:          F-S08-16
Lens:        L7 design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/app_logging/config.py:12, spectre/config/settings.py:325-327
Evidence:
    def configure_logging(run_id: str, log_level: str = "INFO", log_dir: str = "logs") -> None:
    log_dir: str = field(
    default_factory=lambda: os.environ.get("SPECTRE_LOG_DIR", "logs")
Issue:       The structlog configuration with run_id correlation is never called and `Settings.log_dir` is never read, so SPECTRE_LOG_DIR is a dead setting.
Impact:      Operators who set SPECTRE_LOG_DIR expect per-run JSON logs that are never written.
Fix:         Delete the module and the field, or wire `configure_logging` into the planning-run path.
Gate:        Vulture in CI at the current confidence.
Negative-check:Grep `configure_logging|\.log_dir|get_logger\(` in spectre/: only the definitions in app_logging/config.py.

ID:          F-S08-17
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/admin.py:66-67, spectre/web/rate_limit.py:1
Evidence:
    server had already committed the change, so a created, renamed or deleted
    user was invisible until the page was reloaded by hand.
    """In-process sliding-window rate limiters for SPECTRE UDL proxy routes.
Issue:       The admin docstring describes renaming, which no route supports, and the rate_limit module docstring scopes itself to UDL routes while its class also backs both login tiers.
Impact:      Misleads a reader about the admin surface and where the login limiter lives.
Fix:         Drop "renamed"; mention the login tiers in the module docstring.
Gate:        Review.
Negative-check:Grep `rename` in spectre/web/routes/admin.py: only line 66.

ID:          F-S08-18
Lens:        L4 contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/database.py:200
Evidence:
    username = settings.spectre_admin_user.strip()
Issue:       The bootstrap and break-glass paths write SPECTRE_ADMIN_USER to the users table without the `_USERNAME_PATTERN` and 64-character checks that admin.py:126-132 applies, and break-glass silently promotes an existing operator of that name to admin.
Impact:      An environment typo creates an identity the form would refuse, or elevates the wrong account.
Fix:         Validate against the shared pattern at boot and refuse to promote a non-admin without an explicit second flag.
Gate:        Bootstrap test with an invalid name asserting a ConfigurationError.
Negative-check:Grep `_USERNAME_PATTERN` in spectre/: only admin.py:46 and :128.

ID:          F-S08-19
Lens:        L1 correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/log_safety.py:58
Evidence:
    return collapsed[: max(0, limit - len(_ELLIPSIS))] + _ELLIPSIS
Issue:       For `limit` below 3 the result is "..." (3 characters), longer than `limit`, contradicting "never longer than *limit*" (line 48-49).
Impact:      Latent only; every call site uses the default 120.
Fix:         Return `collapsed[:limit]` when `limit <= len(_ELLIPSIS)`.
Gate:        Parametrised test over limit 0-3 asserting `len(result) <= limit`.
Negative-check:Grep `limit=` in tests/unit/test_log_safety.py: TBC, re-verify; tests at lines 67-78 use limits well above 3.

ID:          F-S08-20
Lens:        L8 clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    tests/integration/test_login_hardening.py:271-272
Evidence:
    Every write to ``session_epoch`` goes through ``session_epoch_now``, which
    truncates to whole seconds. That is not tidiness. itsdangerous stamps a
Issue:       The class docstring describes a timestamp epoch design that has been replaced by the generation counter; neither name exists.
Impact:      A reader is told the wrong mechanism for the control under test.
Fix:         Rewrite the docstring around `session_generation`.
Gate:        Review.
Negative-check:Grep `session_epoch` in *.py: only this line.
