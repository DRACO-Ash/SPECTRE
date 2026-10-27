ID:          F-S07-01
Lens:        L3 Security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/planning_state.py:55-57
Evidence:
    # UDL credentials — held in memory for this session only, never persisted.
    udl_username: str | None = None
    udl_password: str | None = None
Issue:       The UDL password is held in plaintext on a SessionState inside the process-global `_store` keyed by SPECTRE username (planning_state.py:113), so its real scope is the process and the user name, not the session: every concurrent browser session of that user drives UDL with it, and it outlives cookie expiry and server-side session revocation because the only clearing sites are SPECTRE logout (login.py:212) and UDL logout (udl.py:384-385).
Impact:      An operator who closes the browser without pressing logout leaves a live UDL credential in memory until the process restarts, and any later session for the same SPECTRE account (another terminal, a stolen cookie inside its 8-hour validity) gets UDL access without the UDL password.
Fix:         Key UDL credentials on the server-side session token, not the username, and clear them when that token expires or is revoked; better still, exchange the Basic credential once for a UDL token and hold only that, with an idle timeout.
Gate:        Integration test: log in twice as one user, connect UDL in session A, assert session B sees no UDL connection; expire A and assert the credential is gone.
Negative-check:clear_session_state|udl_password = None` across spectre/: only routes/login.py:212 and routes/udl.py:385

ID:          F-S07-02
Lens:        L3 Security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:282-297
Evidence:
    udl_user: Annotated[str, Form()] = "",
    udl_pass: Annotated[str, Form()] = "",
    satno, udl_user.strip(), udl_pass.strip(), "REAL",
Issue:       POST /pol/analyse accepts UDL credentials directly in the form (request scope, not stored) and carries no rate-limit dependency, so it is an unthrottled UDL credential oracle that sidesteps the 5-per-minute `udl_auth_rate_limit` on /udl/login (rate_limit.py:120), and each call fires two UDL requests of up to 5,000 elsets with a 120 s timeout.
Impact:      Any logged-in SPECTRE account can brute-force or spray UDL passwords through SPECTRE's egress address, getting the UDL account (or SPECTRE's address) locked out, and can tie up the server with long UDL pulls.
Fix:         Add `Depends(udl_auth_rate_limit)` when `pol_source == "udl_direct"` and `Depends(udl_data_rate_limit)` otherwise, or remove the direct-credential path and require /udl/login.
Gate:        Route-inventory test asserting every handler that calls httpx against _UDL_BASE declares one of the udl_* rate-limit dependencies.
Negative-check:rate_limit` in spectre/web/routes/pol.py and gcat.py: 0 occurrences

ID:          F-S07-03
Lens:        L4 Contracts and data
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.py:121-123
Evidence:
    existing_ids: set[str] = {
    str(r.get("msgId") or r.get("messageId") or "")
    for r in self._data["records"]
Issue:       The cache reads `msgId`, top-level `satNo` (notso_cache.py:149) and `msgText` (pol.py:922), but the 500 real UDL TACREP_NOTSO records in the committed file carry `id`, `msgBody` and `msgBody.SatIds` and none of those three keys (counted: 0/0/0 of 500), so deduplication never fires, `get_for_satno` returns an empty list for every object, and the cache path of /pol/notso-correlate always answers "No NOTSOs in local cache".
Impact:      Correlation from the cache is dead code against live data, and every re-sync of an overlapping window appends duplicates, so counts and correlations are inflated. The unit tests stay green because their fixtures (test_notso_cache.py:54-55) use the invented shape.
Fix:         Key deduplication on `id`; index satellite numbers from `msgBody.SatIds`; build the parse text from `msgBody` fields; rebuild the test fixtures from a redacted real record.
Gate:        Contract test that loads one redacted real record shape and asserts `append` twice adds 1 and `get_for_satno(<SatIds[0]>)` returns it.
Negative-check:python count over notso_cache.json records of keys msgId/messageId, satNo, msgText: 0, 0, 0

ID:          F-S07-04
Lens:        L5 Resource lifecycle and concurrency
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/udl.py:1125-1127
Evidence:
    params: dict[str, str | int] = dict(base_params)
    if page > 0:
    params["offset"] = page * 500
Issue:       The NOTSO sync is an uncapped `while True` (udl.py:1124) whose only exits are an error, an empty page or a page under 500. It pages with an `offset` parameter that the rest of the code base never uses for UDL; if UDL ignores it (my understanding is that UDL pages with `firstResult`, TBC), every page returns the same 500 records.
Impact:      Combined with F-S07-03, where deduplication never matches, each loop iteration appends 500 duplicates and rewrites the whole JSON file. The request never finishes, the file and memory grow without bound, and one operator's credential hammers UDL every 60 s timeout window.
Fix:         Use UDL's documented paging parameter, cap pages (for example 50) and total records, break when a page adds zero new records, and report truncation to the operator.
Gate:        Unit test with a mocked client that returns the same full page forever, asserting the loop ends within the page cap.
Negative-check:firstResult|"offset"` across *.py: only udl.py:1127

ID:          F-S07-05
Lens:        L10 Build, config and deploy
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.json:14-15
Evidence:
    "source": "JCO",
    "classificationMarking": "U//DS-JCO-NOTIF",
Issue:       The repository commits 500 REAL-mode JCO TACREP_NOTSO notifications pulled from UDL (metadata last_sync 2026-04-07, createdAt 2024-01-02 to 2025-11-13, origNetwork OPS1, every record marked U//DS-JCO-NOTIF and naming 92 commercial providers). The file ships in the image through `COPY spectre/ /app/spectre/` (Dockerfile:77; .dockerignore `data/` matches only the root). It is also served to every logged-in SPECTRE operator whether or not they hold a UDL account.
Impact:      Data carrying a UDL dissemination-control marking is redistributed through git history and every container image to people outside the UDL access decision. By contrast the operator's own HRR_List.json is deliberately ignored as "their operational product, not ours to commit" (test_hrr_bootstrap.py:122).
Fix:         Remove the file from the tree and history after a human ruling on the marking, ship an empty cache, and gitignore spectre/data/notso_cache.json.
Gate:        CI check that fails when any tracked JSON contains a `classificationMarking` key, or when notso_cache.json is tracked.
Negative-check:git ls-files spectre/data` lists notso_cache.json; .gitignore anchors only `/data/` (.gitignore:114)

ID:          F-S07-06
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:298-300
Evidence:
    url = urllib.parse.urljoin(url, resp.headers.get("location", ""))
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in _ALLOWED_URL_SCHEMES:
Issue:       The per-hop redirect check enforces scheme only, yet the docstring (gcat.py:288-289) claims it stops a redirect "onto an address inside the cluster". An https redirect to any host, internal ones included, is followed, and its body is parsed and shown to the operator.
Impact:      If planet4589.org or the DNS path to it is compromised, a 302 to an https service inside the cluster turns the GCAT panel into an SSRF read primitive. The test that names the metadata service (test_outbound_and_ddl_guards.py:171) passes only because it uses http.
Fix:         Pin each hop's host to planet4589.org (or an allowlist) and refuse private, loopback and link-local resolved addresses.
Gate:        Parametrised test adding `https://169.254.169.254/` and `https://10.0.0.1/` as redirect targets, asserting they are refused.
Negative-check:host|netloc|hostname` in gcat.py `_get_rechecking_every_hop`: no host check present

ID:          F-S07-07
Lens:        L3 Security
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:472-474
Evidence:
    mask = (
    df.apply(lambda col: col.astype(str).str.lower().str.contains(qlo, na=False))
    .any(axis=1)
Issue:       The operator's search string goes to pandas `str.contains`, whose default is `regex=True`, and runs synchronously on the event loop across every column of datasets with tens of thousands of rows.
Impact:      q=(` raises re.error and returns a 500, and a catastrophic-backtracking pattern stalls the single worker, freezing every operator's console. The path is untested (pytest.txt:110 misses 463-500).
Fix:         Pass `regex=False`, cap `q` length, and run `_page_data` in the executor.
Gate:        Unit test calling `_page_data` with `q="("` and `q="(a+)+$"` on a cached frame, asserting no exception and a bounded run time.
Negative-check:regex=` in gcat.py: no match

ID:          F-S07-08
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:609-611
Evidence:
    _CACHE.clear()
    _CACHE_FETCH_TIME = None
    await _load_all()
Issue:       Any logged-in operator can clear the cache shared by every operator and start 28 downloads, with no role check and no rate limit. The clear runs before the `_FETCHING` guard (gcat.py:383-385), so a second refresh during a first wipes what is loading and returns an empty panel. `_FETCHING` is reset without try/finally (gcat.py:421), and on-demand loads (gcat.py:563-568) have no single-flight, so N concurrent first views download the same dataset N times.
Impact:      One operator can repeatedly blank GCAT for everyone and hammer a third-party personal site from SPECTRE's address. A cancelled refresh leaves `_FETCHING` True and blocks refresh until the process restarts.
Fix:         Restrict refresh to admin, rate-limit it, check `_FETCHING` before clearing, swap in the new cache atomically, use try/finally, and put a per-key lock on the on-demand path.
Gate:        Async test running two concurrent refreshes, asserting the cache ends full and `_FETCHING` ends False.
Negative-check:require_admin|rate_limit` in gcat.py: no match

ID:          F-S07-09
Lens:        L4 Contracts and data
Severity:    High
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/udl.py:427
Evidence:
    params: dict[str, Any] = {"satNo": satno, "epoch": f"<{epoch_filter}", "maxResults": 10}
Issue:       Epoch mode asks UDL for 10 elsets before scenario start with no sort order, then picks the closest of those 10. If UDL returns oldest first or in no particular order (TBC against the UDL /elset query semantics), the 10 can come from decades before the scenario, and the "closest" is wrong.
Impact:      The operator gets a TLE years older than the best available one. The STALE badge (tle_fields.html:9) flags it, but the form is still filled and the TLE drives planning.
Fix:         Bound the window on both sides (`epoch=<start` together with a lower bound such as start minus 7 days, using UDL's range syntax), or request descending epoch order, and fetch enough to cover multiple providers.
Gate:        Contract test against a recorded UDL response for a long-lived object, asserting the chosen epoch is within 7 days of scenario start.
Negative-check:sort|orderBy` in UDL params across spectre/: no match

ID:          F-S07-10
Lens:        L4 Contracts and data
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/udl.py:724-725
Evidence:
    params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z",
    "dataMode": dm, "maxResults": 1},
Issue:       The docstring promises the state vector "at the most recent available epoch" (udl.py:704), but the query asks for any one record after 2020 with no ordering. `rec = data[0]` (udl.py:760) raises KeyError if UDL answers with a bare object, which the same module says it does elsewhere (udl.py:443-444). The frame silently defaults to "J2000" when absent (udl.py:770).
Impact:      An operator can start intercept geometry from a state vector years old, presented as the latest, or get an unhandled 500.
Fix:         Bound the epoch to a recent window and select the newest client-side as `_select_latest_elset` does; normalise the payload with `_normalise_elset_records`; refuse when referenceFrame is absent.
Gate:        Unit tests for dict payloads and for unordered multi-record payloads.
Negative-check:fetch_statevector` in tests: no match

ID:          F-S07-11
Lens:        L2 Error handling and failure modes
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:541-543
Evidence:
    line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
    line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
    return name, f"{line1}\n{line2}", line1
Issue:       In latest mode, when no record carries a parsable line 1, `_select_latest_elset` falls back to `records[0]` (udl.py:517), `_extract_tle_fields` does not check for empty lines, and fetch_tle renders `error: None` with `tle` set to "\n" and a "TLE loaded" success line. Diagnostics read a `tle1` key (udl.py:478) that extraction ignores.
Impact:      The operator is told a TLE loaded when the form holds nothing usable, and the failure surfaces later and somewhere else.
Fix:         Return an error from fetch_tle when line1 or line2 is empty, and read the same key set in diagnostics and extraction.
Gate:        Unit test: a record with only `tle1`/`tle2` keys yields a non-None error.
Negative-check:if not line1` in udl.py fetch_tle path (561-688): no match

ID:          F-S07-12
Lens:        L3 Security
Severity:    Medium
Confidence:  Medium
Epistemics:  fact
Location:    spectre/web/routes/udl.py:1177-1179
Evidence:
    error_html = "".join(f'<p style="margin:0.1rem 0">{e}</p>' for e in errors)
    return _HTMLResponse(
    f'<div class="callout callout-red" style="font-size:0.72rem">{error_html}</div>'
Issue:       The sync response is built by f-string with exception text (`{exc}` at udl.py:1145,1167) inserted without html.escape, bypassing the Jinja autoescaping every other route relies on (app.py:49).
Impact:      Today the exception strings carry server-built URLs and library messages (inference), so exploitation needs attacker influence over an httpx or JSON error message. Any future error that includes response content becomes stored-free reflected XSS in the console.
Fix:         Render a template, or html.escape each entry.
Gate:        Ruff/semgrep rule forbidding f-string HTMLResponse bodies that interpolate a variable not wrapped in html.escape.
Negative-check:html.escape` in udl.py: no match

ID:          F-S07-13
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/data/notso_cache.py:93-94
Evidence:
    with open(self._path, "w", encoding="utf-8") as fh:
    json.dump(self._data, fh, indent=2, ensure_ascii=False)
Issue:       Every sync page truncates and rewrites the whole (8.6 MB) JSON file in place, synchronously on the event loop, with no temp-file-and-rename. A crash mid-write leaves a corrupt file that `_load` silently replaces with an empty cache (notso_cache.py:82-86), after which the next sync re-pulls from 2024-01-01. The file sits inside the package directory, which in the image is ephemeral (/app/spectre/data).
Impact:      Data loss on a crash or disk-full, a stalled event loop during each page write, and a cache that disappears on every pod restart.
Fix:         Write to a temp file in the configured data directory and `os.replace` it; run the write in a thread; move the path under SPECTRE_DATA_DIR or STORAGE_MOUNT_PATH; keep the corrupt file aside instead of silently resetting.
Gate:        Unit test that simulates an exception mid-dump and asserts the previous file survives.
Negative-check:os.replace|tempfile|rename` in notso_cache.py: no match

ID:          F-S07-14
Lens:        L3 Security
Severity:    High
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:981-982
Evidence:
    catalog = get_onorbit_catalog()
    status = get_catalog_status()
Issue:       /udl/catalog/search and the cache path of /pol/notso-correlate (pol.py:1035-1036) serve UDL-derived data fetched with one operator's credential to any logged-in operator, and check neither that operator's UDL session nor their UDL entitlement.
Impact:      A SPECTRE account with no UDL access can browse the UDL on-orbit catalogue and REAL-mode JCO notifications, so UDL's own access decision is bypassed (the entitlement consequence is inference; the mechanism is fact).
Fix:         Require an active UDL session for both routes at minimum; preferably cache per UDL identity, or re-validate entitlement per request.
Gate:        Integration test: operator B without UDL login gets an error from /udl/catalog/search after operator A has populated the catalogue.
Negative-check:udl_username` in search_catalog (udl.py:969-1004): no match

ID:          F-S07-15
Lens:        L5 Resource lifecycle and concurrency
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:316-317
Evidence:
    asyncio.create_task(_fetch_onorbit_background(username, password))
    asyncio.create_task(_discover_tle_sources(username, password, state))
Issue:       The task handles are discarded, so the event loop holds only a weak reference and a task can be collected before it finishes (Python asyncio documentation). The "ready" guard (udl.py:197-199) does not cover "loading", so concurrent logins duplicate the 60 s catalogue pull. Once "ready", the catalogue is never refreshed for the life of the process. The tasks keep using the password after the operator presses UDL logout.
Impact:      Silent catalogue load failure stuck at "loading", duplicate full-catalogue pulls, a catalogue that goes stale indefinitely, and credential use after logout.
Fix:         Keep task references in a module set with a done-callback, add a single-flight lock, add a TTL refresh, and cancel session-bound tasks on UDL logout.
Gate:        Unit test that two logins in quick succession produce one /onorbit request.
Negative-check:add_done_callback|_background_tasks` in udl.py: no match

ID:          F-S07-16
Lens:        L4 Contracts and data
Severity:    Medium
Confidence:  Medium
Epistemics:  inference
Location:    spectre/web/routes/pol.py:114-116
Evidence:
    params: dict[str, Any] = {
    "satNo": satno,
    "epoch": ">2015-01-01T00:00:00.000000Z",
Issue:       The history pull is a single request capped at 5,000 records (pol.py:35,117), with no paging and no check of whether the cap was hit. The current elset is then appended, so a long-lived object whose archive is truncated gets a silent gap between the 5,000th elset and today.
Impact:      Manoeuvres inside the gap are never detected, and the PoL verdict and cumulative delta-v are presented as covering 2015 to now when they do not. The gap may only show as `skipped_long_gap` in the detection audit.
Fix:         Page until exhausted (with a cap), or detect `len(records) == _UDL_MAX_RESULTS` and show "history truncated at <epoch>" in the results panel.
Gate:        Unit test: a mocked 5,000-record response produces a visible truncation flag in the view context.
Negative-check:_UDL_MAX_RESULTS` usages: pol.py:35,117 only, no comparison against the result count

ID:          F-S07-17
Lens:        L7 Design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:289-290
Evidence:
    resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
Issue:       Every non-2xx response has already returned at udl.py:278, so the `raise_for_status` and the HTTPStatusError handler (udl.py:290-297) are dead code.
Impact:      Misleading error handling. A maintainer may believe that path is live and tested.
Fix:         Delete the dead branch.
Gate:        Coverage gate on routes/udl.py login lines.
Negative-check:n/a

ID:          F-S07-18
Lens:        L3 Security
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/templates/partials/pol_panel.html:70
Evidence:
    <input type="password" name="udl_pass" autocomplete="current-password" placeholder="UDL password" />
Issue:       The PoL direct-credential field invites the browser to save the UDL password, which contradicts `autocomplete="off"` on the main UDL form (udl_status.html:12). The route also `.strip()`s the password (pol.py:297), which alters a credential that has leading or trailing spaces.
Impact:      The UDL password is stored in browser profiles on shared operations-room terminals.
Fix:         Use `autocomplete="off"` (or `new-password`) and do not strip passwords.
Gate:        Template lint asserting every password input named for UDL carries autocomplete="off".
Negative-check:n/a

ID:          F-S07-19
Lens:        L6 Performance and complexity
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:797-800
Evidence:
    n_samples=min(max(n_samples, 50), 2000),
    archetype_override=manoeuvre_type,
    )
Issue:       /pol/monte-carlo clamps samples but leaves `horizon_h` (pol.py:762,800) unbounded, runs in the shared default executor, and has no rate limit. /pol/photometry-analyse parses an unbounded CSV on the event loop.
Impact:      One operator can queue arbitrarily long propagations and starve the executor that other features use.
Fix:         Bound horizon_h (for example to 720 h), cap the CSV size, and add a per-operator compute rate limit.
Gate:        Form-validation test rejecting horizon_h above the cap.
Negative-check:horizon_h` bounds in pol.py: none (`le=` absent)

ID:          F-S07-20
Lens:        L8 Clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    spectre/data/intel.py:4-5
Evidence:
    keyed by NORAD catalogue number.  Data sourced from the Adversary Satellite
    Activity Report (UNCLASSIFIED // PAIR, 30 March 2026).
Issue:       The docstring attributes the whole dataset to one PAIR report, but the records cite open sources (McDowell 2025, CSIS 2025, SWF 2025, RAND 2025) and one "Iran Space OOB (PAIR/PatchPlus Feb 2026)" source (adversary_intel.json:350). The JSON itself carries no marking, and the threat_level values (CRITICAL/HIGH/MEDIUM/LOW) have no stated method.
Impact:      Operators see these records as "pair" in PoL results (pol.py:192,366) with an authority and handling status the data does not state.
Fix:         Record the actual per-record provenance and handling marking in the file header, and label threat_level as an analyst judgement in the template.
Gate:        Test asserting every record has a non-empty `source` and that the file carries a top-level marking and provenance field.
Negative-check:classification regex over adversary_intel.json: no match

ID:          F-S07-21
Lens:        L7 Design and structure
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:1027
Evidence:
    _UDL_BASE = "https://unifieddatalibrary.com/udl"
Issue:       The UDL base URL is defined three times (udl.py:55, udl.py:1027 shadowing the module constant, pol.py:32), with no configuration for test or alternative UDL instances.
Impact:      A base-URL change made in one place leaves the other routes talking to the old host.
Fix:         Define it once in settings and import it.
Gate:        Grep check in CI for the literal outside settings.
Negative-check:unifieddatalibrary\.com` in spectre/: 3 matches (listed)

ID:          F-S07-22
Lens:        L8 Clarity and comments
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/pol.py:108-111
Evidence:
    ) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    Returns ``(tle_text, metadata, rms_metadata)``.
Issue:       The docstring says three elements are returned. The signature and `_parse_udl_elset_response` return four, with sat_name as the fourth.
Impact:      Misleading contract for the next caller.
Fix:         Correct the docstring.
Gate:        Docstring-signature check (pydoclint) in CI.
Negative-check:n/a

ID:          F-S07-23
Lens:        L4 Contracts and data
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/gcat.py:476
Evidence:
    df = df[mask]
Issue:       pyright reports `Series | Unknown | Self@DataFrame` is not assignable to DataFrame here (audit/tools-raw/pyright.txt:16), and `intel.py:23` returns an Optional where a dict is declared (pyright.txt:12). Both are type-only at runtime. In addition, gcat responses have no size cap (`resp.content`, gcat.py:341) and `_page_data` copies the whole frame on every request (gcat.py:467).
Impact:      Type checking is red for these files, and memory use per table request scales with dataset size.
Fix:         Use `df = df.loc[mask]` with a typed mask; return a narrowed value in intel._load; cap the download size; filter without `.copy()`.
Gate:        pyright in CI on spectre/web/routes and spectre/data.
Negative-check:n/a

ID:          F-S07-24
Lens:        L1 Correctness and edge cases
Severity:    Low
Confidence:  High
Epistemics:  fact
Location:    spectre/web/routes/udl.py:800-804
Evidence:
    raw = str(rec.get("createdAt") or "").strip().replace("Z", "+00:00")
    try:
    return datetime.fromisoformat(raw)
Issue:       A createdAt without an offset parses to a naive datetime. `max(..., key=_parse_created_at)` (udl.py:857) then compares naive with aware values and raises TypeError, which /udl/hrr does not catch. Separately, `_parse_tle_epoch` accepts a day-of-year of 0 or above 366 without complaint (udl.py:49-51).
Impact:      One malformed notification turns the HRR panel into a 500, and a corrupt epoch field becomes a plausible-looking date.
Fix:         Attach UTC when tzinfo is None; reject a day-of-year outside 1 to 366.
Gate:        Unit tests for both inputs.
Negative-check:n/a

ID:          F-S07-25
Lens:        L3 Security
Severity:    Low
Confidence:  Medium
Epistemics:  fact
Location:    spectre/web/templates/partials/catalog_results.html:31
Evidence:
    hx-vals='{"satno": {{ obj.satno }}}'
Issue:       A UDL-sourced satno is placed raw into a JSON attribute (also hrr_panel.html:55,63,106,114 for `sat.satno`). Autoescaping stops an attribute break-out, but not JSON injection or invalid JSON (the fallback value is "—", udl.py:992).
Impact:      A catalogue entry without a satno yields a broken button. A crafted upstream value could add keys to the htmx request.
Fix:         Use `{{ obj.satno | tojson }}`.
Gate:        Template lint: every `hx-vals` interpolation goes through tojson.
Negative-check:n/a

ID:          F-S07-26
Lens:        L8 Clarity and comments
Severity:    Medium
Confidence:  High
Epistemics:  fact
Location:    tests/unit/test_udl_tle_fetch.py:43-45
Evidence:
    def test_two_digit_year_post_2000(self) -> None:
    # Year "99" → 1999 (< 57 threshold)
    line = "1 25544U 98067A   99001.00000000  .00000000  00000-0  00000-0 0  9999 0"
Issue:       The test name and comment contradict what it asserts (99 is not below 57 and maps to 1999). Its sibling `test_two_digit_year_pre_2000` (:50) tests 57 to 1957, and no test pins 56 to 2056 or 00 to 2000. Separately, test_notso_cache.py:145 asserts only `added >= 0`, which cannot fail.
Impact:      The pivot boundary on the 20xx side is unpinned, and one cache test proves nothing.
Fix:         Rename the tests; add cases for 00, 56 and 57; replace the vacuous assertion with the intended behaviour.
Gate:        A ruff/pytest plugin flagging tautological assertions (`>= 0` on a count).
Negative-check:56001\|00001\.` in test_udl_tle_fetch.py: no match
