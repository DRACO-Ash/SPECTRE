| Path:line | Kind | Justification (heuristic) | Note | Fragment |
|---|---|---|---|---|
| `scripts/cognitive_complexity.py:354` | noqa | comment above: the moment of upload. That is exactly how this was found. | suppresses rule(s) not enabled: S603 | `merge_base = subprocess.run(  # noqa: S603` |
| `scripts/cognitive_complexity.py:360` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `scripts/cognitive_complexity.py:390` | noqa | comment above: be scored by nothing. The whole of a new file is new code. | suppresses rule(s) not enabled: S603 | `status = subprocess.run(  # noqa: S603` |
| `scripts/cognitive_complexity.py:457` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `scripts/smoke-browser.py:124` | noqa | NONE | suppresses rule(s) not enabled: S603 | `self._proc = subprocess.Popen(  # noqa: S603` |
| `scripts/smoke-browser.py:140` | noqa | NONE | suppresses rule(s) not enabled: S310 | `with urllib.request.urlopen(f"{self.base_url}/login", timeout=2):  # noqa: S310` |
| `scripts/smoke-browser.py:164` | type-ignore | NONE |  | `page.on("console", self._on_console)  # type: ignore[attr-defined]` |
| `scripts/smoke-browser.py:165` | type-ignore | NONE |  | `page.on("pageerror", lambda exc: self.fatal.append(f"uncaught exception: {exc}"))  # type: ignore[attr-defined` |
| `scripts/smoke-browser.py:168` | type-ignore | NONE |  | `if message.type != "error":  # type: ignore[attr-defined]` |
| `scripts/smoke-browser.py:170` | type-ignore | NONE |  | `text = str(message.text)  # type: ignore[attr-defined]` |
| `scripts/smoke-browser.py:193` | type-ignore | NONE |  | `browser = await pw.chromium.launch(**launch)  # type: ignore[arg-type]` |
| `scripts/smoke-browser.py:369` | noqa | NONE |  | `import playwright  # noqa: F401` |
| `scripts/sonar_scope.py:26` | noqa | NONE | suppresses rule(s) not enabled: S603 | `return subprocess.run(  # noqa: S603` |
| `scripts/sonar_scope.py:27` | noqa | NONE | suppresses rule(s) not enabled: S607 | `["git", *args],  # noqa: S607` |
| `scripts/verify-db-resilience.py:12` | noqa | inline: register the User table |  | `import spectre.web.models  # noqa: F401  register the User table` |
| `spectre/astro/dv_estimation.py:462` | noqa | comment above: BLE001: any parse failure falls back to the closed form. | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/astro/dv_estimation.py:782` | noqa | comment above: BLE001: a malformed element set is reportable. | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/astro/dv_estimation.py:798` | noqa | comment above: BLE001: SGP4 can diverge; that sample is simply unusable. | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/astro/dv_estimation.py:868` | noqa | comment above: BLE001: any propagation failure is reportable. | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/astro/notso.py:596` | noqa | comment above: site passes all six by keyword already. | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def extract_behaviour_profile(  # noqa: PLR0913, PLR0917` |
| `spectre/astro/pattern_of_life.py:760` | noqa | NONE | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/astro/photometry.py:263` | type-ignore | comment above: Covariance: residual variance × (X^T X)^{-1}  (approximated  |  | `residuals = [mags[i] - _eval_quadratic(tuple(coeffs), phases[i]) for i in range(n)]  # type: ignore[arg-type]` |
| `spectre/astro/tactical.py:1718` | type-ignore | comment above: Select primary |  | `primary = max(probs, key=probs.get)  # type: ignore[arg-type]` |
| `spectre/config/settings.py:395` | no-cover | inline: — defensive |  | `except OSError as exc:  # pragma: no cover — defensive` |
| `spectre/domain/pol_assessment.py:289` | noqa | comment above: positionally. | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def _classify(delta_v_m_s: float, channel: str, regime: str,  # noqa: PLR0913, PLR0917` |
| `spectre/web/_entrypoint.py:15` | other | comment above: one bind and nothing else. Why the bind is correct is record |  | `# ruff: noqa: S104` |
| `spectre/web/_entrypoint.py:41` | nosec | comment above: Keycloak single-sign-on gateway in front of the service, not |  | `host="0.0.0.0",  # nosec B104` |
| `spectre/web/database.py:92` | noqa | comment above: what puts the training tables on Base.metadata before create |  | `import spectre.training.models  # noqa: F401` |
| `spectre/web/deps.py:25` | noqa | NONE | suppresses rule(s) not enabled: PLC0415 | `from spectre.web.app import templates  # noqa: PLC0415` |
| `spectre/web/deps.py:43` | noqa | NONE | suppresses rule(s) not enabled: PLC0415 | `from spectre.web.csrf import make_csrf_token  # noqa: PLC0415` |
| `spectre/web/planning_state.py:210` | noqa | comment above: reader has to work out, which is a loss, not an improvement. | suppresses rule(s) not enabled: PLW0603 | `global _default_hrr_tles, _default_hrr_tle_modes  # noqa: PLW0603` |
| `spectre/web/routes/geometry.py:57` | type-ignore | NONE |  | `for a in state.blue_assets:  # type: ignore[attr-defined]` |
| `spectre/web/routes/geometry.py:60` | type-ignore | NONE |  | `for t in state.red_tracks:  # type: ignore[attr-defined]` |
| `spectre/web/routes/login.py:199` | noqa | NONE | suppresses rule(s) not enabled: PLC0415 | `from spectre.web.auth import decode_session_cookie  # noqa: PLC0415` |
| `spectre/web/routes/login.py:200` | noqa | NONE | suppresses rule(s) not enabled: PLC0415 | `from spectre.web.planning_state import clear_session_state  # noqa: PLC0415` |
| `spectre/web/routes/maneuver.py:873` | noqa | comment above: BLE001: any solver failure is reported to the operator, not  | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/web/routes/maneuver.py:1010` | noqa | comment above: BLE001: any solver failure is reported per method, not raise | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/web/routes/maneuver.py:1196` | type-ignore | NONE |  | `for a in state.blue_assets:  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1199` | type-ignore | NONE |  | `for t in state.red_tracks:  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1216` | type-ignore | NONE |  | `if not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1227` | type-ignore | NONE |  | `state.udl_username,  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1228` | type-ignore | NONE |  | `state.udl_password,  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1502` | type-ignore | NONE |  | `event_type=_EVENT_TYPE_TO_BURN_LOCATION[ev.event_type],  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1503` | type-ignore | NONE |  | `epoch=ev.epoch,  # type: ignore[attr-defined]` |
| `spectre/web/routes/maneuver.py:1504` | type-ignore | NONE |  | `label=ev.label,  # type: ignore[attr-defined]` |
| `spectre/web/routes/pol.py:353` | type-ignore | NONE |  | `state.last_pol_analysis = pol  # type: ignore[attr-defined]` |
| `spectre/web/routes/pol.py:683` | type-ignore | NONE |  | `state.pol_reserve_resets = resets  # type: ignore[attr-defined]` |
| `spectre/web/routes/pol.py:756` | noqa | comment above: PLR0913, PLR0917: FastAPI form parameters. | suppresses rule(s) not enabled: PLR0913,PLR0917 | `async def pol_monte_carlo(  # noqa: PLR0913, PLR0917` |
| `spectre/web/routes/pol.py:800` | type-ignore | NONE |  | `hypothesis.prediction_horizon_hours = horizon_h  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:162` | type-ignore | NONE |  | `for track in state.red_tracks:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:192` | type-ignore | NONE |  | `for obj in state.hrr_objects:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:215` | type-ignore | NONE |  | `for obj in state.hrr_objects:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:331` | type-ignore | NONE |  | `if not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:335` | type-ignore | NONE |  | `int(satno_str), state.udl_username, state.udl_password,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:336` | type-ignore | NONE |  | `data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:337` | type-ignore | NONE |  | `source=state.udl_tle_source,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:342` | type-ignore | NONE |  | `state.hrr_tle_cache[satno_str] = tle  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:343` | type-ignore | NONE |  | `state.hrr_tle_data_mode[satno_str] = dm  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:346` | type-ignore | NONE |  | `int(satno_str), state.udl_username, state.udl_password,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:348` | type-ignore | NONE |  | `data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:349` | type-ignore | NONE |  | `source=state.udl_tle_source,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:352` | type-ignore | NONE |  | `state.hrr_tle_multiset[satno_str] = history  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:451` | type-ignore | NONE |  | `if satno not in state.hrr_tle_cache:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:453` | type-ignore | NONE |  | `mode = state.hrr_tle_data_mode.get(satno, "REAL")  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:474` | type-ignore | NONE |  | `raw_objects = list(state.hrr_objects)  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:496` | type-ignore | NONE |  | `for a in state.blue_assets:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:499` | type-ignore | NONE |  | `for t in state.red_tracks:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:519` | noqa | comment above: PLR0913, PLR0917: one parameter per column of the row it bui | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def _sol_to_entry(  # noqa: PLR0913, PLR0917` |
| `spectre/web/routes/threat.py:681` | noqa | comment above: BLE001: one refusal is recorded and the sweep continues. | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:934` | type-ignore | NONE |  | `cached = state.hrr_tle_cache.get(str(satno).strip())  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:943` | noqa | comment above: BLE001: a malformed element set must not kill the screen. | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:956` | type-ignore | NONE |  | `for obj in state.hrr_objects:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:977` | noqa | comment above: PLR0913, PLR0917: the inputs of one actor's assessment. | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def _screen_one_actor(  # noqa: PLR0913, PLR0917` |
| `spectre/web/routes/threat.py:1082` | noqa | comment above: BLE001: operator input, reported not raised. | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:1098` | type-ignore | NONE |  | `for manual in state.manual_sweep_tles:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1127` | type-ignore | NONE |  | `if not missing or not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1133` | type-ignore | NONE |  | `udl_user: str = state.udl_username  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1134` | type-ignore | NONE |  | `udl_pass: str = state.udl_password  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1140` | type-ignore | NONE |  | `data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1141` | type-ignore | NONE |  | `source=state.udl_tle_source,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1145` | type-ignore | NONE |  | `state.hrr_tle_cache[t.target_satno] = tle  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1146` | type-ignore | NONE |  | `state.hrr_tle_data_mode[t.target_satno] = dm  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1167` | type-ignore | NONE |  | `if not state.hrr_tle_multiset:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1173` | type-ignore | NONE |  | `state.hrr_tle_multiset,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1174` | type-ignore | NONE |  | `state.hrr_tle_cache,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1177` | type-ignore | NONE |  | `state.hrr_tle_cache.update(reduced)  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1179` | noqa | comment above: BLE001: clustering is an optimisation, never a gate. | suppresses rule(s) not enabled: BLE001 | `except Exception as _cl_exc:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:1185` | noqa | comment above: PLR0913, PLR0917: the inputs of one pass over the sweep's ta | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def _run_target_sweep(  # noqa: PLR0913, PLR0917` |
| `spectre/web/routes/threat.py:1211` | type-ignore | NONE |  | `tle = state.hrr_tle_cache.get(target.target_satno)  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1219` | noqa | comment above: BLE001: one bad element set, not the whole sweep. | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:1255` | type-ignore | NONE |  | `g["data_mode"] = state.hrr_tle_data_mode.get(satno, "REAL") if satno else "REAL"  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1342` | noqa | comment above: BLE001: a malformed element set must not kill the sweep. | suppresses rule(s) not enabled: BLE001 | `except Exception:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:1418` | type-ignore | NONE |  | `if not missing or not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1424` | type-ignore | NONE |  | `user: str = state.udl_username  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1425` | type-ignore | NONE |  | `password: str = state.udl_password  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1431` | type-ignore | NONE |  | `data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1432` | type-ignore | NONE |  | `source=state.udl_tle_source,  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1436` | type-ignore | NONE |  | `state.hrr_tle_cache[actor.actor_satno] = tle  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1437` | type-ignore | NONE |  | `state.hrr_tle_data_mode[actor.actor_satno] = mode  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1453` | noqa | comment above: PLR0913, PLR0917: the inputs of one screening pass. | suppresses rule(s) not enabled: PLR0913,PLR0917 | `def _screen_all_actors(  # noqa: PLR0913, PLR0917` |
| `spectre/web/routes/threat.py:1526` | type-ignore | NONE |  | `if not state.hrr_objects:  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1532` | type-ignore | NONE |  | `hrr_objects = state.hrr_objects  # type: ignore[attr-defined]` |
| `spectre/web/routes/threat.py:1578` | noqa | comment above: BLE001: operator input, reported not raised. | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:  # noqa: BLE001` |
| `spectre/web/routes/threat.py:1600` | type-ignore | NONE |  | `for o in state.hrr_objects  # type: ignore[attr-defined]` |
| `spectre/web/routes/training.py:253` | noqa | NONE |  | `ChallengeResult.scored == True,  # noqa: E712` |
| `spectre/web/routes/training.py:350` | noqa | NONE |  | `ChallengeResult.scored == True,  # noqa: E712` |
| `spectre/web/routes/udl.py:426` | type-ignore | NONE |  | `epoch_filter = state.scenario_start.strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # type: ignore[union-attr]` |
| `spectre/web/routes/udl.py:603` | type-ignore | comment above: than in this frame, so mypy cannot see it here. |  | `auth=(state.udl_username, state.udl_password),  # type: ignore[arg-type]` |
| `spectre/web/routes/udl.py:649` | type-ignore | comment above: Pick the record whose TLE epoch is closest to (and ≤) scenar |  | `rec = _select_elset_by_epoch(records, state.scenario_start)  # type: ignore[arg-type]` |
| `spectre/web/routes/udl.py:655` | type-ignore | NONE |  | `f"{state.scenario_start.strftime('%Y-%m-%d %H:%M UTC')}."  # type: ignore[union-attr]` |
| `tests/integration/conftest.py:50` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as c:  # type: ignore[arg-type]` |
| `tests/integration/conftest.py:56` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:38` | noqa | NONE |  | `import spectre.web.models  # noqa: F401` |
| `tests/integration/test_admin_bootstrap.py:50` | type-ignore | NONE |  | `async with db.AsyncSessionLocal() as session:  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:62` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:65` | type-ignore | NONE |  | `assert [u.username for u in users] == ["operator1"]  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:75` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:87` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:98` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:102` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:114` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:117` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:119` | type-ignore | NONE |  | `assert verify_password("first-password", user.hashed_password)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:131` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:136` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:140` | type-ignore | NONE |  | `user = next(u for u in await _users(clean_db) if u.username == "operator1")  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:141` | type-ignore | NONE |  | `assert verify_password("recovered-password", user.hashed_password)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:150` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:155` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:157` | type-ignore | NONE |  | `assert verify_password("first-password", user.hashed_password)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:167` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:172` | type-ignore | NONE |  | `await clean_db._bootstrap_admin()  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:174` | type-ignore | NONE |  | `user = next(u for u in await _users(clean_db) if u.username == "rescue-admin")  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:175` | type-ignore | NONE |  | `assert user.role == "admin"  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_bootstrap.py:176` | type-ignore | NONE |  | `assert verify_password("rescue-password", user.hashed_password)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:8` | type-ignore | NONE |  | `def _admin_session(client: object) -> dict[str, str]:  # type: ignore[type-arg]` |
| `tests/integration/test_admin_routes.py:10` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:19` | type-ignore | NONE |  | `def _operator_session(client: object, username: str, password: str) -> dict[str, str]:  # type: ignore[type-ar` |
| `tests/integration/test_admin_routes.py:21` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:32` | type-ignore | NONE |  | `resp = client.get("/admin/users", follow_redirects=False)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:40` | type-ignore | comment above: Create an operator account first |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:47` | type-ignore | NONE |  | `resp = client.get("/admin/users", cookies=op_cookies, follow_redirects=False)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:52` | type-ignore | NONE |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:61` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:72` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:83` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:94` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:105` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:120` | type-ignore | comment above: Fetch user id for new_op |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:130` | type-ignore | comment above: Get the list page to find a user id in the content |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:138` | type-ignore | NONE |  | `cancel_resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:148` | type-ignore | comment above: Find new_op's row id |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:159` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:161` | type-ignore | NONE |  | `update_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:175` | type-ignore | NONE |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:179` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:181` | type-ignore | NONE |  | `reset_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:190` | type-ignore | comment above: Verify new password works |  | `login_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:204` | type-ignore | comment above: Create a throwaway user |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:210` | type-ignore | NONE |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:214` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:216` | type-ignore | NONE |  | `del_resp = client.delete(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:228` | type-ignore | NONE |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:232` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:234` | type-ignore | NONE |  | `del_resp = client.delete(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:245` | type-ignore | comment above: Delete second_admin first so testadmin is the only admin |  | `resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:250` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:255` | type-ignore | NONE |  | `client.delete(f"/admin/users/{second_admin_id}", cookies=cookies, headers=csrf_headers(cookies))  # type: igno` |
| `tests/integration/test_admin_routes.py:261` | type-ignore | comment above: by checking that after second_admin is gone, demoting testad |  | `resp2 = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:264` | type-ignore | NONE |  | `edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:267` | type-ignore | comment above: Try to demote to operator — last admin guard |  | `demote_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:309` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:321` | type-ignore | NONE |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:326` | type-ignore | NONE |  | `listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:331` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:342` | type-ignore | NONE |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:347` | type-ignore | NONE |  | `listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_admin_routes.py:351` | type-ignore | NONE |  | `resp = client.request(  # type: ignore[attr-defined]` |
| `tests/integration/test_audit_log_integrity.py:53` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_audit_log_integrity.py:73` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_audit_log_integrity.py:86` | type-ignore | comment above: is a standing liability for every sink, not only the ones fi |  | `listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]` |
| `tests/integration/test_audit_log_integrity.py:94` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_audit_log_integrity.py:106` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_packager_gates.py:63` | noqa | comment above: S603: fixed argv, no shell, and every path is test-controlle | suppresses rule(s) not enabled: S603 | `listing = subprocess.run(  # noqa: S603` |
| `tests/integration/test_packager_gates.py:79` | noqa | NONE | suppresses rule(s) not enabled: S603 | `subprocess.run(command, cwd=destination, check=True, capture_output=True)  # noqa: S603` |
| `tests/integration/test_packager_gates.py:89` | noqa | comment above: S603: fixed argv, no shell, and every path is test-controlle | suppresses rule(s) not enabled: S603 | `return subprocess.run(  # noqa: S603` |
| `tests/integration/test_packager_gates.py:162` | noqa | NONE | suppresses rule(s) not enabled: S603 | `subprocess.run(  # noqa: S603` |
| `tests/integration/test_plan_export.py:31` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_plan_export.py:39` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:49` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:55` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:62` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:72` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:83` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:94` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:104` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:176` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:196` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:218` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:259` | type-ignore | NONE |  | `for node in ast.walk(self._tree())  # type: ignore[arg-type]` |
| `tests/integration/test_plan_export.py:277` | type-ignore | NONE |  | `for node in ast.walk(tree)  # type: ignore[arg-type]` |
| `tests/integration/test_plan_export.py:317` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:329` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:345` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_plan_export.py:384` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:16` | type-ignore | NONE |  | `resp = client.get("/", cookies={}, follow_redirects=False)  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:22` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:33` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:42` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:51` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:97` | type-ignore | NONE |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_root_contract.py:103` | type-ignore | NONE |  | `resp = client.get("/", cookies={}, follow_redirects=False)  # type: ignore[attr-defined]` |
| `tests/integration/test_threat_screen_route.py:29` | type-ignore | NONE |  | `return client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_threat_screen_route.py:157` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:16` | type-ignore | NONE |  | `resp = client.get("/login")  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:21` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:27` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:33` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:42` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:61` | type-ignore | comment above: Use a fresh client with no cookies to test unauthenticated a |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes.py:70` | type-ignore | comment above: Login first to get a session cookie |  | `login = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:76` | type-ignore | NONE |  | `resp = client.get("/", cookies={"spectre_session": session_cookie})  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:84` | type-ignore | NONE |  | `login = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:92` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:102` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:115` | type-ignore | NONE |  | `login = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:123` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:133` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:148` | type-ignore | NONE |  | `login = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:156` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:166` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:177` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes.py:190` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:29` | type-ignore | NONE |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:35` | type-ignore | NONE |  | `client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:47` | type-ignore | NONE |  | `resp = client.get("/training", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:51` | type-ignore | NONE |  | `resp = client.get("/training/", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:55` | type-ignore | NONE |  | `resp = client.get("/training/dashboard", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-define` |
| `tests/integration/test_web_routes_extended.py:59` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:70` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:79` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:87` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:95` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:103` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:111` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:119` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:127` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:135` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:144` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:154` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:164` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:173` | type-ignore | NONE |  | `resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defin` |
| `tests/integration/test_web_routes_extended.py:177` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:187` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:212` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:221` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:241` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:262` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:283` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:307` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:321` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:336` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:352` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:367` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:377` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:385` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:396` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:404` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:418` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:427` | type-ignore | NONE |  | `resp = client.get("/gcat/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:432` | type-ignore | comment above: Should return a "not loaded" message rather than crash |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:440` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:450` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:459` | type-ignore | NONE |  | `resp = client.get("/pol/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:464` | type-ignore | comment above: No UDL session credentials — should return an error partial |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:475` | type-ignore | comment above: UDL direct mode with missing credentials |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:487` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:508` | type-ignore | NONE |  | `get_session_state("testadmin").last_pol_analysis = pol  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:511` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:536` | type-ignore | NONE |  | `get_session_state("testadmin").last_pol_analysis = pol  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:537` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:548` | type-ignore | NONE |  | `with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]` |
| `tests/integration/test_web_routes_extended.py:560` | type-ignore | comment above: Start a scenario |  | `start_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:566` | skip | inline: "Scenario not available at current level") |  | `pytest.skip("Scenario not available at current level")` |
| `tests/integration/test_web_routes_extended.py:579` | skip | inline: "Could not extract result_id from response") |  | `pytest.skip("Could not extract result_id from response")` |
| `tests/integration/test_web_routes_extended.py:584` | type-ignore | comment above: Submit the scenario |  | `submit_resp = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:598` | type-ignore | comment above: Completing a tutorial twice should not award points the seco |  | `resp1 = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:603` | type-ignore | NONE |  | `resp2 = client.post(  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:632` | type-ignore | NONE |  | `get_session_state("testadmin").last_pol_analysis = pol  # type: ignore[attr-defined]` |
| `tests/integration/test_web_routes_extended.py:634` | type-ignore | NONE |  | `resp = client.get(  # type: ignore[attr-defined]` |
| `tests/unit/test_auth.py:10` | noqa | NONE |  | `from spectre.web.auth import (  # noqa: E402` |
| `tests/unit/test_cognitive_complexity_meter.py:41` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_cognitive_complexity_meter.py:147` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_cognitive_complexity_meter.py:150` | skip | inline: "the calibration replays a commit; git is not available here") |  | `pytest.skip("the calibration replays a commit; git is not available here")` |
| `tests/unit/test_cognitive_complexity_meter.py:151` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_cognitive_complexity_meter.py:213` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_cognitive_complexity_meter.py:216` | skip | inline: "the scoping check needs git") |  | `pytest.skip("the scoping check needs git")` |
| `tests/unit/test_cognitive_complexity_meter.py:217` | noqa | NONE | suppresses rule(s) not enabled: S603 | `dirty = subprocess.run(  # noqa: S603` |
| `tests/unit/test_cognitive_complexity_meter.py:239` | noqa | comment above: tree and the skip above is no longer needed for this leg. | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_csrf.py:95` | type-ignore | NONE |  | `assert client.get("/login").status_code == 200  # type: ignore[attr-defined]` |
| `tests/unit/test_csrf.py:98` | type-ignore | NONE |  | `resp = client.post("/scenario/time", data={})  # type: ignore[attr-defined]` |
| `tests/unit/test_csrf.py:103` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/unit/test_csrf.py:113` | type-ignore | NONE |  | `resp = client.post(  # type: ignore[attr-defined]` |
| `tests/unit/test_db_pool_contract.py:90` | noqa | inline: the point is the class | suppresses rule(s) not enabled: BLE001 | `except Exception as exc:        # noqa: BLE001 - the point is the class` |
| `tests/unit/test_deployment_contract.py:43` | skip | inline: f"{name} is excluded from the submission package") |  | `pytest.skip(f"{name} is excluded from the submission package")` |
| `tests/unit/test_deployment_contract.py:95` | skip | inline: "Dockerfile is not present in this tree") |  | `pytest.skip("Dockerfile is not present in this tree")` |
| `tests/unit/test_deployment_contract.py:435` | no-cover | inline: no git |  | `except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git` |
| `tests/unit/test_deployment_contract.py:438` | no-cover | inline: broken git |  | `if result.returncode not in (0, 1):  # pragma: no cover - broken git` |
| `tests/unit/test_deployment_contract.py:564` | skip | inline: f"{name} is excluded from this package") |  | `pytest.skip(f"{name} is excluded from this package")` |
| `tests/unit/test_deployment_contract.py:663` | skip | inline: "no lock file travels in this tree") |  | `pytest.skip("no lock file travels in this tree")` |
| `tests/unit/test_deployment_contract.py:796` | skip | inline reason= |  | `@pytest.mark.skipif(not _DOCKER_ONLY, reason="python template: manifests ship by design")` |
| `tests/unit/test_deployment_contract.py:813` | skip | inline reason= |  | `@pytest.mark.skipif(not _DOCKER_ONLY, reason="python template: manifests ship by design")` |
| `tests/unit/test_docs_are_committable.py:51` | skip | inline: "no git executable: the runner's job image ships none") |  | `pytest.skip("no git executable: the runner's job image ships none")` |
| `tests/unit/test_docs_are_committable.py:53` | skip | inline: "no git repository: running from the submission package") |  | `pytest.skip("no git repository: running from the submission package")` |
| `tests/unit/test_docs_are_committable.py:55` | skip | inline: "docs/ is excluded from the submission package") |  | `pytest.skip("docs/ is excluded from the submission package")` |
| `tests/unit/test_docs_are_committable.py:60` | noqa | NONE | suppresses rule(s) not enabled: S603 | `return subprocess.run(  # noqa: S603` |
| `tests/unit/test_docs_are_committable.py:86` | noqa | NONE | suppresses rule(s) not enabled: S603 | `tracked = subprocess.run(  # noqa: S603` |
| `tests/unit/test_docs_are_committable.py:120` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_entrypoint.py:44` | noqa | NONE | suppresses rule(s) not enabled: S104 | `assert captured["host"] == "0.0.0.0"  # noqa: S104` |
| `tests/unit/test_health.py:69` | type-ignore | NONE |  | `resp = client.get("/healthz")  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:74` | type-ignore | NONE |  | `resp = client.get("/readyz")  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:88` | type-ignore | NONE |  | `resp = client.get("/readyz")  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:97` | type-ignore | NONE |  | `assert client.get("/healthz").status_code == 200  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:98` | type-ignore | NONE |  | `assert client.get("/readyz").status_code == 200  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:115` | type-ignore | NONE |  | `body = client.get(path).json()  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:125` | type-ignore | NONE |  | `assert __version__ not in client.get(path).text  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:137` | type-ignore | NONE |  | `client.get("/readyz")  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:156` | type-ignore | NONE |  | `resp = client.get(path)  # type: ignore[attr-defined]` |
| `tests/unit/test_health.py:164` | type-ignore | NONE |  | `body = client.get(path).text  # type: ignore[attr-defined]` |
| `tests/unit/test_hrr_bootstrap.py:59` | skip | inline: "no git executable: the runner's job image ships none") |  | `pytest.skip("no git executable: the runner's job image ships none")` |
| `tests/unit/test_hrr_bootstrap.py:61` | skip | inline: "no git repository: running from the submission package") |  | `pytest.skip("no git repository: running from the submission package")` |
| `tests/unit/test_hrr_bootstrap.py:70` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_hrr_bootstrap.py:90` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_hrr_bootstrap.py:109` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_hrr_bootstrap.py:128` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_lambert_validation.py:79` | no-cover | inline: the reference propagator converges on these cases |  | `else:  # pragma: no cover - the reference propagator converges on these cases` |
| `tests/unit/test_operator_sees_metres_per_second.py:302` | skip | inline: "operator guide generator not present in this checkout") |  | `pytest.skip("operator guide generator not present in this checkout")` |
| `tests/unit/test_outbound_and_ddl_guards.py:46` | type-ignore | NONE |  | `httpx.Client = _record  # type: ignore[misc, assignment]` |
| `tests/unit/test_outbound_and_ddl_guards.py:50` | type-ignore | NONE |  | `httpx.Client = original  # type: ignore[misc]` |
| `tests/unit/test_outbound_and_ddl_guards.py:160` | type-ignore | NONE |  | `httpx.Client = _ScriptedClient  # type: ignore[misc, assignment]` |
| `tests/unit/test_outbound_and_ddl_guards.py:164` | type-ignore | NONE |  | `httpx.Client = original  # type: ignore[misc]` |
| `tests/unit/test_quality_gate_scope.py:79` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_quality_gate_scope.py:103` | skip | inline: "scripts/ is excluded from the submission package") |  | `pytest.skip("scripts/ is excluded from the submission package")` |
| `tests/unit/test_quality_gate_scope.py:134` | no-cover | inline: the repo fixture skips before this |  | `if git is None:  # pragma: no cover - the repo fixture skips before this` |
| `tests/unit/test_quality_gate_scope.py:135` | skip | inline: "the scoping checks need git") |  | `pytest.skip("the scoping checks need git")` |
| `tests/unit/test_quality_gate_scope.py:136` | noqa | NONE | suppresses rule(s) not enabled: S603 | `subprocess.run(  # noqa: S603` |
| `tests/unit/test_quality_gate_scope.py:144` | noqa | NONE | suppresses rule(s) not enabled: S603 | `return subprocess.run(  # noqa: S603` |
| `tests/unit/test_quality_gate_scope.py:166` | skip | inline: "the scoping checks need git") |  | `pytest.skip("the scoping checks need git")` |
| `tests/unit/test_rate_limit_memory.py:30` | type-ignore | NONE |  | `return asyncio.run(coro)  # type: ignore[arg-type]` |
| `tests/unit/test_rate_limit_memory.py:121` | type-ignore | NONE |  | `limiter._evict_elapsed = counting  # type: ignore[method-assign]` |
| `tests/unit/test_rate_limit_memory.py:180` | type-ignore | NONE |  | `total += sum(sys.getsizeof(stamp) for stamp in queue)  # type: ignore[attr-defined]` |
| `tests/unit/test_tactical.py:402` | noqa | comment above: without failing the suite on a case physics allows. |  | `assert cheapest_long <= cheapest_short or True  # noqa: SIM222` |
| `tests/unit/test_template_markup_is_well_formed.py:103` | noqa | NONE | suppresses rule(s) not enabled: S603 | `result = subprocess.run(  # noqa: S603` |
| `tests/unit/test_token_channels_match.py:116` | type-ignore | NONE |  | `return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]` |
| `tests/integration/test_packager_gates.py:40` | skip (module pytestmark) | inline reason= |  | `pytestmark = pytest.mark.skipif(` reason "packager and git are excluded from the submission package" |
| `tests/unit/test_deployment_contract.py:72` | skip (marker definition) | inline reason= TBC, re-verify full reason text |  | `_python_template_only = pytest.mark.skipif(` |
| `pyproject.toml:69` | config: coverage omit | NONE at site | | `omit = ["tests/*", "spectre/app_logging/config.py"]` |
| `sonar-project.properties:41` | config: Sonar coverage exclusion | TBC, re-verify comment above line 41 | | `sonar.coverage.exclusions=spectre/app_logging/config.py` |
| `pyproject.toml:85-89` | config: ruff global ignore | inline per code | | `B008`, `E501`, `SIM108` |
| `pyproject.toml:92-93` | config: ruff per-file ignores | NONE | | `"tests/**" = ["ANN"]` (ANN not selected, inert); `"docs/**" = ["ALL"]` |
| `pyproject.toml:101,103` | config: mypy | comment above 103 | | `ignore_missing_imports = true`; `disable_error_code = ["untyped-decorator"]` |
| `pyproject.toml:112` | config: bandit exclude | NONE | | `exclude_dirs = ["tests", ".venv"]` |
