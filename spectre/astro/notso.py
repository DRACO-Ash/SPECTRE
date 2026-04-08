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


@dataclass
class NOTSOManoeuvreCorrelation:
    """A correlated pair: NOTSO ↔ detected manoeuvre (one or both may be absent)."""

    notso:             NOTSORecord | None
    manoeuvre:         object | None    # Manoeuvre from pattern_of_life
    correlation_type:  str             # "matched" | "notso_only" | "manoeuvre_only"
    time_offset_hours: float | None    # NOTSO effective_start − manoeuvre epoch (h)
    magnitude_ratio:   float | None    # Predicted ΔV / detected ΔV
    notes:             str = ""


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

    # NOTSOs without detected manoeuvres
    phantom_notso_count:    int
    phantom_notso_types:    dict[str, int] = field(default_factory=dict)

    # Behavioural flags
    consistent_notifier:    bool = False   # notification_rate > 0.90
    inconsistent_notifier:  bool = False   # 0.30 ≤ rate ≤ 0.90
    stealth_operator:       bool = False   # rate < 0.30
    predictable_timing:     bool = False   # std_lead_time < 6 h

    def summary(self) -> str:
        rate_pct = f"{self.notification_rate * 100:.0f}%"
        if self.consistent_notifier:
            behaviour = f"consistent notifier ({rate_pct})"
        elif self.stealth_operator:
            behaviour = f"stealth operator — low notification rate ({rate_pct})"
        else:
            behaviour = f"inconsistent notifier ({rate_pct})"

        parts = [
            f"SATNO {self.norad_id}: {behaviour}.",
            f"{self.total_manoeuvres} manoeuvres detected, {self.manoeuvres_with_notso} pre-notified.",
        ]
        if self.mean_lead_time_h is not None:
            parts.append(
                f"Mean notification lead time: {self.mean_lead_time_h:.1f}h"
                + (f" ± {self.std_lead_time_h:.1f}h." if self.std_lead_time_h else ".")
            )
        if self.phantom_notso_count > 0:
            parts.append(f"{self.phantom_notso_count} NOTSO(s) filed with no corresponding detected manoeuvre.")
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
    s = s.strip().rstrip("Z").strip()
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
    """Extract NORAD catalogue number from common NOTSO field patterns."""
    patterns = [
        r"(?:SATNO|SAT\s*NO|NORAD\s*ID|NORAD|CATALOG\s*NO|CATNO)[:\s#]+(\d{4,6})",
        r"(?:OBJECT|OBJ)[:\s]+\d+[^\d].*?(\d{5})",
        r"\b(\d{5})\b",   # Fallback: any 5-digit number
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 999999:
                return val
    return None


def _extract_delta_v(text: str) -> float | None:
    """Extract predicted ΔV magnitude from NOTSO description."""
    patterns = [
        r"(?:delta.?v|dv|delta.v)[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|km/s)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|km/s)\s+(?:burn|manoeuvre|maneuver|impulse)",
    ]
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
    # Also split on "MESSAGE ID:" or "MSGID:" as a reliable separator
    expanded: list[str] = []
    for msg in messages:
        sub = re.split(r"(?:MESSAGE\s*ID|MSGID)\s*:", msg, flags=re.IGNORECASE)
        if len(sub) > 1:
            # Re-prepend the split token
            expanded.append(sub[0])
            for s in sub[1:]:
                expanded.append("MSGID: " + s)
        else:
            expanded.append(msg)
    return [m.strip() for m in expanded if m.strip()]


def parse_notso_text(raw_text: str) -> list[NOTSORecord]:
    """Parse one or more NOTSO messages from free text.

    Handles the common USSPACECOM template format (field: value lines) and
    ISO-formatted structured messages.  Unknown fields are captured in
    *description*.

    Returns
    -------
    list[NOTSORecord]
        Parsed records.  Unparseable messages are skipped with a log warning.
    """
    messages = _split_messages(raw_text)
    records: list[NOTSORecord] = []

    for i, msg in enumerate(messages):
        if not msg.strip():
            continue
        try:
            record = _parse_single_notso(msg, index=i)
            if record is not None:
                records.append(record)
        except Exception as exc:
            logger.warning("NOTSO parse error for message %d: %s", i, exc)

    return records


def _parse_single_notso(text: str, index: int = 0) -> NOTSORecord | None:
    """Parse a single NOTSO message block."""
    lines = text.strip().splitlines()
    fields: dict[str, str] = {}

    # Parse key: value lines
    for line in lines:
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().upper()] = val.strip()

    # Message ID
    msg_id = (
        fields.get("MSGID") or fields.get("MESSAGE ID") or
        fields.get("MESSAGE_ID") or f"NOTSO-{index+1:04d}"
    )

    # NORAD ID
    norad_raw = (
        fields.get("SATNO") or fields.get("SAT NO") or
        fields.get("NORAD ID") or fields.get("NORAD") or
        fields.get("CATALOG NO") or ""
    )
    norad_id = None
    if norad_raw:
        m = re.search(r"\d+", norad_raw)
        if m:
            norad_id = int(m.group())
    if norad_id is None:
        norad_id = _extract_norad_id(text)
    if norad_id is None:
        return None  # Can't correlate without NORAD ID

    # Issuing entity
    issuer = (
        fields.get("ISSUER") or fields.get("ISSUED BY") or
        fields.get("OPERATOR") or fields.get("FROM") or "UNKNOWN"
    )

    # Dates — issue date
    issue_raw = fields.get("ISSUE DATE") or fields.get("ISSUED") or fields.get("DATE") or ""
    issue_dt  = _parse_dt(issue_raw) or _extract_datetime(text) or datetime.now(UTC)

    # Window start
    start_raw = (
        fields.get("EFFECTIVE START") or fields.get("START") or
        fields.get("WINDOW START") or fields.get("BEGIN") or ""
    )
    start_dt = _parse_dt(start_raw) or _extract_datetime(text) or issue_dt

    # Window end
    end_raw = (
        fields.get("EFFECTIVE END") or fields.get("END") or
        fields.get("WINDOW END") or fields.get("STOP") or ""
    )
    end_dt = _parse_dt(end_raw)
    if end_dt is None:
        # Default: window of 24h if not specified
        end_dt = start_dt + timedelta(hours=24.0)

    # Type
    type_raw = fields.get("TYPE") or fields.get("ACTIVITY TYPE") or text
    notso_type = _infer_notso_type(type_raw)

    # Description
    description = (
        fields.get("DESCRIPTION") or fields.get("REMARKS") or
        fields.get("COMMENT") or text[:500]
    )

    # Optional predicted ΔV
    dv = _extract_delta_v(
        fields.get("PREDICTED DV") or fields.get("DELTA-V") or text
    )

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
    )


# ── Correlation engine ────────────────────────────────────────────────────────

def correlate_notsos_with_manoeuvres(
    notsos: list[NOTSORecord],
    manoeuvres: list,     # list[Manoeuvre] from pattern_of_life
    norad_id: int,
    time_tolerance_hours: float = 24.0,
) -> list[NOTSOManoeuvreCorrelation]:
    """Correlate NOTSOs with detected manoeuvres for a single object.

    Matching logic
    --------------
    1. A NOTSO matches a manoeuvre if the manoeuvre epoch falls within
       [effective_start − tolerance, effective_end + tolerance].
    2. Multiple manoeuvre candidates → select closest to window midpoint.
    3. Multiple NOTSO candidates → select closest effective_start.
    4. Unmatched NOTSOs → "notso_only" (filed but no manoeuvre detected).
    5. Unmatched manoeuvres → "manoeuvre_only" (no corresponding NOTSO).
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

    matched_notso_ids: set[str]      = set()
    matched_mnv_epochs: set[datetime] = set()
    correlations: list[NOTSOManoeuvreCorrelation] = []

    # Match each NOTSO to at most one manoeuvre
    for notso in obj_notsos:
        window_start = notso.effective_start_utc - tolerance
        window_end   = notso.effective_end_utc   + tolerance

        candidates = [
            m for m in obj_manoeuvres
            if window_start <= m.epoch <= window_end
            and m.epoch not in matched_mnv_epochs
        ]

        if candidates:
            # Select candidate closest to window midpoint
            midpoint = notso.effective_start_utc + (
                notso.effective_end_utc - notso.effective_start_utc
            ) / 2
            best = min(candidates, key=lambda m: abs((m.epoch - midpoint).total_seconds()))

            offset_h = (
                (notso.effective_start_utc - best.epoch).total_seconds() / 3600.0
            )
            mag_ratio = None
            if notso.predicted_delta_v_km_s and best.delta_v_km_s > 1e-9:
                mag_ratio = notso.predicted_delta_v_km_s / best.delta_v_km_s

            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=best,
                correlation_type="matched",
                time_offset_hours=round(offset_h, 2),
                magnitude_ratio=round(mag_ratio, 3) if mag_ratio else None,
            ))
            matched_notso_ids.add(notso.message_id)
            matched_mnv_epochs.add(best.epoch)
        else:
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=None,
                correlation_type="notso_only",
                time_offset_hours=None,
                magnitude_ratio=None,
                notes="NOTSO filed but no manoeuvre detected in TLE analysis",
            ))
            matched_notso_ids.add(notso.message_id)

    # Unmatched manoeuvres
    for m in obj_manoeuvres:
        if m.epoch not in matched_mnv_epochs:
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=None,
                manoeuvre=m,
                correlation_type="manoeuvre_only",
                time_offset_hours=None,
                magnitude_ratio=None,
                notes="Manoeuvre detected without any associated NOTSO",
            ))

    return correlations


# ── Behaviour profile extraction ──────────────────────────────────────────────

def extract_behaviour_profile(
    norad_id: int,
    correlations: list[NOTSOManoeuvreCorrelation],
    analysis_start: datetime,
    analysis_end: datetime,
) -> OperatorBehaviourProfile:
    """Aggregate correlations into an OperatorBehaviourProfile."""
    matched  = [c for c in correlations if c.correlation_type == "matched"]
    notso_only = [c for c in correlations if c.correlation_type == "notso_only"]
    mnv_only   = [c for c in correlations if c.correlation_type == "manoeuvre_only"]

    total_mnv     = len(matched) + len(mnv_only)
    with_notso    = len(matched)
    without_notso = len(mnv_only)
    notif_rate    = with_notso / total_mnv if total_mnv > 0 else 0.0

    # Lead times (NOTSO effective_start − manoeuvre epoch)
    lead_times = [c.time_offset_hours for c in matched if c.time_offset_hours is not None]
    mean_lt = sum(lead_times) / len(lead_times) if lead_times else None
    std_lt  = None
    if len(lead_times) >= 2:
        import math
        variance = sum((x - mean_lt) ** 2 for x in lead_times) / (len(lead_times) - 1)  # type: ignore[arg-type]
        std_lt = math.sqrt(variance)

    # Magnitude accuracy
    ratios = [c.magnitude_ratio for c in matched if c.magnitude_ratio is not None]
    mean_mr = sum(ratios) / len(ratios) if ratios else None
    std_mr  = None
    if len(ratios) >= 2:
        import math
        var_mr = sum((x - mean_mr) ** 2 for x in ratios) / (len(ratios) - 1)  # type: ignore[arg-type]
        std_mr = math.sqrt(var_mr)

    # Window accuracy: manoeuvre fell inside (not just within tolerance)
    window_hits = 0
    for c in matched:
        if (
            c.notso
            and c.manoeuvre
            and c.notso.effective_start_utc <= c.manoeuvre.epoch <= c.notso.effective_end_utc
        ):
            window_hits += 1
    window_acc = window_hits / len(matched) if matched else 0.0

    # Phantom NOTSOs by type
    phantom_types: dict[str, int] = {}
    for c in notso_only:
        if c.notso:
            t = c.notso.notso_type.value
            phantom_types[t] = phantom_types.get(t, 0) + 1

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
        phantom_notso_count=len(notso_only),
        phantom_notso_types=phantom_types,
        consistent_notifier=notif_rate > 0.90,
        inconsistent_notifier=0.30 <= notif_rate <= 0.90,
        stealth_operator=notif_rate < 0.30,
        predictable_timing=bool(std_lt is not None and std_lt < 6.0),
    )
    return profile
