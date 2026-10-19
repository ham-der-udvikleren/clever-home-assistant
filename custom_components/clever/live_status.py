"""Parsing for the live charging status read directly from Firebase Firestore.

The Clever app stores each account's live charging-session data in Firestore at
`v1-user-data/{firebase_uid}/active-transactions/*`, in the named `user-database`
database. We read that collection over the Firestore REST API with the Firebase ID
token the integration already holds from login (see
`api.async_get_active_transactions`). This module turns the raw Firestore REST JSON
(a typed value envelope) into a flat `LiveChargingStatus` snapshot of the current
session.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Enum values are stored in Firestore exactly as the app's Kotlin enum constant names
# (no @PropertyName overrides), so we compare against those PascalCase strings.
_STATUS_CHARGING = "Charging"
_STRATEGY_BOOST = "Boost"
_SUBSTRATEGY_SESSION = "Session"
_SUBSTRATEGY_TIMEBOX = "Timebox"


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a Firestore RFC3339 `timestampValue` into an aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Firestore can emit up to 9 fractional digits; datetime.fromisoformat (pre-3.11)
    # accepts at most 6, so clamp the fractional part defensively.
    if "." in text:
        head, _, tail = text.partition(".")
        frac = ""
        offset = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                frac += ch
            else:
                offset = tail[i:]
                break
        text = f"{head}.{frac[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _convert(value: dict[str, Any]) -> Any:
    """Convert one Firestore REST `Value` envelope into a native Python value."""
    if "nullValue" in value:
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return None
    if "timestampValue" in value:
        return _parse_timestamp(value["timestampValue"])
    if "mapValue" in value:
        return {k: _convert(v) for k, v in (value["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in value:
        return [_convert(v) for v in (value["arrayValue"].get("values") or [])]
    if "geoPointValue" in value:
        return value["geoPointValue"]
    return None  # bytesValue / referenceValue etc. - unused here


def _document_fields(document: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Firestore REST document's typed fields into a native dict."""
    return {k: _convert(v) for k, v in (document.get("fields") or {}).items()}


def _current_segment(segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the segment that is active right now.

    Both appChargeSegments[] and the plan's segments[] span the whole session
    (past, current and future), so the last entry is usually a future placeholder.
    Pick the last segment whose start time has already arrived instead.
    """
    if not segments:
        return None
    now = datetime.now(timezone.utc)
    current = segments[0]
    for segment in segments:
        start = segment.get("start")
        if isinstance(start, datetime) and start <= now:
            current = segment
        else:
            break
    return current


@dataclass
class LiveChargingStatus:
    """A snapshot of the currently active charging session, from Firestore."""

    session_id: str | None
    charge_point_id: str | None
    session_started_at: datetime | None
    revision_number: int | None
    departure_time: datetime | None
    estimated_finish_time: datetime | None
    power_required: int | None
    based_on_soc: bool
    smart_charging_flow: str | None
    cpms_charging_status: str | None
    is_stop_requested: bool
    total_kwh_delivered: float | None
    status_message: str | None
    status_subtitle: str | None
    segment_state: str | None
    schedule_strategy: str | None
    schedule_sub_strategy: str | None
    schedule_segment_start: datetime | None
    schedule_segment_end: datetime | None
    captured_at: datetime

    @property
    def is_charging(self) -> bool:
        return self.cpms_charging_status == _STATUS_CHARGING

    @property
    def smart_charging_disabled(self) -> bool:
        """Whether smart charging is currently boosted/disabled, per Firestore's own
        plan (the REST API's strategySettings.disabled field does NOT reflect this)."""
        return self.schedule_strategy == _STRATEGY_BOOST

    @property
    def boost_duration_minutes(self) -> int | None:
        """Length of the current timeboxed boost, if any (None for session-long boosts)."""
        if self.schedule_sub_strategy != _SUBSTRATEGY_TIMEBOX:
            return None
        if self.schedule_segment_start is None or self.schedule_segment_end is None:
            return None
        return round((self.schedule_segment_end - self.schedule_segment_start).total_seconds() / 60)


def _select_current_document(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the current session: the transaction with the most recent start time.

    A new session can't begin while another is still charging, so the newest-started
    transaction is always the active one when charging, and otherwise the last session
    (kept around in `active-transactions` until it expires).
    """
    best: dict[str, Any] | None = None
    best_start: datetime | None = None
    for document in documents:
        fields = _document_fields(document)
        start = fields.get("chargingStart") or fields.get("timeStamp")
        if not isinstance(start, datetime):
            # No usable timestamp - only consider it if we have nothing else at all.
            if best is None:
                best = fields
            continue
        if best_start is None or start > best_start:
            best, best_start = fields, start
    return best


def _parse_document(fields: dict[str, Any], captured_at: datetime) -> LiveChargingStatus:
    plan = fields.get("chargingPlan") or {}
    power_required_raw = plan.get("powerRequiredInKwh")
    consumed_wh = fields.get("consumedWh")
    consumption = fields.get("consumption") or {}
    cpms_status = fields.get("cpmsChargingStatus")

    app_segment = _current_segment(plan.get("appChargeSegments") or []) or {}
    title = app_segment.get("appSegmentTitle") or {}
    subtitle = app_segment.get("appSegmentSubtitle") or {}

    plan_segment = _current_segment(plan.get("segments") or []) or {}
    reason = plan_segment.get("reason") or {}

    total_kwh: float | None
    if isinstance(consumed_wh, (int, float)):
        total_kwh = round(consumed_wh / 1000, 3)
    else:
        total_kwh = consumption.get("totalKwh")

    return LiveChargingStatus(
        session_id=fields.get("sessionId"),
        charge_point_id=fields.get("chargePointId"),
        session_started_at=fields.get("chargingStart"),
        revision_number=plan.get("revisionNumber"),
        departure_time=plan.get("departureTime"),
        # Only project a finish time while actually charging - once a session is
        # completed/stopped the plan keeps a stale earliestFinishedAt that would show
        # a bogus countdown.
        estimated_finish_time=(
            plan.get("earliestFinishedAt") if cpms_status == _STATUS_CHARGING else None
        ),
        power_required=int(round(power_required_raw))
        if isinstance(power_required_raw, (int, float))
        else None,
        based_on_soc=bool(plan.get("basedOnSoc")),
        smart_charging_flow=fields.get("smartChargingFlow"),
        cpms_charging_status=cpms_status,
        is_stop_requested=bool(fields.get("isStopRequested")),
        total_kwh_delivered=total_kwh,
        status_message=title.get("en"),
        status_subtitle=subtitle.get("en"),
        segment_state=app_segment.get("appSegmentChargingState"),
        schedule_strategy=reason.get("strategy"),
        schedule_sub_strategy=reason.get("substrategy"),
        schedule_segment_start=plan_segment.get("start"),
        schedule_segment_end=plan_segment.get("end"),
        captured_at=captured_at,
    )


def parse_transactions_response(
    payload: dict[str, Any] | None, captured_at_fallback: datetime
) -> LiveChargingStatus | None:
    """Parse the Firestore REST `active-transactions` collection response.

    Returns the current session as a LiveChargingStatus, or None if there are no
    transactions (nothing has been charged recently).
    """
    if not payload:
        return None
    documents = payload.get("documents") or []
    fields = _select_current_document(documents)
    if not fields:
        return None
    try:
        return _parse_document(fields, captured_at_fallback)
    except Exception:  # noqa: BLE001 - never let a parsing quirk break the coordinator
        _LOGGER.exception("Failed to parse Clever live charging status from Firestore")
        return None
