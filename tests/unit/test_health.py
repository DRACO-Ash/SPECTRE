"""Tests for the unauthenticated health and readiness endpoints.

These probes are the platform's only view of a running pod, so their failure
modes matter more than their success path: a probe that hangs is killed
silently by kubelet, and a 503 without an errno cannot be diagnosed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from spectre.web.health import _STORAGE_PROBE_TIMEOUT_SECONDS, check_storage


class TestStorageProbe:
    async def test_reports_healthy_on_a_writable_directory(self, tmp_path: Path) -> None:
        healthy, detail = await check_storage(str(tmp_path))
        assert healthy is True
        assert detail is None

    async def test_removes_its_probe_file(self, tmp_path: Path) -> None:
        """The probe must prove a write without leaving litter on the volume."""
        await check_storage(str(tmp_path))
        assert list(tmp_path.iterdir()) == []

    async def test_reports_unhealthy_for_a_missing_directory(self, tmp_path: Path) -> None:
        healthy, detail = await check_storage(str(tmp_path / "does-not-exist"))
        assert healthy is False
        assert detail is not None
        assert "errno" in detail

    async def test_reports_errno_for_an_unwritable_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Injected rather than chmod-based: the suite also runs as root."""
        def deny_write(self: Path, *args: object, **kwargs: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "write_text", deny_write)
        healthy, detail = await check_storage(str(tmp_path))
        assert healthy is False
        assert detail is not None and "errno 13" in detail

    async def test_reports_a_stalled_mount_rather_than_hanging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hanging probe is killed silently by kubelet; it must time out loudly."""
        import spectre.web.health as health_module

        def hang(self: Path, *args: object, **kwargs: object) -> None:
            time.sleep(5)

        monkeypatch.setattr(health_module, "_STORAGE_PROBE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(Path, "write_text", hang)
        healthy, detail = await check_storage(str(tmp_path))
        assert healthy is False
        assert detail is not None and "stalled" in detail

    def test_timeout_is_shorter_than_a_platform_probe(self) -> None:
        """A probe that outlives the platform's timeout becomes a silent kill."""
        assert 0 < _STORAGE_PROBE_TIMEOUT_SECONDS < 5.0


class TestHealthEndpoints:
    def test_healthz_is_unauthenticated_and_200(self, client: object) -> None:
        resp = client.get("/healthz")  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_healthz_carries_the_version_stamp(self, client: object) -> None:
        from spectre import __version__

        assert client.get("/healthz").json()["version"] == __version__  # type: ignore[attr-defined]

    def test_readyz_is_unauthenticated_and_200(self, client: object) -> None:
        resp = client.get("/readyz")  # type: ignore[attr-defined]
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "data_dir" in body

    def test_readyz_reports_503_with_diagnosis_when_storage_fails(
        self, client: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A screenshot of the 503 must be a complete diagnosis on its own."""
        from spectre.web import health

        async def broken(_data_dir: str) -> tuple[bool, str | None]:
            return False, "storage write to /data failed: [errno 13] Permission denied"

        monkeypatch.setattr(health, "check_storage", broken)
        resp = client.get("/readyz")  # type: ignore[attr-defined]
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unavailable"
        assert "errno 13" in body["detail"]
        assert "fsGroup" in body["remedy"]
        assert "data_dir" in body

    def test_health_paths_are_exempt_from_csrf(self, client: object) -> None:
        """GET is a safe method, so the global CSRF dependency must admit it."""
        assert client.get("/healthz").status_code == 200  # type: ignore[attr-defined]
        assert client.get("/readyz").status_code == 200  # type: ignore[attr-defined]
