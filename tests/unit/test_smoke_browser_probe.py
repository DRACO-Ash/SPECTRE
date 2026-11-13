"""scripts/smoke-browser.py finds the installed Chromium and screens an asset the acceptance check takes (SPC-230).

Found building SPC-202: the probe's [asset-screening-result] check failed on 0.31.0 as well as later releases. The
cause was the probe, not the page: both of its element sets carried a wrong checksum on each line, so from 0.30.0,
when every ingest path ran the acceptance check (SPC-201), the manual asset was refused, and the refusal is neither
a ranking nor one of the explanations the probe looks for. The browser lookup took the first versioned directory in
text order, so with two builds installed it could take the older; it now takes the newest build, in either layout,
chrome-linux or chrome-linux64.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from spectre.astro.elset_check import check_elset
from tests.unit.test_deployment_contract import _repo_only


def _probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_smoke_browser", _repo_only("scripts/smoke-browser.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["_PROBE_ASSET_TLE", "_PROBE_RED_TLE"])
def test_each_probe_element_set_passes_the_acceptance_check(name: str) -> None:
    check = check_elset(getattr(_probe(), name))
    assert check.failures == ()
    assert check.accepted is True


def _install(root: Path, build: str, layout: str) -> Path:
    chrome = root / build / layout / "chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("", encoding="utf-8")
    return chrome


def test_the_probe_finds_chrome_linux64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chrome = _install(tmp_path, "chromium-1243", "chrome-linux64")
    _install(tmp_path, "chromium_headless_shell-1243", "chrome-headless-shell-linux64")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert _probe()._find_chromium() == str(chrome)


def test_the_probe_takes_the_newest_build_whichever_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install(tmp_path, "chromium-1187", "chrome-linux")
    newest = _install(tmp_path, "chromium-1243", "chrome-linux64")
    _install(tmp_path, "chromium-999", "chrome-linux")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert _probe()._find_chromium() == str(newest)


def test_with_no_build_the_probe_lets_playwright_choose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert _probe()._find_chromium() is None
