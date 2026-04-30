"""Jinja2 renderers for 法令改正アラート (Compliance Alerts) emails.

This module is the ONLY place allowed to render the body of the alert
emails. No LLM / Anthropic / OpenAI call shapes the text — rendering is
deterministic Jinja2 over structured `Change` records pulled from SQLite.
That constraint is load-bearing: at ¥3/req margin the product cannot
absorb an LLM round-trip per customer per day (memory
`feedback_autonomath_no_api_use.md`).

Three public functions:
    - `compose_alert_email(subscriber, changes, mode='realtime')`
        Returns `{subject, html, text}` for a single subscriber + a list of
        changes. `mode='realtime'` (daily paid cron) vs `mode='digest'`
        (monthly free-plan round-up) toggles the subject line and intro
        copy, but the body list is rendered the same way so the same
        Jinja2 partial covers both.
    - `render_verification_email(email, verify_url)` — returns
        `{subject, html, text}` for the double opt-in confirmation mail
        that fires on POST /v1/compliance/subscribe.
    - `AREA_LABELS_JA` — mapping of internal area codes
        ('invoice', 'ebook', 'subsidy', 'loan', 'enforcement',
         'tax_ruleset', 'court') to Japanese display labels. Kept
        module-level so the API layer and the landing page form can reuse
        the same strings without risk of drift.

Design:
    * Templates are defined as Python multi-line strings at module scope
      so tests can call `compose_alert_email` without needing any file
      system access. Past Postmark-style template aliases live on
      Postmark's side; these live on OUR side because the alert body is
      data-dependent (variable number of changes) and Postmark's template
      engine cannot do {% for %} over a JSON array cleanly.
    * The text body is rendered by the same templates with `html2text`-
      style plain rendering (we just write a separate template for plain
      text — no external library needed).
    * Every email footer MUST carry the 特商法 (Act on Specified
      Commercial Transactions) notation + unsubscribe link. The helper
      `_footer_ja` builds it once and both html/text partials include it.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from jinja2 import Environment, StrictUndefined

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

AREA_LABELS_JA: dict[str, str] = {
    "invoice": "インボイス制度",
    "ebook": "電子帳簿保存法",
    "subsidy": "補助金",
    "loan": "融資",
    "enforcement": "行政処分",
    "tax_ruleset": "税務ルール",
    "court": "判例",
}

# Canonical enum of areas_of_interest. Kept here so the API layer, the
# landing page, and the cron all agree. Adding a new area means one edit
# here + renderer support below.
AREAS_SUPPORTED: tuple[str, ...] = tuple(AREA_LABELS_JA.keys())


# ---------------------------------------------------------------------------
# Types — shape of the payload `compose_alert_email` expects
# ---------------------------------------------------------------------------


class Change(TypedDict, total=False):
    """A single row that changed in the last N hours / last month.

    `table` is one of the source tables (programs / laws / tax_rulesets /
    enforcement_cases / court_decisions). `area` is the internal area code
    from AREA_LABELS_JA (the cron assigns this based on which table the
    row came from).
    """
    unified_id: str
    table: str
    area: str
    title: str
    summary: str
    source_url: str
    detail_url: str
    updated_at: str


class Subscriber(TypedDict, total=False):
    id: int
    email: str
    prefecture: str | None
    plan: str
    unsubscribe_token: str
    areas_of_interest: list[str]
    industry_codes: list[str]


class ComposedEmail(TypedDict):
    subject: str
    html: str
    text: str


# ---------------------------------------------------------------------------
# Jinja2 environment — one shared env per process
# ---------------------------------------------------------------------------

# StrictUndefined: template access to a missing key raises rather than
# silently rendering an empty string. Keeps regressions visible in tests.
_env = Environment(
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)

# Plain-text env — no autoescape (HTML entities in a text body look broken).
_env_text = Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


# ---------------------------------------------------------------------------
# Template strings
# ---------------------------------------------------------------------------

# Subject line — real-time daily alert vs monthly free digest.
_SUBJECT_REALTIME = "【AutonoMath】法令改正アラート: {n}件の変更があります"
_SUBJECT_DIGEST = "【AutonoMath】{ym} の制度変更まとめ ({n}件)"
_SUBJECT_VERIFY = "【AutonoMath】法令改正アラートの登録確認"

_FOOTER_TXT = """--
AutonoMath — 法令改正アラート
このメールは {email} 宛に配信されています。
配信を停止する: {unsubscribe_url}

運営: Bookyou 株式会社 (T8010001213708)
所在地: 東京都文京区小日向2-22-1
問い合わせ: info@bookyou.net
特商法表記: https://jpcite.com/tokushoho.html
利用規約: https://jpcite.com/tos.html
プライバシーポリシー: https://jpcite.com/privacy.html
"""

_FOOTER_HTML = """\
<hr style="border:none;border-top:1px solid #e5e5e5;margin:32px 0 16px">
<p style="font-size:12px;color:#555;line-height:1.7;margin:0 0 8px">
  AutonoMath — 法令改正アラート<br>
  このメールは <a href="mailto:{{ email }}" style="color:#555">{{ email }}</a> 宛に配信されています。<br>
  <a href="{{ unsubscribe_url }}" style="color:#1e3a8a">配信を停止する</a>
</p>
<p style="font-size:12px;color:#555;line-height:1.7;margin:0">
  運営: Bookyou 株式会社 (T8010001213708)<br>
  所在地: 東京都文京区小日向2-22-1<br>
  問い合わせ: <a href="mailto:info@bookyou.net" style="color:#1e3a8a">info@bookyou.net</a><br>
  <a href="https://jpcite.com/tokushoho.html" style="color:#1e3a8a">特商法表記</a> ・
  <a href="https://jpcite.com/tos.html" style="color:#1e3a8a">利用規約</a> ・
  <a href="https://jpcite.com/privacy.html" style="color:#1e3a8a">プライバシーポリシー</a>
</p>
"""


_ALERT_HTML_TMPL = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>{{ subject }}</title>
</head>
<body style="font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic UI', sans-serif; color:#111; line-height:1.7; max-width:640px; margin:0 auto; padding:24px;">
  <h1 style="font-size:20px; font-weight:700; margin:0 0 8px;">{{ heading }}</h1>
  <p style="font-size:14px; color:#555; margin:0 0 20px;">{{ lead }}</p>

  {% for area, items in grouped.items() %}
  <h2 style="font-size:16px; font-weight:700; margin:24px 0 8px; padding-bottom:6px; border-bottom:1px solid #e5e5e5;">
    {{ area_labels[area] }} <span style="color:#555; font-weight:500; font-size:13px;">({{ items|length }}件)</span>
  </h2>
  <ul style="list-style:none; padding:0; margin:0 0 12px;">
    {% for c in items %}
    <li style="margin:0 0 14px; padding:0 0 0 12px; border-left:3px solid #1e3a8a;">
      <div style="font-weight:600; font-size:14px; margin:0 0 4px;">
        {{ c.title }}
      </div>
      <div style="font-size:13px; color:#555; margin:0 0 6px;">
        {{ c.summary }}
      </div>
      <div style="font-size:12px; color:#555;">
        <a href="{{ c.source_url }}" style="color:#1e3a8a;">一次資料を開く</a>
        {% if c.detail_url %}
        ・
        <a href="{{ c.detail_url }}" style="color:#1e3a8a;">AutonoMath で詳細を見る</a>
        {% endif %}
      </div>
    </li>
    {% endfor %}
  </ul>
  {% endfor %}

  <p style="font-size:13px; color:#555; margin:24px 0 0;">
    {{ closing }}
  </p>

""" + _FOOTER_HTML + """\
</body>
</html>
"""

_ALERT_TEXT_TMPL = """\
{{ heading }}

{{ lead }}

{% for area, items in grouped.items() %}
== {{ area_labels[area] }} ({{ items|length }}件) ==

{% for c in items %}
- {{ c.title }}
  {{ c.summary }}
  一次資料: {{ c.source_url }}
{% if c.detail_url %}  AutonoMath: {{ c.detail_url }}
{% endif %}
{% endfor %}

{% endfor %}

{{ closing }}

""" + _FOOTER_TXT


_VERIFY_HTML_TMPL = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>{{ subject }}</title>
</head>
<body style="font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic UI', sans-serif; color:#111; line-height:1.7; max-width:560px; margin:0 auto; padding:24px;">
  <h1 style="font-size:20px; font-weight:700; margin:0 0 12px;">ご登録ありがとうございます</h1>
  <p style="font-size:14px; color:#111; margin:0 0 16px;">
    AutonoMath 法令改正アラートへのご登録を確認するため、下のボタンをクリックしてください。
  </p>
  <p style="margin:24px 0;">
    <a href="{{ verify_url }}" style="display:inline-block; background:#1e3a8a; color:#fff; padding:12px 24px; border-radius:6px; font-weight:600; text-decoration:none;">登録を確認する</a>
  </p>
  <p style="font-size:13px; color:#555; margin:0 0 8px;">
    ボタンが動かない場合は下記 URL をブラウザに貼り付けてください:
  </p>
  <p style="font-size:12px; color:#1e3a8a; word-break:break-all; margin:0 0 16px;">
    {{ verify_url }}
  </p>
  <p style="font-size:13px; color:#555; margin:0 0 0;">
    心当たりのない場合はこのメールを破棄してください (何もしなければ登録は完了しません)。
  </p>
""" + _FOOTER_HTML + """\
</body>
</html>
"""

_VERIFY_TEXT_TMPL = """\
ご登録ありがとうございます。

AutonoMath 法令改正アラートへのご登録を確認するため、下記 URL を開いてください:

  {{ verify_url }}

心当たりのない場合はこのメールを破棄してください (何もしなければ登録は完了しません)。

""" + _FOOTER_TXT


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unsubscribe_url(token: str) -> str:
    """Landing URL for one-click unsubscribe from email footer.

    Points at the static `site/alerts-unsubscribe.html` page which POSTs
    back to `/v1/compliance/unsubscribe/{token}` on click (so bots crawling
    links in the email body cannot accidentally unsubscribe users — a
    Gmail / Outlook "show images" fetch must NOT end the subscription).
    """
    return f"https://jpcite.com/alerts-unsubscribe.html?token={token}"


def _group_by_area(changes: list[Change]) -> dict[str, list[Change]]:
    """Bucket changes by their `area` code, preserving insertion order.

    We iterate the canonical `AREAS_SUPPORTED` tuple so the rendered
    email sections always appear in the same order (インボイス -> 電帳法
    -> 補助金 -> ...), regardless of how the query returned them.
    """
    out: dict[str, list[Change]] = {}
    for area in AREAS_SUPPORTED:
        area_items = [c for c in changes if c.get("area") == area]
        if area_items:
            out[area] = area_items
    # Tail bucket for anything with an unknown area code (defensive — the
    # cron should always set a valid area, but a bad row upstream
    # shouldn't break the send).
    tail = [c for c in changes if c.get("area") not in AREA_LABELS_JA]
    if tail:
        out["_other"] = tail
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compose_alert_email(
    subscriber: Subscriber,
    changes: list[Change],
    *,
    mode: Literal["realtime", "digest"] = "realtime",
    period_label: str | None = None,
) -> ComposedEmail:
    """Render a single alert email for `subscriber` given `changes`.

    Args:
        subscriber: TypedDict — must include `email` and `unsubscribe_token`.
        changes: list of Change dicts. Callers (cron) already filtered by
            this subscriber's areas_of_interest / industry / prefecture.
        mode: 'realtime' (paid, daily) or 'digest' (free, monthly).
        period_label: For `mode='digest'`, the YYYY-MM string the digest
            covers (e.g. '2026-04'). Ignored for 'realtime'.

    Returns:
        `{subject, html, text}` — ready to hand to the Postmark send path.

    The function NEVER raises on a malformed `Change` (missing keys fall
    back to placeholder strings). It DOES raise if `subscriber` is missing
    `email` or `unsubscribe_token` — those are required for the footer
    and should always be populated by the API/cron layer.
    """
    if not subscriber.get("email"):
        raise ValueError("subscriber.email is required")
    if not subscriber.get("unsubscribe_token"):
        raise ValueError("subscriber.unsubscribe_token is required")

    # Coerce missing fields on change rows to safe placeholders before
    # handing to StrictUndefined.
    prepared: list[dict[str, Any]] = []
    for c in changes:
        prepared.append(
            {
                "unified_id": c.get("unified_id", ""),
                "table": c.get("table", ""),
                "area": c.get("area", "_other"),
                "title": c.get("title") or "(無題)",
                "summary": c.get("summary") or "",
                "source_url": c.get("source_url") or "#",
                "detail_url": c.get("detail_url") or "",
                "updated_at": c.get("updated_at") or "",
            }
        )

    grouped = _group_by_area(prepared)  # type: ignore[arg-type]
    n = len(prepared)

    if mode == "digest":
        ym = period_label or ""
        subject = _SUBJECT_DIGEST.format(ym=ym, n=n)
        heading = f"{ym} の制度変更まとめ"
        lead = (
            f"{ym} の期間に更新された制度を、ご関心のある領域に絞ってまとめました。"
            " 常時アラートに切り替えると、変更を24時間以内に個別通知します。"
        )
        closing = (
            "24時間以内の変更を個別に通知する ¥500/月 プランへは、"
            "https://jpcite.com/alerts.html からアップグレードできます。"
        )
    else:
        subject = _SUBJECT_REALTIME.format(n=n)
        heading = f"{n}件の変更があります"
        lead = "過去24時間に、あなたのフィルタに合致する制度の変更が検出されました。"
        closing = (
            "本通知は ¥500/月 プランで配信しています。"
            "配信頻度・対象の変更は https://jpcite.com/alerts.html から可能です。"
        )

    # Area labels localized for the template.
    area_labels = dict(AREA_LABELS_JA)
    area_labels["_other"] = "その他"

    context: dict[str, Any] = {
        "subject": subject,
        "heading": heading,
        "lead": lead,
        "closing": closing,
        "grouped": grouped,
        "area_labels": area_labels,
        "email": subscriber["email"],
        "unsubscribe_url": _unsubscribe_url(subscriber["unsubscribe_token"]),
    }

    html = _env.from_string(_ALERT_HTML_TMPL).render(**context)
    text = _env_text.from_string(_ALERT_TEXT_TMPL).render(**context)

    return ComposedEmail(subject=subject, html=html, text=text)


def render_verification_email(
    *,
    email: str,
    verify_url: str,
    unsubscribe_token: str,
) -> ComposedEmail:
    """Render the double-opt-in verification email.

    Sent synchronously from POST /v1/compliance/subscribe. The click-through
    hits GET /v1/compliance/verify/{token} which sets `verified_at`.

    The footer still carries a one-click unsubscribe link — if the user
    never verifies AND clicks unsubscribe anyway, we treat it as a request
    to never contact them again (prevents bounce-loop abuse of a typo'd
    email address).
    """
    subject = _SUBJECT_VERIFY
    context = {
        "subject": subject,
        "verify_url": verify_url,
        "email": email,
        "unsubscribe_url": _unsubscribe_url(unsubscribe_token),
    }
    html = _env.from_string(_VERIFY_HTML_TMPL).render(**context)
    text = _env_text.from_string(_VERIFY_TEXT_TMPL).render(**context)
    return ComposedEmail(subject=subject, html=html, text=text)


__all__ = [
    "AREA_LABELS_JA",
    "AREAS_SUPPORTED",
    "Change",
    "ComposedEmail",
    "Subscriber",
    "compose_alert_email",
    "render_verification_email",
]
