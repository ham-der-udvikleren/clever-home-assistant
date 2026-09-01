"""Parsing for the optional live-status add-on's /status endpoint.

The add-on (a Frida-instrumented Android emulator sidecar) exposes the *raw*
Kotlin/Java `toString()` output of Clever's own internal domain objects, not a
clean JSON API - so this module extracts just the fields we need with targeted
regexes rather than attempting a full generic parse of that format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

ACTIVE_TRANSACTION_KEY = "dk.clever.data.transaction.domain.ActiveTransaction"

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
# Matches Java's Date.toString() format, e.g. "Thu Aug 27 05:15:00 UTC 2026".
_JAVA_DATE_RE = r"\w{3} (\w{3}) (\d{1,2}) (\d{2}):(\d{2}):(\d{2}) \S+ (\d{4})"

_SESSION_ID_RE = re.compile(r"sessionId=([^,]+)")
_CHARGE_POINT_ID_RE = re.compile(r"chargePointId=(\d+)")
_START_TIMESTAMP_RE = re.compile(r"startTimestamp=(\d+)")
_REVISION_RE = re.compile(r"revisionNumber=(\d+)")
_DEPARTURE_TIME_RE = re.compile(r"departureTime=" + _JAVA_DATE_RE)
_EARLIEST_FINISHED_RE = re.compile(r"earliestFinishedAt=" + _JAVA_DATE_RE)
_POWER_REQUIRED_RE = re.compile(r"powerRequired=(\d+)")
_BASED_ON_SOC_RE = re.compile(r"basedOnSoc=(true|false)")
_SMART_CHARGING_FLOW_RE = re.compile(r"smartChargingFlow=(\w+)")
_CPMS_CHARGING_STATUS_RE = re.compile(r"cpmsChargingStatus=(\w+)")
_IS_STOP_REQUESTED_RE = re.compile(r"isStopRequested=(true|false)")
_TOTAL_KWH_RE = re.compile(r"totalKwh=([\d.]+)")

_APP_CHARGE_SEGMENT_MARKER = "AppChargeSegment("
_SEGMENT_STATE_RE = re.compile(r"appSegmentChargingState=(\w+)")
_SEGMENT_START_RE = re.compile(r"start=" + _JAVA_DATE_RE)
# The ChargingPlan carries its own construction-time clock (repeated on several nested
# fields, all identical) - more trustworthy than our own wall clock for deciding which
# planned segment is "now", since the two can drift if the add-on's data is stale.
_CURRENT_TIME_RE = re.compile(r"currentTime=(\d+)")
# Non-greedy ".*?" for the "da=" value (not "[^,]*") because Danish decimal numbers
# use a comma (e.g. "2,39 kWh"), which would otherwise break a comma-terminated match.
_TITLE_EN_RE = re.compile(r"appSegmentTitle=LocalizedText\(da=.*?, en=(.*?), se=")
_SUBTITLE_EN_RE = re.compile(r"appSegmentSubtitle=LocalizedText\(da=.*?, en=(.*?), se=")

# ChargingPlan.schedule[] - the *actual* smart-charging decision engine's plan. Confirmed
# by testing (2026-09-01): the REST API's strategySettings.disabled field does NOT
# reflect boost/disable state (stayed "enabled" the whole time a 1h boost was
# active) - this schedule is the only source that does, via strategy=BOOST segments.
_SCHEDULE_SEGMENT_MARKER = "ChargingPlanSegment("
_SCHEDULE_START_RE = re.compile(r"startDate=" + _JAVA_DATE_RE)
_SCHEDULE_END_RE = re.compile(r"endDate=(?:null|" + _JAVA_DATE_RE + r")")
_SCHEDULE_STRATEGY_RE = re.compile(r"strategy=(\w+)")
_SCHEDULE_SUBSTRATEGY_RE = re.compile(r"subStrategy=(\w+)")


def _parse_java_date(match: re.Match[str]) -> datetime:
    month_abbr, day, hour, minute, second, year = match.groups()
    return datetime(
        int(year), _MONTHS[month_abbr], int(day), int(hour), int(minute), int(second),
        tzinfo=timezone.utc,
    )


def _find_all_blocks(text: str, marker: str) -> list[str]:
    """Extract every "<marker>...)" block (balancing parens), in order. `marker` must end in '('."""
    blocks: list[str] = []
    search_from = 0
    while True:
        start = text.find(marker, search_from)
        if start == -1:
            return blocks
        depth = 0
        end = None
        for i in range(start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            return blocks
        blocks.append(text[start : end + 1])
        search_from = end + 1


def _extract_current_block(text: str, marker: str, start_re: re.Pattern[str]) -> str | None:
    """Pick the "<marker>...)" block that's actually active right now.

    Both ChargingPlan.schedule[] and .appChargeSegments[] cover the *entire* planned
    session - past, current, and future segments all the way past the departure time
    (including trailing placeholders with an open-ended `end=null`) - so the
    textually-last entry is usually a future placeholder, not the currently active
    one. Pick the last block whose start time has actually arrived instead.
    """
    blocks = _find_all_blocks(text, marker)
    if not blocks:
        return None

    current_time_match = _CURRENT_TIME_RE.search(text)
    if not current_time_match:
        return blocks[-1]
    now = int(current_time_match.group(1)) / 1000

    current = blocks[0]
    for block in blocks:
        start_match = start_re.search(block)
        if start_match and _parse_java_date(start_match).timestamp() <= now:
            current = block
        else:
            break
    return current


@dataclass
class LiveChargingStatus:
    """A snapshot of the currently active charging session, from the add-on."""

    session_id: str
    charge_point_id: str
    session_started_at: datetime | None
    revision_number: int
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
        return self.cpms_charging_status == "CHARGING"

    @property
    def smart_charging_disabled(self) -> bool:
        """Whether smart charging is currently boosted/disabled, per Firestore's own
        schedule (the REST API's strategySettings.disabled field does NOT reflect this -
        confirmed by testing on 2026-09-01, it stayed "enabled" through an active boost).
        """
        return self.schedule_strategy == "BOOST"

    @property
    def boost_duration_minutes(self) -> int | None:
        """Length of the current timeboxed boost, if any (None for session-long boosts)."""
        if self.schedule_sub_strategy != "TIMEBOX":
            return None
        if self.schedule_segment_start is None or self.schedule_segment_end is None:
            return None
        return round((self.schedule_segment_end - self.schedule_segment_start).total_seconds() / 60)


def parse_status_response(payload: dict, captured_at_fallback: datetime) -> LiveChargingStatus | None:
    """Parse the JSON returned by the add-on's /status endpoint."""
    entry = payload.get(ACTIVE_TRANSACTION_KEY)
    if not entry or not entry.get("text"):
        return None

    text = entry["text"]
    session_id_match = _SESSION_ID_RE.search(text)
    charge_point_match = _CHARGE_POINT_ID_RE.search(text)
    revision_match = _REVISION_RE.search(text)
    if not (session_id_match and charge_point_match and revision_match):
        return None

    start_timestamp_match = _START_TIMESTAMP_RE.search(text)
    departure_match = _DEPARTURE_TIME_RE.search(text)
    earliest_finished_match = _EARLIEST_FINISHED_RE.search(text)
    power_required_match = _POWER_REQUIRED_RE.search(text)
    based_on_soc_match = _BASED_ON_SOC_RE.search(text)
    smart_flow_match = _SMART_CHARGING_FLOW_RE.search(text)
    cpms_status_match = _CPMS_CHARGING_STATUS_RE.search(text)
    stop_requested_match = _IS_STOP_REQUESTED_RE.search(text)
    total_kwh_match = _TOTAL_KWH_RE.search(text)

    current_segment = _extract_current_block(text, _APP_CHARGE_SEGMENT_MARKER, _SEGMENT_START_RE)
    segment_state_match = _SEGMENT_STATE_RE.search(current_segment) if current_segment else None
    segment_state = segment_state_match.group(1) if segment_state_match else None
    title_match = _TITLE_EN_RE.search(current_segment) if current_segment else None
    subtitle_match = _SUBTITLE_EN_RE.search(current_segment) if current_segment else None

    current_schedule = _extract_current_block(text, _SCHEDULE_SEGMENT_MARKER, _SCHEDULE_START_RE)
    schedule_strategy_match = _SCHEDULE_STRATEGY_RE.search(current_schedule) if current_schedule else None
    schedule_substrategy_match = _SCHEDULE_SUBSTRATEGY_RE.search(current_schedule) if current_schedule else None
    schedule_start_match = _SCHEDULE_START_RE.search(current_schedule) if current_schedule else None
    schedule_end_match = _SCHEDULE_END_RE.search(current_schedule) if current_schedule else None
    # The endDate alternation also matches the literal "null" - group(1) (the month
    # abbreviation) only gets populated when a real date matched.
    schedule_end_is_real_date = bool(schedule_end_match and schedule_end_match.group(1))

    try:
        captured_at = datetime.fromisoformat(entry["captured_at"])
    except (KeyError, ValueError):
        captured_at = captured_at_fallback

    return LiveChargingStatus(
        session_id=session_id_match.group(1),
        charge_point_id=charge_point_match.group(1),
        session_started_at=(
            datetime.fromtimestamp(int(start_timestamp_match.group(1)) / 1000, tz=timezone.utc)
            if start_timestamp_match
            else None
        ),
        revision_number=int(revision_match.group(1)),
        departure_time=_parse_java_date(departure_match) if departure_match else None,
        # Once the car itself has ended the session (segment_state ERROR, e.g. "Charging
        # stopped by your car"), Clever's own plan keeps projecting a finish time as if
        # charging will resume shortly - confirmed stale/misleading by testing, so drop it
        # rather than show a bogus countdown.
        estimated_finish_time=(
            _parse_java_date(earliest_finished_match)
            if earliest_finished_match and segment_state != "ERROR"
            else None
        ),
        power_required=int(power_required_match.group(1)) if power_required_match else None,
        based_on_soc=(based_on_soc_match.group(1) == "true") if based_on_soc_match else False,
        smart_charging_flow=smart_flow_match.group(1) if smart_flow_match else None,
        cpms_charging_status=cpms_status_match.group(1) if cpms_status_match else None,
        is_stop_requested=(stop_requested_match.group(1) == "true") if stop_requested_match else False,
        total_kwh_delivered=float(total_kwh_match.group(1)) if total_kwh_match else None,
        status_message=title_match.group(1) if title_match else None,
        status_subtitle=subtitle_match.group(1) if subtitle_match else None,
        segment_state=segment_state,
        schedule_strategy=schedule_strategy_match.group(1) if schedule_strategy_match else None,
        schedule_sub_strategy=(
            schedule_substrategy_match.group(1) if schedule_substrategy_match else None
        ),
        schedule_segment_start=_parse_java_date(schedule_start_match) if schedule_start_match else None,
        schedule_segment_end=(
            _parse_java_date(schedule_end_match) if schedule_end_is_real_date else None
        ),
        captured_at=captured_at,
    )
