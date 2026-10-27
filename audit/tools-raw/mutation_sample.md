| File:line | Mutant | Result | Evidence (first failing test, or summary) |
|---|---|---|---|
| `transfers.py:33` | vis-viva sign | **KILLED** | `tests/unit/test_astro.py::TestHohmann::test_leo_to_geo` |
| `transfers.py:47` | Hohmann transfer SMA scaled by 0.95 | **KILLED** | `tests/unit/test_astro.py::TestHohmann::test_leo_to_geo` |
| `transfers.py:49` | Hohmann circular speed +3% | **KILLED** | `tests/unit/test_astro.py::TestHohmann::test_leo_to_geo` |
| `transfers.py:56` | Hohmann transfer time +4% | **KILLED** | `tests/unit/test_astro.py::TestHohmann::test_leo_to_geo` |
| `transfers.py:55` | Hohmann second burn +4% | **SURVIVED** | `213 passed in 3.16s` |
| `transfers.py:80` | bi-elliptic first SMA wrong | **KILLED** | `tests/unit/test_astro.py::TestBielliptic::test_basic` |
| `transfers.py:92` | bi-elliptic apoapsis burn sign | **KILLED** | `tests/unit/test_astro.py::TestBielliptic::test_basic` |
| `transfers.py:93` | bi-elliptic third burn doubled | **SURVIVED** | `213 passed in 3.10s` |
| `transfers.py:94` | bi-elliptic second leg uses a1 | **SURVIVED** | `213 passed in 3.11s` |
| `transfers.py:28` | total omits third burn | **SURVIVED** | `213 passed in 3.13s` |
| `csrf.py:24` | DELETE treated as safe | **SURVIVED** | `242 passed in 51.91s` |
| `csrf.py:25` | logout exempted | **KILLED** | `tests/integration/test_web_routes.py::TestLogoutFlow::test_logout_without_a_csrf_token_is_rejected` |
| `csrf.py:46` | token not bound to session | **KILLED** | `tests/unit/test_csrf.py::TestTokenBinding::test_a_token_does_not_verify_against_another_session` |
| `csrf.py:57` | empty-session token accepted path | **KILLED** | `tests/integration/test_web_routes.py::TestLogoutFlow::test_logout_without_a_session_still_redirects` |
| `csrf.py:62` | bad signature accepted | **NOT-APPLIED (line mismatch)** | `` |
| `csrf.py:91` | form-parse failure token | **SURVIVED** | `242 passed in 51.73s` |
| `auth.py:22` | session never expires | **SURVIVED** | `219 passed in 52.90s` |
| `auth.py:102` | revocation disabled | **KILLED** | `tests/integration/test_login_hardening.py::TestSessionRevocation::test_logout_refuses_the_captured_cookie` |
| `auth.py:159` | admin check disabled | **KILLED** | `tests/integration/test_admin_routes.py::TestAdminAccess::test_operator_forbidden` |
| `auth.py:195` | optional_login ignores revocation | **SURVIVED** | `219 passed in 53.60s` |
| `auth.py:141` | require_login ignores revocation | **KILLED** | `tests/integration/test_login_hardening.py::TestSessionRevocation::test_logout_refuses_the_captured_cookie` |

Killed 12, survived 8, not applied 1, of 21.
