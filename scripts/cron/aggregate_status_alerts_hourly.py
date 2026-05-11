"""Wave 41 Agent H — hourly status alert aggregator.

Combines the 5 specialty dashboards' snapshot files into a single
``analytics/status_alerts_w41.jsonl`` rolling log, refreshes the
``site/status/feed.atom`` ATOM feed, and (optionally) posts the critical
alerts to a Telegram bot.

Inputs (all best-effort; missing files degrade to ``unknown`` level):

* ``site/status/rum.json``                 — Wave 16 RUM aggregator
* ``site/status/status.json``              — Wave 20 9-axis status_probe
* ``analytics/six_axis_status.json``       — Wave 38 6-axis sanity
* ``analytics/freshness_rollup.json``      — Wave 37 freshness rollup
* ``analytics/cron_health_24h.json``       — derived 24h cron health

Outputs:

* ``analytics/status_alerts_w41.jsonl``    — append-only JSONL of every
  alert emitted (one line per alert; severity-tagged).
* ``site/status/feed.atom``                — refreshed ATOM feed of the
  most recent 50 alerts (XML, no JS).
* ``site/status/status_alerts_w41.json``   — sidecar JSON for the REST
  ``/v1/status/alerts`` endpoint to read.

Constraints (Wave 41):

* Zero LLM API calls. Pure JSON / XML I/O + stdlib only.
* No data loss: input snapshots are read-only; outputs are
  rotation-friendly (jsonl append + atom trim to 50).
* Telegram is optional — ``TG_BOT_TOKEN`` / ``TG_CHAT_ID`` env vars gate
  the post. When unset the script logs ``telegram=skip`` and exits 0.
* honest-null: when a snapshot is missing the level is ``unknown`` (not
  ``critical``) so a missing daily probe does not page the operator.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.sax.saxutils as _saxutils
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_STATUS = REPO_ROOT / "site" / "status"
ANALYTICS = REPO_ROOT / "analytics"

ALERT_JSONL = ANALYTICS / "status_alerts_w41.jsonl"
SIDECAR_JSON = SITE_STATUS / "status_alerts_w41.json"
FEED_ATOM = SITE_STATUS / "feed.atom"

# Maximum ATOM entries to retain (older entries are trimmed each run).
ATOM_MAX_ENTRIES = 50

# Levels are ordered by severity ascending — used to compare alerts and to
# decide whether the Telegram post should fire.
SEVERITY_ORDER = ("unknown", "info", "warn", "critical")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _judge_rum(rum: dict[str, Any] | None) -> dict[str, Any]:
    if not rum:
        return {"axis": "rum", "level": "unknown", "summary": "rum.json not found"}
    days = rum.get("days") or []
    latest = next((d for d in reversed(days) if (d or {}).get("samples", 0)), None)
    if not latest:
        return {"axis": "rum", "level": "info", "summary": "no RUM samples in window"}
    lcp = latest.get("lcp")
    inp = latest.get("inp")
    cls = latest.get("cls")
    thresholds = rum.get("p75_thresholds") or {}
    level = "info"
    breaches = []
    if isinstance(lcp, (int, float)) and lcp > thresholds.get("lcp", {}).get("warn", 4000):
        breaches.append(f"LCP={lcp}")
        level = "warn"
    if isinstance(inp, (int, float)) and inp > thresholds.get("inp", {}).get("warn", 500):
        breaches.append(f"INP={inp}")
        level = "warn"
    if isinstance(cls, (int, float)) and cls > thresholds.get("cls", {}).get("warn", 0.25):
        breaches.append(f"CLS={cls}")
        level = "warn"
    summary = (
        f"RUM p75 latest day: LCP={lcp}ms INP={inp}ms CLS={cls}"
        + (f" — breach: {', '.join(breaches)}" if breaches else "")
    )
    return {"axis": "rum", "level": level, "summary": summary}


def _judge_status_components(status: dict[str, Any] | None) -> dict[str, Any]:
    if not status:
        return {"axis": "audit", "level": "unknown", "summary": "status.json not found"}
    comps = (status.get("components") or {})
    down = [k for k, v in comps.items() if (v or {}).get("status") == "down"]
    degraded = [k for k, v in comps.items() if (v or {}).get("status") == "degraded"]
    if down:
        level = "critical"
        summary = f"components DOWN: {', '.join(sorted(down))}"
    elif degraded:
        level = "warn"
        summary = f"components degraded: {', '.join(sorted(degraded))}"
    else:
        level = "info"
        summary = f"all {len(comps)} components ok"
    return {"axis": "audit", "level": level, "summary": summary}


def _judge_six_axis(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {"axis": "six_axis", "level": "unknown", "summary": "six_axis_status.json not found"}
    axes = report.get("axes") or []
    failing = []
    for axis in axes:
        for sub in (axis.get("sub_axes") or []):
            if (sub or {}).get("sla_status") == "fail":
                failing.append(f"{axis.get('id')}/{sub.get('id')}")
    if failing:
        return {
            "axis": "six_axis",
            "level": "critical",
            "summary": f"6-axis SLA fail: {', '.join(failing[:5])}"
            + (f" (+{len(failing) - 5} more)" if len(failing) > 5 else ""),
        }
    return {"axis": "six_axis", "level": "info", "summary": "6-axis SLA all green or unknown"}


def _judge_freshness(rollup: dict[str, Any] | None) -> dict[str, Any]:
    if not rollup:
        return {"axis": "freshness", "level": "unknown", "summary": "freshness rollup not found"}
    breaches = []
    for axis_id, axis in (rollup.get("axes") or {}).items():
        if isinstance(axis, dict) and axis.get("sla_status") == "fail":
            breaches.append(axis_id)
    if breaches:
        return {
            "axis": "freshness",
            "level": "warn",
            "summary": f"freshness SLA breach: {', '.join(breaches[:5])}",
        }
    return {"axis": "freshness", "level": "info", "summary": "freshness SLA met"}


def _judge_cron_health(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {"axis": "cron", "level": "unknown", "summary": "cron health snapshot not found"}
    success_rate = snapshot.get("success_rate_24h")
    threshold = snapshot.get("threshold", 0.95)
    if isinstance(success_rate, (int, float)) and success_rate < threshold:
        return {
            "axis": "cron",
            "level": "critical" if success_rate < 0.8 else "warn",
            "summary": (
                f"cron success_rate_24h={success_rate:.2f} < threshold {threshold}"
            ),
        }
    return {
        "axis": "cron",
        "level": "info",
        "summary": (
            f"cron success_rate_24h={success_rate}" if success_rate is not None else "cron health snapshot empty"
        ),
    }


def _max_severity(alerts: list[dict[str, Any]]) -> str:
    seen = {a["level"] for a in alerts}
    for level in reversed(SEVERITY_ORDER):
        if level in seen:
            return level
    return "unknown"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_recent_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


def _render_atom(entries: list[dict[str, Any]], snapshot_ts: str) -> str:
    esc = _saxutils.escape
    body_entries: list[str] = []
    for e in reversed(entries):  # newest first
        eid = e.get("id") or f"tag:jpcite.com,{e.get('ts', snapshot_ts)[:10]}:{e.get('axis', 'axis')}-{e.get('level', 'info')}"
        title = f"[{e.get('level', 'info').upper()}] {e.get('axis', '?')}: {e.get('summary', '')}"
        body_entries.append(
            "  <entry>\n"
            f"    <title>{esc(title)}</title>\n"
            f"    <id>{esc(eid)}</id>\n"
            f"    <updated>{esc(e.get('ts', snapshot_ts))}</updated>\n"
            f"    <published>{esc(e.get('ts', snapshot_ts))}</published>\n"
            "    <link href=\"https://jpcite.com/status/monitoring.html\" rel=\"alternate\" type=\"text/html\"/>\n"
            f"    <category term=\"{esc(e.get('level', 'info'))}\" label=\"{esc(e.get('level', 'info'))}\"/>\n"
            f"    <category term=\"{esc(e.get('axis', 'axis'))}\" label=\"{esc(e.get('axis', 'axis'))}\"/>\n"
            "    <author><name>jpcite</name></author>\n"
            f"    <summary type=\"text\">{esc(e.get('summary', ''))}</summary>\n"
            "  </entry>"
        )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<feed xmlns=\"http://www.w3.org/2005/Atom\">\n"
        "  <title>jpcite 監視 alert feed</title>\n"
        "  <subtitle>SLA breach / cron failure / deploy issue / endpoint 5xx を Real-time に publish (Wave 41 Agent H)</subtitle>\n"
        "  <link href=\"https://jpcite.com/status/feed.atom\" rel=\"self\" type=\"application/atom+xml\"/>\n"
        "  <link href=\"https://jpcite.com/status/monitoring.html\" rel=\"alternate\" type=\"text/html\"/>\n"
        "  <id>https://jpcite.com/status/feed.atom</id>\n"
        f"  <updated>{esc(snapshot_ts)}</updated>\n"
        "  <generator uri=\"https://jpcite.com/\" version=\"w41\">jpcite-status-aggregator</generator>\n"
        "  <icon>https://jpcite.com/assets/favicon-32.png</icon>\n"
        "  <logo>https://jpcite.com/assets/og.png</logo>\n"
        "  <rights>Bookyou株式会社 — operational transparency feed, CC0 metadata.</rights>\n"
        "  <author>\n    <name>jpcite</name>\n    <uri>https://jpcite.com/</uri>\n    <email>info@bookyou.net</email>\n  </author>\n"
        + "\n".join(body_entries)
        + "\n</feed>\n"
    )


def _send_telegram(message: str) -> str:
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "skip"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "1",
    }).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"ok:{resp.status}"
    except urllib.error.URLError as exc:
        return f"error:{exc}"


def run() -> int:
    snapshot_ts = _now_iso()

    rum = _load_json(SITE_STATUS / "rum.json")
    status = _load_json(SITE_STATUS / "status.json")
    six_axis = _load_json(ANALYTICS / "six_axis_status.json")
    freshness = _load_json(ANALYTICS / "freshness_rollup.json")
    cron_health = _load_json(ANALYTICS / "cron_health_24h.json")

    alerts: list[dict[str, Any]] = []
    for judge_fn, src in (
        (_judge_rum, rum),
        (_judge_status_components, status),
        (_judge_six_axis, six_axis),
        (_judge_freshness, freshness),
        (_judge_cron_health, cron_health),
    ):
        result = judge_fn(src)
        result["ts"] = snapshot_ts
        result["id"] = f"tag:jpcite.com,{snapshot_ts[:10]}:{result['axis']}-{snapshot_ts}"
        alerts.append(result)
        _append_jsonl(ALERT_JSONL, result)

    max_level = _max_severity(alerts)

    sidecar_payload = {
        "snapshot_ts": snapshot_ts,
        "schema_version": 1,
        "max_severity": max_level,
        "alerts": alerts,
    }
    SIDECAR_JSON.parent.mkdir(parents=True, exist_ok=True)
    SIDECAR_JSON.write_text(json.dumps(sidecar_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    recent = _read_recent_jsonl(ALERT_JSONL, ATOM_MAX_ENTRIES)
    FEED_ATOM.write_text(_render_atom(recent, snapshot_ts), encoding="utf-8")

    tg_status = "skip"
    if max_level == "critical":
        critical_lines = [
            f"[{a['axis']}] {a['summary']}"
            for a in alerts
            if a["level"] == "critical"
        ]
        tg_status = _send_telegram(
            "jpcite WAVE41 critical alert\n" + "\n".join(critical_lines)
        )

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    print(
        json.dumps(
            {
                "snapshot_ts": snapshot_ts,
                "max_severity": max_level,
                "alert_count": len(alerts),
                "telegram": tg_status,
                "jsonl": _rel(ALERT_JSONL),
                "feed": _rel(FEED_ATOM),
                "sidecar": _rel(SIDECAR_JSON),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
