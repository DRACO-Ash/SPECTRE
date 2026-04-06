"""Local TACREP_NOTSO cache — persistent JSON store for UDL notification records.

The cache file ``notso_cache.json`` lives in the same directory as this module
(``sipc/data/``).  It is structured as::

    {
        "metadata": {
            "last_sync_utc": "2026-04-06T12:00:00Z",
            "total_records": 1234,
            "source": "UDL TACREP_NOTSO"
        },
        "records": [
            {
                "msgId":         "...",
                "satNo":         43689,
                "createdAt":     "2026-04-01T08:00:00.000000Z",
                "msgType":       "TACREP_NOTSO",
                "msgText":       "...(full notification text)...",
                "dataMode":      "REAL"
            },
            ...
        ]
    }

Records are stored in ascending ``createdAt`` order.  Each sync fetches only
records newer than the highest ``createdAt`` already in the file.

Usage::

    from sipc.data.notso_cache import NotsoCache
    cache = NotsoCache()
    cache.append(new_records)          # called by the sync route
    records = cache.get_for_satno(43689)
    latest = cache.latest_created_at() # returns datetime | None
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / "notso_cache.json"
_EPOCH_ZERO = "1970-01-01T00:00:00.000000Z"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip().rstrip("Z")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class NotsoCache:
    """Thread-safe (GIL-sufficient for single-process FastAPI) local NOTSO cache."""

    def __init__(self, path: Path = _CACHE_PATH) -> None:
        self._path = path
        self._data: dict = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if "records" in data and "metadata" in data:
                    return data
            except Exception as exc:
                logger.warning("notso_cache: corrupt cache file, resetting. %s", exc)
        return {"metadata": {"last_sync_utc": None, "total_records": 0,
                              "source": "UDL TACREP_NOTSO"},
                "records": []}

    def _save(self) -> None:
        self._data["metadata"]["total_records"] = len(self._data["records"])
        self._data["metadata"]["last_sync_utc"] = datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def latest_created_at(self) -> datetime | None:
        """Return the ``createdAt`` timestamp of the newest cached record, or None."""
        records = self._data["records"]
        if not records:
            return None
        # Records are appended in ascending order; last entry is newest.
        return _parse_iso(records[-1].get("createdAt"))

    def total_records(self) -> int:
        return len(self._data["records"])

    def last_sync_utc(self) -> str | None:
        return self._data["metadata"].get("last_sync_utc")

    def append(self, new_records: list[dict]) -> int:
        """Append *new_records* (dicts from UDL) to the cache, deduplicating by msgId.

        Records are sorted by ``createdAt`` ascending before writing.
        Returns the number of records actually added.
        """
        if not new_records:
            return 0

        existing_ids: set[str] = {
            str(r.get("msgId") or r.get("messageId") or "")
            for r in self._data["records"]
        }

        added = 0
        for rec in new_records:
            msg_id = str(rec.get("msgId") or rec.get("messageId") or "")
            if msg_id and msg_id in existing_ids:
                continue
            self._data["records"].append(rec)
            existing_ids.add(msg_id)
            added += 1

        if added:
            # Keep ascending createdAt order
            self._data["records"].sort(
                key=lambda r: r.get("createdAt") or _EPOCH_ZERO
            )
            self._save()

        return added

    def get_for_satno(self, satno: int | str) -> list[dict]:
        """Return all cached records whose satNo matches *satno*."""
        target = str(satno).strip()
        return [
            r for r in self._data["records"]
            if str(r.get("satNo") or "").strip() == target
        ]

    def all_records(self) -> list[dict]:
        return list(self._data["records"])


# Module-level singleton — shared across all requests in one process.
_cache: NotsoCache | None = None


def get_notso_cache() -> NotsoCache:
    """Return (or create) the module-level NotsoCache singleton."""
    global _cache
    if _cache is None:
        _cache = NotsoCache()
    return _cache
