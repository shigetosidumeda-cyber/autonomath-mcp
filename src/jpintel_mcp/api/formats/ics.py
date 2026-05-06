"""iCalendar renderer (RFC 5545) — ``?format=ics``.

One ``VEVENT`` per row that carries a deadline-bearing key. Recognised
deadline columns (in priority order):

    deadline                      — single ISO-8601 date / datetime
    next_deadline                 — same
    application_deadline          — same
    end_at / valid_to / expires_at — single ISO-8601
    application_period_end        — single ISO-8601

A row with no recognised deadline column produces no VEVENT (it is silently
skipped — the caller should keep filtering to deadline-bearing endpoints).

UID is ``sha256(unified_id || source_fetched_at || deadline_iso)`` so a
re-export of the same calendar with the same row state produces the same
UID — which keeps Apple Calendar / Google Calendar from creating duplicate
events on every refresh. UID is suffixed ``@autonomath.ai`` per RFC 5545.

DTSTART / DTEND use ``TZID=Asia/Tokyo`` because every Japanese government
deadline is JST-based; UTC would render the deadline a day off in Apple
Calendar's compact view. A VTIMEZONE block is embedded so the calendar
file is fully self-contained (Outlook + Apple Calendar both reject lone
TZID references without a matching VTIMEZONE).

We embed the §52 disclaimer in ``X-WR-CALDESC`` (calendar-level) and in
each event's ``DESCRIPTION`` (event-level), so both calendar-list views
and per-event detail views show it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import Response

from jpintel_mcp.api._format_dispatch import (
    BRAND_FOOTER,
    DISCLAIMER_HEADER_VALUE,
    DISCLAIMER_JA,
)

# Asia/Tokyo VTIMEZONE block. Japan has not had DST since 1951 so a single
# fixed STANDARD component covers every event. Embedded literally rather
# than computed because pytz / zoneinfo emit different fragments on
# different platforms — this exact block parses cleanly in Apple Calendar
# 13.0+, Outlook 365, Google Calendar import, and `icalendar` round-trip.
_VTIMEZONE_TOKYO = (
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Asia/Tokyo\r\n"
    "BEGIN:STANDARD\r\n"
    "DTSTART:19510101T000000\r\n"
    "TZOFFSETFROM:+0900\r\n"
    "TZOFFSETTO:+0900\r\n"
    "TZNAME:JST\r\n"
    "END:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
)

# Ordered candidates for a row's deadline column. We pick the first one
# that parses to a valid datetime / date.
_DEADLINE_KEYS: tuple[str, ...] = (
    "deadline",
    "next_deadline",
    "application_deadline",
    "application_period_end",
    "end_at",
    "valid_to",
    "expires_at",
)

_TITLE_KEYS: tuple[str, ...] = (
    "primary_name",
    "name",
    "title",
    "law_title",
    "case_title",
    "ruleset_name",
)


def _ics_escape(s: str) -> str:
    """RFC 5545 §3.3.11 escape: ``\\`` ``;`` ``,`` ``\\n``."""
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _coerce_deadline(v: Any) -> _dt.datetime | None:
    """Accept ISO-8601 date or datetime and return a tz-naive JST datetime.

    Returns ``None`` for unparseable input — the row is silently skipped.
    """
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, _dt.date):
        return _dt.datetime.combine(v, _dt.time(23, 59, 0))
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    # Try datetime first, then date.
    try:
        # `fromisoformat` handles `2026-04-29T17:00:00`, `2026-04-29 17:00`,
        # `2026-04-29T17:00:00+09:00` (3.11+).
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(_dt.timezone(_dt.timedelta(hours=9))).replace(tzinfo=None)
        return d
    except ValueError:
        pass
    try:
        return _dt.datetime.combine(_dt.date.fromisoformat(s), _dt.time(23, 59, 0))
    except ValueError:
        return None


def _row_title(row: dict[str, Any]) -> str:
    for k in _TITLE_KEYS:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(row.get("unified_id") or "(untitled)")


def _row_deadline(row: dict[str, Any]) -> tuple[str, _dt.datetime] | None:
    for k in _DEADLINE_KEYS:
        if k in row:
            d = _coerce_deadline(row.get(k))
            if d is not None:
                return k, d
    return None


def _fmt_dt_local(d: _dt.datetime) -> str:
    """Format as ``YYYYMMDDTHHMMSS`` (no Z, used with TZID=Asia/Tokyo)."""
    return d.strftime("%Y%m%dT%H%M%S")


def _fmt_dt_utc(d: _dt.datetime) -> str:
    """Format as ``YYYYMMDDTHHMMSSZ`` (DTSTAMP is always UTC per §3.8.7.2)."""
    return d.strftime("%Y%m%dT%H%M%SZ")


def _uid(unified_id: str, fetched_at: str | None, deadline: _dt.datetime) -> str:
    raw = f"{unified_id}|{fetched_at or ''}|{deadline.isoformat()}".encode()
    return hashlib.sha256(raw).hexdigest() + "@autonomath.ai"


def render_ics(rows: list[dict[str, Any]], meta: dict[str, Any]) -> Response:
    """Render ``rows`` to RFC 5545 ical.

    A 200 with zero VEVENTs is still valid — calendar clients accept an
    empty calendar — but we set ``X-AutonoMath-Empty: 1`` so the round-trip
    test can flag it.
    """
    # icalendar lib is the canonical RFC 5545 emitter. It auto-handles line
    # folding (75-byte CRLF folds), VCALENDAR/VEVENT envelope, and ESCAPE
    # behaviours — we still escape DESCRIPTION manually because we want
    # control over multi-line layout.
    try:
        from icalendar import Calendar, Event
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("format=ics requires the 'icalendar' dep — pip install icalendar"),
        ) from exc

    cal = Calendar()
    cal.add("prodid", "-//Bookyou株式会社//AutonoMath//JA")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", meta.get("endpoint", "AutonoMath"))
    cal.add("x-wr-caldesc", DISCLAIMER_JA + " | " + BRAND_FOOTER)
    cal.add("x-wr-timezone", "Asia/Tokyo")

    now_utc = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    n_events = 0
    for row in rows:
        d = _row_deadline(row)
        if d is None:
            continue
        _key, deadline = d
        title = _row_title(row)
        unified_id = str(row.get("unified_id") or "")
        fetched_at = row.get("source_fetched_at")
        url = row.get("source_url")
        license_ = row.get("license") or ""

        ev = Event()
        ev.add("uid", _uid(unified_id, fetched_at, deadline))
        ev.add("summary", title)
        # Attach DTSTART/DTEND with TZID=Asia/Tokyo (matches the embedded
        # VTIMEZONE block). icalendar honours `tzinfo` on a datetime to
        # emit `DTSTART;TZID=Asia/Tokyo:YYYYMMDDTHHMMSS`. A naive datetime
        # would render as a "floating" time which Apple Calendar / Google
        # interpret in the viewer's local zone — wrong for JP deadlines.
        try:
            from zoneinfo import ZoneInfo

            _jst = ZoneInfo("Asia/Tokyo")
        except Exception:  # pragma: no cover — zoneinfo always available 3.9+
            _jst = _dt.timezone(_dt.timedelta(hours=9))
        deadline_tz = deadline.replace(tzinfo=_jst)
        ev.add("dtstart", deadline_tz)
        ev.add("dtend", deadline_tz + _dt.timedelta(minutes=30))
        ev.add("dtstamp", now_utc)
        if url:
            ev.add("url", url)
        # icalendar handles RFC 5545 §3.3.11 escaping of \n / \, / \;.
        # Pass real newlines (\n) here — passing the literal "\\n" would
        # double-escape and the rendered DESCRIPTION would show "\n" as
        # text in Apple Calendar's compact view (actual bug found
        # 2026-04-29 — the source previously used `\\n` strings).
        ev.add(
            "description",
            (
                f"{DISCLAIMER_JA}\n\n"
                f"unified_id: {unified_id}\n"
                f"license: {license_}\n"
                f"source: {url or ''}\n"
                f"出典取得: {fetched_at or ''}\n"
                f"— {BRAND_FOOTER}"
            ),
        )
        cal.add_component(ev)
        n_events += 1

    body = cal.to_ical()
    # icalendar.Calendar.to_ical does not embed the VTIMEZONE block by
    # default when we pass naive datetimes. Splice the Asia/Tokyo block
    # in right after the calendar header.
    text = body.decode("utf-8")
    text = text.replace("METHOD:PUBLISH\r\n", "METHOD:PUBLISH\r\n" + _VTIMEZONE_TOKYO, 1)

    filename = f"{meta.get('filename_stem', 'autonomath_export')}.ics"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AutonoMath-Disclaimer": DISCLAIMER_HEADER_VALUE,
            "X-AutonoMath-Format": "ics",
            "X-AutonoMath-Empty": "1" if n_events == 0 else "0",
            "X-AutonoMath-Event-Count": str(n_events),
        },
    )
