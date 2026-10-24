"""NOTSO (Notice to Space Operators) correlation with manoeuvre detection.

Parses NOTSO messages, correlates them temporally with manoeuvres detected
by the Pattern of Life engine, and extracts operator behavioural profiles.

Typical use::

    notsos = parse_notso_text(raw_text)
    correlations = correlate_notsos_with_manoeuvres(notsos, manoeuvres, norad_id)
    profile = extract_behaviour_profile(norad_id, correlations, start, end)

Data-source note
----------------
NOTSO data may be fetched from a UDL notification endpoint (if available) or
pasted by the operator as free text.  Both paths produce ``NOTSORecord``
objects.  The parser handles the common USSPACECOM template format plus
reasonable variants.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Enumerations ──────────────────────────────────────────────────────────────

class NOTSOType(Enum):
    MANOEUVRE        = "manoeuvre"
    DEORBIT          = "deorbit"
    LAUNCH           = "launch"
    PROXIMITY_OPS    = "proximity_operations"
    TEST             = "test"
    OTHER            = "other"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class NOTSORecord:
    """A single parsed NOTSO message."""

    message_id:             str
    norad_id:               int
    international_designator: str | None
    object_name:            str | None
    issuing_entity:         str
    issue_date_utc:         datetime
    effective_start_utc:    datetime
    effective_end_utc:      datetime
    notso_type:             NOTSOType
    description:            str
    predicted_delta_v_km_s: float | None
    predicted_direction:    str | None
    raw_message:            str
    #: Date fields not read from their own field: "issue date", "effective
    #: start", "effective end". Each was inferred from the text, from another
    #: date, or defaulted, and is shown to the operator as such.
    inferred_fields:        tuple[str, ...] = ()


@dataclass
class NOTSOManoeuvreCorrelation:
    """A correlated pair: NOTSO ↔ detected manoeuvre (one or both may be absent)."""

    notso:             NOTSORecord | None
    manoeuvre:         object | None    # Manoeuvre from pattern_of_life
    correlation_type:  str             # "matched" | "notso_only" | "manoeuvre_only"
    time_offset_hours: float | None    # window offset: NOTSO effective_start − burn (h)
    magnitude_ratio:   float | None    # Predicted ΔV / detected ΔV
    notes:             str = ""
    #: Burn minus the NOTSO's issue date (h): positive when the notice came
    #: first. "Lead time" used to be the window offset above, which ignores
    #: when the notice was issued and is negative for a timely one (audit F-091).
    lead_time_hours:   float | None = None


@dataclass
class OperatorBehaviourProfile:
    """Extracted behavioural patterns from NOTSO–manoeuvre correlations."""

    norad_id:               int
    analysis_period_start:  datetime
    analysis_period_end:    datetime

    # Notification behaviour
    total_manoeuvres:           int
    manoeuvres_with_notso:      int
    manoeuvres_without_notso:   int
    notification_rate:          float   # [0, 1]

    # Timing patterns (h)
    mean_lead_time_h:   float | None
    std_lead_time_h:    float | None
    min_lead_time_h:    float | None
    max_lead_time_h:    float | None

    # Accuracy
    mean_magnitude_ratio:   float | None
    std_magnitude_ratio:    float | None
    window_accuracy_rate:   float       # Fraction where manoeuvre fell inside NOTSO window

    # NOTSOs with no detected manoeuvre beside them.
    #
    # NOT evidence that the operator filed a notice for a burn that never
    # happened. A NOTSO is issued only after human-in-the-loop analysis, so its
    # presence is strong evidence a burn occurred; the absence of a matching
    # detection is far more likely to mean the burn sat below OUR measured
    # detection floor, which on most LEO catalogues is above routine
    # station-keeping. The field was called phantom_notso_count, which put the
    # blame in exactly the wrong place.
    notso_without_detection_count: int = 0
    notso_without_detection_types: dict[str, int] = field(default_factory=dict)

    # ── Reportability ────────────────────────────────────────────────────────
    # A NOTSO is not filed for every burn. Small, routine manoeuvres are
    # deliberately left unreported to stop the notification channel filling
    # with inconsequential traffic, so a routine station-keeping burn is not
    # expected to carry one. Measuring a notification rate over EVERY detected
    # manoeuvre therefore scores a fully compliant operator near zero and, on
    # the bands below, called them a stealth operator.
    reportable_manoeuvres:       int = 0
    below_reporting_threshold:   int = 0
    reporting_threshold_km_s:    float | None = None

    # Behavioural flags, computed over REPORTABLE manoeuvres only and only when
    # there are enough of them to mean anything.
    consistent_notifier:    bool = False   # rate > 0.90
    inconsistent_notifier:  bool = False   # 0.30 ≤ rate ≤ 0.90
    low_notification_rate:  bool = False   # rate < 0.30
    behaviour_unassessable: bool = False   # too few reportable manoeuvres
    predictable_timing:     bool = False   # std_lead_time < _PREDICTABLE_LEAD_STD_H

    def summary(self) -> str:
        rate_pct = f"{self.notification_rate * 100:.0f}%"
        if self.behaviour_unassessable:
            behaviour = (f"notification behaviour not assessable — only "
                         f"{self.reportable_manoeuvres} manoeuvre(s) above the "
                         "reporting threshold")
        elif self.consistent_notifier:
            behaviour = f"consistent notifier ({rate_pct} of reportable manoeuvres)"
        elif self.low_notification_rate:
            behaviour = f"low notification rate ({rate_pct} of reportable manoeuvres)"
        else:
            behaviour = f"inconsistent notifier ({rate_pct} of reportable manoeuvres)"

        parts = [
            f"SATNO {self.norad_id}: {behaviour}.",
            f"{self.total_manoeuvres} manoeuvres detected, of which "
            f"{self.reportable_manoeuvres} above the reporting threshold and "
            f"{self.manoeuvres_with_notso} pre-notified.",
        ]
        if self.below_reporting_threshold:
            parts.append(
                f"{self.below_reporting_threshold} sat below it and would not be "
                "expected to carry a notice."
            )
        if self.mean_lead_time_h is not None:
            parts.append(
                f"Mean notification lead time: {self.mean_lead_time_h:.1f}h"
                + (f" ± {self.std_lead_time_h:.1f}h." if self.std_lead_time_h else ".")
            )
        if self.notso_without_detection_count > 0:
            parts.append(
                f"{self.notso_without_detection_count} NOTSO(s) have no detection "
                "beside them. A NOTSO follows human analysis, so the likeliest "
                "reading is that the burn sat below this object's measured "
                "detection floor rather than that the notice was spurious."
            )
        if self.predictable_timing:
            parts.append("Timing is predictable (low lead-time variance).")
        return " ".join(parts)


# ── NOTSO parser ──────────────────────────────────────────────────────────────

# Datetime patterns for NOTSO messages (various formats encountered in practice)
_DT_PATTERNS = [
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)",               # ISO 8601
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s*UTC",    # YYYY-MM-DD HH:MM UTC
    r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?)\s*UTC",    # MM/DD/YYYY HH:MM UTC
    r"(\d{1,2}\s+\w+\s+\d{4}\s+\d{2}:\d{2})\s*UTC",           # DD Mon YYYY HH:MM UTC
]

_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d %B %Y %H:%M",
    "%d %b %Y %H:%M",
]


def _parse_dt(s: str) -> datetime | None:
    """Parse a NOTSO date to UTC. ISO 8601 first, with fractional seconds and
    offsets, which the fixed formats below rejected (audit F-087)."""
    s = s.strip()
    try:
        iso = datetime.fromisoformat(s)
    except ValueError:
        pass
    else:
        return iso.replace(tzinfo=UTC) if iso.tzinfo is None else iso.astimezone(UTC)
    # Strip timezone suffixes before trying strptime formats
    for suffix in (" UTC", " utc", "Z"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_datetime(text: str) -> datetime | None:
    for pattern in _DT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            dt = _parse_dt(m.group(1))
            if dt:
                return dt
    return None


def _infer_notso_type(text: str) -> NOTSOType:
    low = text.lower()
    if any(w in low for w in ("deorbit", "de-orbit", "reentry", "re-entry", "passivat")):
        return NOTSOType.DEORBIT
    if any(w in low for w in ("launch", "deployment", "deployed")):
        return NOTSOType.LAUNCH
    if any(w in low for w in ("proximity", "rpo ", "rendezvous", "approach", "intercept")):
        return NOTSOType.PROXIMITY_OPS
    if any(w in low for w in ("test", "testing", "calibration", "demonstration")):
        return NOTSOType.TEST
    if any(w in low for w in ("manoeuv", "maneuv", "thruster", "station keep", "stationkeep",
                               "orbit adjust", "orbit correction", "repositioning", "raise", "lower")):
        return NOTSOType.MANOEUVRE
    return NOTSOType.OTHER


def _extract_norad_id(text: str) -> int | None:
    """Extract a labelled NORAD catalogue number from the message text.

    Only a number introduced by a catalogue label counts. The fallbacks that
    took the first five-digit number anywhere, or any five digits after an
    OBJECT label, could pick another object, a quantity or a reference: "close
    approach with 43013" was attributed to 43013 (audit F-090).
    """
    patterns = [
        r"(?:SATNO|SAT\s*NO|NORAD\s*ID|NORAD|CATALOG\s*NO|CATNO)[:\s#]+(\d{4,6})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 999999:
                return val
    return None


def _extract_delta_v(text: str, *, bare: bool = False) -> float | None:
    """Extract predicted ΔV magnitude from NOTSO description.

    With *bare*, *text* is a dedicated field's value, whose key the field
    parser has already stripped, so a plain "1.5 m/s" is accepted (audit
    F-086).
    """
    patterns = [
        r"(?:delta.?v|dv|delta.v)[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|km/s)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|km/s)\s+(?:burn|manoeuvre|maneuver|impulse)",
    ]
    if bare:
        patterns.insert(0, r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|km/s)")
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            # Convert m/s to km/s if the unit says m/s
            if "m/s" in m.group(0).lower() and "km/s" not in m.group(0).lower():
                val /= 1000.0
            return val
    return None


def _split_messages(text: str) -> list[str]:
    """Split a block of text containing multiple NOTSO messages."""
    # Common separators: "---", "===", blank lines > 1, "NOTSO #N"
    messages = re.split(
        r"(?m)^(?:-{3,}|={3,}|\*{3,})\s*$|(?:^NOTSO\s*#?\d+\b)",
        text,
        flags=re.IGNORECASE,
    )
    # A MSGID line also starts a new message when the message so far already
    # has one, or follows a blank line. Splitting on every MSGID cut a message
    # whose SATNO came first in two, and the half holding the window was
    # dropped for want of a SATNO (audit F-088).
    expanded: list[str] = []
    for msg in messages:
        expanded.extend(_split_on_msgid(msg))
    return [m.strip() for m in expanded if m.strip()]


_MSGID_LINE = re.compile(r"^\s*(?:MESSAGE\s*ID|MSGID)\s*:", re.IGNORECASE)


def _split_on_msgid(text: str) -> list[str]:
    """Split *text* before each MSGID line that begins a new message."""
    fragments: list[list[str]] = [[]]
    has_msgid = False
    previous_blank = True
    for line in text.splitlines():
        if _MSGID_LINE.match(line):
            if any(ln.strip() for ln in fragments[-1]) and (has_msgid or previous_blank):
                fragments.append([])
            has_msgid = True
        fragments[-1].append(line)
        previous_blank = not line.strip()
    return ["\n".join(f) for f in fragments]


def parse_notso_text(raw_text: str) -> list[NOTSORecord]:
    """Parse one or more NOTSO messages from free text.

    Handles the common USSPACECOM template format (field: value lines) and
    ISO-formatted structured messages.  Unknown fields are captured in
    *description*.

    Returns
    -------
    list[NOTSORecord]
        Parsed records. See :func:`parse_notso_text_with_rejects` for the
        messages that did not parse and why.
    """
    records, _ = parse_notso_text_with_rejects(raw_text)
    return records


def parse_notso_text_with_rejects(raw_text: str) -> tuple[list[NOTSORecord], list[str]]:
    """Parse NOTSO messages, also returning a reason for each one rejected.

    A message without a labelled NORAD ID used to drop with no log, and one
    that raised reached only the server log, so the operator could not tell a
    pasted message had been lost (audit F-089). Each reject is logged and
    returned as "message N: reason" for the page to show.
    """
    records: list[NOTSORecord] = []
    rejects: list[str] = []
    for i, msg in enumerate(_split_messages(raw_text)):
        try:
            record = _parse_single_notso(msg, index=i)
        except Exception as exc:  # noqa: BLE001 - one bad message must not lose the rest
            rejects.append(f"message {i + 1}: {exc}")
        else:
            if record is None:
                rejects.append(f"message {i + 1}: no labelled NORAD ID")
            else:
                records.append(record)
    for reason in rejects:
        logger.warning("NOTSO not parsed, %s", reason)
    return records, rejects


def _notso_dates(
    fields: dict[str, str], text: str,
) -> tuple[datetime, datetime, datetime, tuple[str, ...]]:
    """Issue date, window start and end, and which of them were inferred.

    A date missing from its own field is taken from the first date in the
    text, then from another date, or defaulted; each such field is named in
    the returned tuple instead of being replaced silently (audit F-087).
    """
    inferred: list[str] = []

    issue_raw = fields.get("ISSUE DATE") or fields.get("ISSUED") or fields.get("DATE") or ""
    issue_dt = _parse_dt(issue_raw)
    if issue_dt is None:
        inferred.append("issue date")
        issue_dt = _extract_datetime(text) or datetime.now(UTC)

    start_raw = (
        fields.get("EFFECTIVE START") or fields.get("START") or
        fields.get("WINDOW START") or fields.get("BEGIN") or ""
    )
    start_dt = _parse_dt(start_raw)
    if start_dt is None:
        inferred.append("effective start")
        start_dt = _extract_datetime(text) or issue_dt

    end_raw = (
        fields.get("EFFECTIVE END") or fields.get("END") or
        fields.get("WINDOW END") or fields.get("STOP") or ""
    )
    end_dt = _parse_dt(end_raw)
    if end_dt is None:
        # Default: window of 24h if not specified
        inferred.append("effective end")
        end_dt = start_dt + timedelta(hours=24.0)

    return issue_dt, start_dt, end_dt, tuple(inferred)


def _fields(text: str) -> dict[str, str]:
    """The message's "key: value" lines, keys upper-cased."""
    fields: dict[str, str] = {}
    for line in text.strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().upper()] = val.strip()
    return fields


def _norad_id_of(fields: dict[str, str], text: str) -> int | None:
    """The catalogue number from its own field, else a labelled one in the text."""
    norad_raw = (
        fields.get("SATNO") or fields.get("SAT NO") or
        fields.get("NORAD ID") or fields.get("NORAD") or
        fields.get("CATALOG NO") or ""
    )
    m = re.search(r"\d+", norad_raw)
    return int(m.group()) if m else _extract_norad_id(text)


def _predicted_dv(fields: dict[str, str], text: str) -> float | None:
    """Predicted ΔV from its own field, else from the text (audit F-086)."""
    dv_field = fields.get("PREDICTED DV") or fields.get("DELTA-V")
    dv = _extract_delta_v(dv_field, bare=True) if dv_field else None
    return dv if dv is not None else _extract_delta_v(text)


def _parse_single_notso(text: str, index: int = 0) -> NOTSORecord | None:
    """Parse a single NOTSO message block."""
    fields = _fields(text)

    # Message ID
    msg_id = (
        fields.get("MSGID") or fields.get("MESSAGE ID") or
        fields.get("MESSAGE_ID") or f"NOTSO-{index+1:04d}"
    )

    norad_id = _norad_id_of(fields, text)
    if norad_id is None:
        return None  # Can't correlate without NORAD ID

    # Issuing entity
    issuer = (
        fields.get("ISSUER") or fields.get("ISSUED BY") or
        fields.get("OPERATOR") or fields.get("FROM") or "UNKNOWN"
    )

    issue_dt, start_dt, end_dt, inferred = _notso_dates(fields, text)

    # Type
    type_raw = fields.get("TYPE") or fields.get("ACTIVITY TYPE") or text
    notso_type = _infer_notso_type(type_raw)

    # Description
    description = (
        fields.get("DESCRIPTION") or fields.get("REMARKS") or
        fields.get("COMMENT") or text[:500]
    )

    dv = _predicted_dv(fields, text)

    direction = (
        fields.get("DIRECTION") or fields.get("BURN DIRECTION") or None
    )

    return NOTSORecord(
        message_id=str(msg_id).strip(),
        norad_id=norad_id,
        international_designator=fields.get("INTL DESIG") or fields.get("COSPAR") or None,
        object_name=fields.get("OBJECT NAME") or fields.get("OBJECT") or None,
        issuing_entity=issuer,
        issue_date_utc=issue_dt,
        effective_start_utc=start_dt,
        effective_end_utc=end_dt,
        notso_type=notso_type,
        description=description.strip(),
        predicted_delta_v_km_s=dv,
        predicted_direction=direction,
        raw_message=text,
        inferred_fields=inferred,
    )


# ── Correlation engine ────────────────────────────────────────────────────────

def correlate_notsos_with_manoeuvres(
    notsos: list[NOTSORecord],
    manoeuvres: list[Any],     # list[Manoeuvre] from pattern_of_life
    norad_id: int,
    time_tolerance_hours: float = 24.0,
) -> list[NOTSOManoeuvreCorrelation]:
    """Correlate NOTSOs with detected manoeuvres for a single object.

    Matching logic
    --------------
    1. A NOTSO matches a manoeuvre if the manoeuvre's burn window overlaps
       [effective_start − tolerance, effective_end + tolerance]. The burn
       window is the measured burn epoch, or when the burn could not be dated
       the bracket between the element sets either side. The after-element-set
       epoch alone can lag the burn by the whole gap, which reported notified
       burns as silent (audit F-027).
    2. Pairs are assigned closest first: of every NOTSO-manoeuvre pair within
       tolerance, the one whose burn window lies nearest the NOTSO window
       midpoint is taken, then the next, each NOTSO and manoeuvre used once
       (ties go to the earlier window). The time offset is measured to the
       point of the burn window nearest that midpoint.
    3. Unmatched NOTSOs → "notso_only" (filed but no manoeuvre detected).
    4. Unmatched manoeuvres → "manoeuvre_only" (no corresponding NOTSO).
    """
    tolerance = timedelta(hours=time_tolerance_hours)

    obj_notsos     = sorted(
        [n for n in notsos if n.norad_id == norad_id],
        key=lambda n: n.effective_start_utc,
    )
    obj_manoeuvres = sorted(
        [m for m in manoeuvres if m.tle_after.sma_km > 0],  # basic sanity
        key=lambda m: m.epoch,
    )

    # Pair closest first: every NOTSO-manoeuvre pair within tolerance, ordered
    # by the burn's distance from the NOTSO window midpoint, each side used
    # once. Walking the NOTSOs in start order let an early, wide notice claim
    # a burn a later notice's window fits better (audit F-092).
    pairing = _closest_first(obj_notsos, obj_manoeuvres, tolerance)
    matched_mnv = {id(m) for m in pairing.values()}
    correlations: list[NOTSOManoeuvreCorrelation] = [
        _matched(notso, pairing[id(notso)]) if id(notso) in pairing else NOTSOManoeuvreCorrelation(
            notso=notso,
            manoeuvre=None,
            correlation_type="notso_only",
            time_offset_hours=None,
            magnitude_ratio=None,
            notes="NOTSO filed but no manoeuvre detected in TLE analysis",
        )
        for notso in obj_notsos
    ]

    # Unmatched manoeuvres
    for m in obj_manoeuvres:
        if id(m) not in matched_mnv:
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=None,
                manoeuvre=m,
                correlation_type="manoeuvre_only",
                time_offset_hours=None,
                magnitude_ratio=None,
                notes="Manoeuvre detected without any associated NOTSO",
            ))

    return correlations


# Below this detected ΔV (km/s) a predicted-to-detected ratio is meaningless.
_MIN_DETECTED_DV_KM_S = 1e-9


def _midpoint(notso: NOTSORecord) -> datetime:
    return notso.effective_start_utc + (notso.effective_end_utc - notso.effective_start_utc) / 2


def _closest_first(
    notsos: list[NOTSORecord], manoeuvres: list[Any], tolerance: timedelta,
) -> dict[int, Any]:
    """Map id(notso) to its manoeuvre, assigning the closest pairs first."""
    candidates = []
    for notso in notsos:
        window_start = notso.effective_start_utc - tolerance
        window_end = notso.effective_end_utc + tolerance
        mid = _midpoint(notso)
        for order, m in enumerate(manoeuvres):
            lo, hi = _burn_window(m)
            if lo <= window_end and hi >= window_start:
                distance = abs((_nearest(m, mid) - mid).total_seconds())
                candidates.append((distance, notso.effective_start_utc, order, notso, m))
    pairing: dict[int, Any] = {}
    used: set[int] = set()
    for _, _, _, notso, m in sorted(candidates, key=lambda c: c[:3]):
        if id(notso) not in pairing and id(m) not in used:
            pairing[id(notso)] = m
            used.add(id(m))
    return pairing


def _matched(notso: NOTSORecord, best: Any) -> NOTSOManoeuvreCorrelation:
    """The correlation row for a NOTSO paired with a manoeuvre."""
    burn_at = _nearest(best, _midpoint(notso))
    offset_h = (notso.effective_start_utc - burn_at).total_seconds() / 3600.0
    lead_h = (burn_at - notso.issue_date_utc).total_seconds() / 3600.0
    mag_ratio = None
    if notso.predicted_delta_v_km_s and best.delta_v_km_s > _MIN_DETECTED_DV_KM_S:
        mag_ratio = notso.predicted_delta_v_km_s / best.delta_v_km_s
    return NOTSOManoeuvreCorrelation(
        notso=notso,
        manoeuvre=best,
        correlation_type="matched",
        time_offset_hours=round(offset_h, 2),
        magnitude_ratio=round(mag_ratio, 3) if mag_ratio else None,
        lead_time_hours=round(lead_h, 2),
    )


def _burn_window(m: Any) -> tuple[datetime, datetime]:
    """The manoeuvre's burn window, or its epoch for an object that has none."""
    window = getattr(m, "burn_window", None)
    return window if window is not None else (m.epoch, m.epoch)


def _nearest(m: Any, when: datetime) -> datetime:
    """The point of the manoeuvre's burn window nearest *when*."""
    lo, hi = _burn_window(m)
    return min(max(when, lo), hi)


# ── Behaviour profile extraction ──────────────────────────────────────────────

# Lead-time scatter below which an operator's notification timing is called
# predictable. A tuned figure, not a sourced one.
_PREDICTABLE_LEAD_STD_H = 6.0

# Smallest sample a spread may be quoted from: a standard deviation over a
# single observation is not a spread, it is zero information.
_MIN_SAMPLES_FOR_STD = 2

# Band edges on the notification rate, which is counted over REPORTABLE
# manoeuvres only: rate > _CONSISTENT_NOTIFIER_RATE is a consistent notifier,
# rate < _LOW_NOTIFIER_RATE is a low notification rate, and the inclusive span
# between them is an inconsistent notifier. Named because the same two figures
# decide three flags, and as bare numbers at the call site it was not visible
# that the middle band closes on both edges and so leaves no gap.
_CONSISTENT_NOTIFIER_RATE = 0.90
_LOW_NOTIFIER_RATE        = 0.30


def _dv(c: NOTSOManoeuvreCorrelation) -> float:
    return float(getattr(c.manoeuvre, "delta_v_km_s", 0.0) or 0.0)


def _split_by_reportability(
    matched: list[NOTSOManoeuvreCorrelation],
    mnv_only: list[NOTSOManoeuvreCorrelation],
    reportable_threshold_km_s: float | None,
) -> tuple[list[NOTSOManoeuvreCorrelation], list[NOTSOManoeuvreCorrelation], int]:
    """Split detected manoeuvres into those a notice was expected for and the rest.

    With no threshold supplied, everything comes back as reportable and nothing
    sits below it, which is what leaves the rate computed over every detected
    manoeuvre and the behaviour bands withheld by the caller.
    """
    if reportable_threshold_km_s is None:
        return matched, mnv_only, 0

    reportable_matched = [c for c in matched if _dv(c) >= reportable_threshold_km_s]
    reportable_missing = [c for c in mnv_only if _dv(c) >= reportable_threshold_km_s]
    below_threshold = (len(matched) + len(mnv_only)
                       - len(reportable_matched) - len(reportable_missing))
    return reportable_matched, reportable_missing, below_threshold


def _mean_and_std(values: list[float]) -> tuple[float | None, float | None]:
    """Sample mean and sample standard deviation, each None when unavailable."""
    mean = sum(values) / len(values) if values else None
    std = None
    if len(values) >= _MIN_SAMPLES_FOR_STD and mean is not None:
        import math
        _mean: float = mean
        variance = sum((x - _mean) ** 2 for x in values) / (len(values) - 1)
        std = math.sqrt(variance)
    return mean, std


def _window_accuracy_rate(matched: list[NOTSOManoeuvreCorrelation]) -> float:
    """Fraction of matched manoeuvres whose epoch fell inside the NOTSO window.

    Inside the stated window itself, not merely within the correlation
    tolerance that paired the two in the first place.
    """
    window_hits = 0
    for c in matched:
        mnv_epoch = getattr(c.manoeuvre, "epoch", None)
        if (
            c.notso
            and c.manoeuvre
            and mnv_epoch is not None
            and c.notso.effective_start_utc <= mnv_epoch <= c.notso.effective_end_utc
        ):
            window_hits += 1
    return window_hits / len(matched) if matched else 0.0


def _undetected_notso_types(notso_only: list[NOTSOManoeuvreCorrelation]) -> dict[str, int]:
    """Count, by NOTSO type, the notices with no detection beside them."""
    undetected_types: dict[str, int] = {}
    for c in notso_only:
        if c.notso:
            t = c.notso.notso_type.value
            undetected_types[t] = undetected_types.get(t, 0) + 1
    return undetected_types


# PLR0913, PLR0917: six inputs, and each is a separate question the profile
# has to answer: whose behaviour, over which correlations, across what window,
# and what counts as reportable. Grouping them into a holder would hide that
# the window and the threshold are independent of each other, and every call
# site passes all six by keyword already.
def extract_behaviour_profile(  # noqa: PLR0913, PLR0917
    norad_id: int,
    correlations: list[NOTSOManoeuvreCorrelation],
    analysis_start: datetime,
    analysis_end: datetime,
    reportable_threshold_km_s: float | None = None,
    min_reportable_for_behaviour: int = 3,
) -> OperatorBehaviourProfile:
    """Aggregate correlations into an OperatorBehaviourProfile.

    *reportable_threshold_km_s* is the ΔV below which a manoeuvre would not be
    expected to carry a NOTSO. Notices follow human-in-the-loop analysis and
    are deliberately withheld for small, routine burns so the channel is not
    flooded with inconsequential traffic, so a routine station-keeping
    manoeuvre carries no notice and its absence says nothing about the
    operator. Scoring the notification rate over every detected manoeuvre
    therefore measured how much routine station-keeping an object does, not how
    forthcoming its operator is, and put a compliant operator in the lowest
    band. Pass the routine per-burn ceiling for the object's regime; without it
    the rate is computed over everything and the behaviour bands are withheld.

    *min_reportable_for_behaviour* is the smallest number of reportable
    manoeuvres from which a behavioural band will be offered at all. One
    unreported burn out of one is not a pattern.
    """
    matched  = [c for c in correlations if c.correlation_type == "matched"]
    notso_only = [c for c in correlations if c.correlation_type == "notso_only"]
    mnv_only   = [c for c in correlations if c.correlation_type == "manoeuvre_only"]

    total_mnv     = len(matched) + len(mnv_only)
    with_notso    = len(matched)
    without_notso = len(mnv_only)

    reportable_matched, reportable_missing, below_threshold = _split_by_reportability(
        matched, mnv_only, reportable_threshold_km_s,
    )

    reportable = len(reportable_matched) + len(reportable_missing)
    notif_rate = len(reportable_matched) / reportable if reportable > 0 else 0.0
    assessable = (reportable >= min_reportable_for_behaviour
                  and reportable_threshold_km_s is not None)

    # Lead times: burn minus issue date, positive when the notice came first.
    lead_times = [c.lead_time_hours for c in matched if c.lead_time_hours is not None]
    mean_lt, std_lt = _mean_and_std(lead_times)

    # Magnitude accuracy
    ratios = [c.magnitude_ratio for c in matched if c.magnitude_ratio is not None]
    mean_mr, std_mr = _mean_and_std(ratios)

    # Window accuracy: manoeuvre fell inside (not just within tolerance)
    window_acc = _window_accuracy_rate(matched)

    # NOTSOs with no detection beside them, by type.
    undetected_types = _undetected_notso_types(notso_only)

    profile = OperatorBehaviourProfile(
        norad_id=norad_id,
        analysis_period_start=analysis_start,
        analysis_period_end=analysis_end,
        total_manoeuvres=total_mnv,
        manoeuvres_with_notso=with_notso,
        manoeuvres_without_notso=without_notso,
        notification_rate=round(notif_rate, 4),
        mean_lead_time_h=round(mean_lt, 2) if mean_lt is not None else None,
        std_lead_time_h=round(std_lt, 2) if std_lt is not None else None,
        min_lead_time_h=round(min(lead_times), 2) if lead_times else None,
        max_lead_time_h=round(max(lead_times), 2) if lead_times else None,
        mean_magnitude_ratio=round(mean_mr, 3) if mean_mr is not None else None,
        std_magnitude_ratio=round(std_mr, 3) if std_mr is not None else None,
        window_accuracy_rate=round(window_acc, 4),
        notso_without_detection_count=len(notso_only),
        notso_without_detection_types=undetected_types,
        reportable_manoeuvres=reportable,
        below_reporting_threshold=below_threshold,
        reporting_threshold_km_s=reportable_threshold_km_s,
        behaviour_unassessable=not assessable,
        consistent_notifier=assessable and notif_rate > _CONSISTENT_NOTIFIER_RATE,
        inconsistent_notifier=(assessable
                               and _LOW_NOTIFIER_RATE <= notif_rate <= _CONSISTENT_NOTIFIER_RATE),
        low_notification_rate=assessable and notif_rate < _LOW_NOTIFIER_RATE,
        predictable_timing=bool(std_lt is not None and std_lt < _PREDICTABLE_LEAD_STD_H),
    )
    return profile
