"""Local TACREP_NOTSO cache — persistent JSON store for UDL notification records.

The cache file ``notso_cache.json`` lives in the configured data directory
(SPECTRE_DATA_DIR, then STORAGE_MOUNT_PATH, then ./data), seeded on first use
from the copy bundled beside this module. It is structured as::

    {
        "metadata": {
            "last_sync_utc": "2026-04-06T12:00:00Z",
            "total_records": 1234,
            "source": "UDL TACREP_NOTSO"
        },
        "records": [
            {
                "id":         "...",
                "createdAt":  "2026-04-01T08:00:00.000000Z",
                "msgType":    "TACREP_NOTSO",
                "dataMode":   "REAL",
                "msgBody":    {"SatIds": ["43689"], "Event_Class": "Maneuver / ...",
                               "Event_Description": "Jday 091 0800z ...", ...}
            },
            ...
        ]
    }

That is the shape UDL returns for a JCO TACREP_NOTSO notification. The cache
read ``msgId``, a top-level ``satNo`` and ``msgText``, which no real record
carries, so it found nothing for any object (audit F-046). Those legacy keys
are still read, after the real ones.

Records are stored in ascending ``createdAt`` order.  Each sync fetches only
records newer than the highest ``createdAt`` already in the file.

Usage::

    from spectre.data.notso_cache import NotsoCache
    cache = NotsoCache()
    cache.append(new_records)          # called by the sync route
    records = cache.get_for_satno(43689)
    latest = cache.latest_created_at() # returns datetime | None
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

#: The copy shipped with the package, used only to seed a new data directory.
_BUNDLED_PATH = Path(__file__).parent / "notso_cache.json"
_CACHE_NAME = "notso_cache.json"
_EPOCH_ZERO = "1970-01-01T00:00:00.000000Z"
# "Jday 002 1934z": day of year and UTC time at the head of Event_Description.
_JDAY = re.compile(r"\bJ\s*day\s*(\d{1,3})\s+(\d{2})(\d{2})\s*z", re.IGNORECASE)
_SATNO = re.compile(r"^\d{1,9}$")


def default_cache_path() -> Path:
    """The cache file in the configured data directory (audit F-062).

    It sat inside the installed package, which bypassed SPECTRE_DATA_DIR and
    STORAGE_MOUNT_PATH and is ephemeral in the container image.
    """
    from spectre.config.settings import get_settings

    return Path(get_settings().data_dir) / _CACHE_NAME


def record_id(rec: dict[str, Any]) -> str:
    """A record's unique id: UDL's ``id``, else the legacy message id keys."""
    return str(rec.get("id") or rec.get("msgId") or rec.get("messageId") or "")


def record_satnos(rec: dict[str, Any]) -> set[str]:
    """Every catalogue number a record names.

    ``msgBody.SatIds`` arrives as a list, as None, or as the text of a list,
    and holds "-" when no object was named; a legacy record has ``satNo``.
    """
    raw = (rec.get("msgBody") or {}).get("SatIds")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            raw = [raw]
    ids = {str(x).strip() for x in (raw or []) if x is not None}
    if rec.get("satNo") is not None:
        ids.add(str(rec["satNo"]).strip())
    return {x for x in ids if _SATNO.match(x)}


def _event_start(description: str, created: datetime | None) -> datetime | None:
    """The event time a JCO description opens with, dated by its record.

    The description gives a day of year and a time but no year, so the year is
    the record's own; a day that would land after the record was created
    belongs to the year before (a 31 December event reported on 1 January).
    """
    m = _JDAY.search(description)
    if not m or created is None:
        return None
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    for year in (created.year, created.year - 1):
        when = datetime(year, 1, 1, hour, minute, tzinfo=UTC) + timedelta(days=day - 1)
        if when <= created + timedelta(days=1):
            return when
    return None


def message_text(rec: dict[str, Any], satno: int | str) -> str:
    """Labelled text the NOTSO parser reads, for one record and one satellite.

    A legacy record carrying its whole notification in ``msgText`` passes
    through. A JCO record's fields are laid out under the labels the parser
    knows; the window start is left out when the description gives no time,
    so the parser infers it and flags it as inferred rather than guessing.
    """
    legacy = str(rec.get("msgText") or rec.get("message") or "")
    if legacy:
        return legacy
    body = rec.get("msgBody") or {}
    created = rec.get("createdAt") or ""
    event_class = " ".join(str(body.get("Event_Class") or rec.get("msgType") or "").split())
    kind = event_class.split(" / ")[0].strip() or "Other"
    lines = [
        f"MSGID: {record_id(rec) or body.get('NOTSO', '')}",
        f"SATNO: {satno}",
        f"ISSUER: {rec.get('source') or 'UNKNOWN'}",
        f"ISSUE DATE: {body.get('Publish_Date') or created}",
        # A trailing word keeps a bare "RPO" readable to the type keywords.
        f"TYPE: {kind} event",
        f"DESCRIPTION: {event_class}",
    ]
    start = _event_start(str(body.get("Event_Description") or ""), _parse_iso(created))
    if start is not None:
        lines.insert(4, f"EFFECTIVE START: {start.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    return "\n".join(lines)


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

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_cache_path()
        if path is None:
            self._seed()
        self._data: dict[str, Any] = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _seed(self) -> None:
        """Start a new data directory from the bundled copy, once."""
        if self._path.exists() or not _BUNDLED_PATH.exists() or self._path == _BUNDLED_PATH:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_BUNDLED_PATH, self._path)
        logger.info("notso_cache: seeded %s from the bundled cache", self._path)

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if "records" in data and "metadata" in data:
                    return cast(dict[str, Any], data)
                raise ValueError("no records or metadata")
            # BLE001: any unreadable file is kept aside and the cache starts empty.
            except Exception as exc:  # noqa: BLE001
                aside = self._path.with_name(
                    f"{self._path.name}.corrupt-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
                )
                self._path.replace(aside)
                # It was overwritten in silence before (audit F-141); the next
                # sync then re-pulled from 2024. The bad file is now kept.
                logger.warning("notso_cache: unreadable cache moved to %s: %s", aside, exc)
        return {"metadata": {"last_sync_utc": None, "total_records": 0,
                              "source": "UDL TACREP_NOTSO"},
                "records": []}

    def _save(self) -> None:
        self._data["metadata"]["total_records"] = len(self._data["records"])
        self._data["metadata"]["last_sync_utc"] = datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # Written beside the target and swapped in, so a crash mid-write leaves
        # the previous file whole (audit F-141).
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

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
        return cast(str | None, self._data["metadata"].get("last_sync_utc"))

    def append(self, new_records: list[dict[str, Any]]) -> int:
        """Append *new_records* (dicts from UDL) to the cache, deduplicating by id.

        Records are sorted by ``createdAt`` ascending before writing.
        Returns the number of records actually added.
        """
        if not new_records:
            return 0

        existing_ids: set[str] = {record_id(r) for r in self._data["records"]}

        added = 0
        for rec in new_records:
            msg_id = record_id(rec)
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

    def get_for_satno(self, satno: int | str) -> list[dict[str, Any]]:
        """Return all cached records that name *satno*."""
        target = str(satno).strip()
        return [r for r in self._data["records"] if target in record_satnos(r)]

    def all_records(self) -> list[dict[str, Any]]:
        return list(self._data["records"])


# Module-level singleton — shared across all requests in one process.
_cache: NotsoCache | None = None


def get_notso_cache() -> NotsoCache:
    """Return (or create) the module-level NotsoCache singleton."""
    global _cache
    if _cache is None:
        _cache = NotsoCache()
    return _cache
