"""The two compute-heavy PoL forms are bounded (audit F-145).

/pol/monte-carlo clamped its sample count but took any horizon, and neither it
nor /pol/photometry-analyse had a rate limit; the photometry CSV was any size
and was parsed on the event loop. One operator could queue arbitrarily long
propagations and starve the executor every other feature uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from spectre.web.routes.pol import MAX_HORIZON_H, MAX_PHOTOMETRY_CSV_CHARS
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login


def _operator(client: TestClient, name: str) -> dict[str, str]:
    """A fresh operator with an untouched compute budget."""
    admin = _admin_cookies(client)
    _create_operator(client, admin, name, "compute-bounds-pass")
    client.cookies.clear()
    resp = _login(client, name, "compute-bounds-pass")
    return dict(resp.cookies)  # type: ignore[attr-defined]


def _monte_carlo(client: TestClient, cookies: dict[str, str], horizon_h: float) -> object:
    return client.post(
        "/pol/monte-carlo",
        data={"satno": "25544", "manoeuvre_epoch": "2026-01-01T00:00:00", "horizon_h": str(horizon_h)},
        cookies=cookies, headers=csrf_headers(cookies),
    )


class TestHorizon:
    def test_the_cap_is_30_days(self) -> None:
        assert MAX_HORIZON_H == 720.0

    def test_a_horizon_above_the_cap_is_refused(self, client: TestClient) -> None:
        cookies = _operator(client, "f145_horizon")
        resp = _monte_carlo(client, cookies, 721.0)
        assert resp.status_code == 200  # type: ignore[attr-defined]
        assert b"between 1 and 720 hours" in resp.content  # type: ignore[attr-defined]

    def test_a_non_positive_horizon_is_refused(self, client: TestClient) -> None:
        cookies = _operator(client, "f145_zero")
        assert b"between 1 and 720 hours" in _monte_carlo(client, cookies, 0.0).content  # type: ignore[attr-defined]

    def test_the_cap_itself_is_accepted(self, client: TestClient) -> None:
        # No analysis is loaded, so an accepted horizon reaches the next check.
        cookies = _operator(client, "f145_cap")
        resp = _monte_carlo(client, cookies, 720.0)
        assert b"No PoL analysis for this SATNO" in resp.content  # type: ignore[attr-defined]


class TestPhotometryCsv:
    def test_a_csv_over_the_cap_is_refused_unparsed(self, client: TestClient) -> None:
        cookies = _operator(client, "f145_csv")
        csv_text = "epoch_utc,apparent_magnitude\n" + "x" * MAX_PHOTOMETRY_CSV_CHARS
        assert len(csv_text) < 1_048_576, "Starlette refuses a field over 1 MiB before the route sees it"
        resp = client.post(
            "/pol/photometry-analyse", data={"csv_text": csv_text},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"too large" in resp.content


class TestComputeRateLimit:
    def test_an_operator_is_limited_across_both_forms(self, client: TestClient) -> None:
        cookies = _operator(client, "f145_rate")
        codes = [_monte_carlo(client, cookies, 48.0).status_code for _ in range(10)]  # type: ignore[attr-defined]
        assert codes == [200] * 10
        resp = client.post(
            "/pol/photometry-analyse", data={"csv_text": "epoch_utc,apparent_magnitude\n"},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert resp.status_code == 429

    def test_one_operators_limit_leaves_anothers_budget(self, client: TestClient) -> None:
        cookies = _operator(client, "f145_other")
        assert _monte_carlo(client, cookies, 48.0).status_code == 200  # type: ignore[attr-defined]
