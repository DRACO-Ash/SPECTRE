"""The Monte Carlo density model is Vallado's exponential atmosphere.

Audit F-105. The uncited table had its scale heights shifted one band
against base densities that matched no published row, so density jumped at
most band edges (x24.9 at 150 km, x2.74 at 400 km, x10.1 at 1,000 km) and
read 2.22e-13 kg/m^3 at 550 km against about 3.2e-13.

Reference: Vallado, Fundamentals of Astrodynamics and Applications,
Table 8-4 (exponential atmosphere).
"""

from __future__ import annotations

import pytest

from spectre.astro.monte_carlo import _atmo_density_kg_m3


@pytest.mark.parametrize(
    ("h_km", "rho"),
    [(200.0, 2.789e-10), (450.0, 1.585e-12), (700.0, 3.614e-14)],
)
def test_the_band_bases_are_the_published_rows(h_km: float, rho: float) -> None:
    assert _atmo_density_kg_m3(h_km) == pytest.approx(rho, rel=0.01)


def test_mid_band_density_at_550_km() -> None:
    # 6.967e-13 exp(-50 / 63.822) from the 500 km row.
    assert _atmo_density_kg_m3(550.0) == pytest.approx(3.183e-13, rel=0.01)


@pytest.mark.parametrize("edge", [25, 100, 150, 180, 200, 300, 400, 500, 600, 700, 1000])
def test_density_is_continuous_across_band_edges(edge: float) -> None:
    below, at = _atmo_density_kg_m3(edge - 1e-9), _atmo_density_kg_m3(edge)
    assert at == pytest.approx(below, rel=0.02)
