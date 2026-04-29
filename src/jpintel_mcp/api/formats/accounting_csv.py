"""Accounting-CSV renderers — ``?format={csv-freee, csv-mf, csv-yayoi}``.

Three vendor-CSV variants share encoding + 備考-pack logic and diverge
only on column-name + encoding:

  * ``csv-freee``  — UTF-8 (no BOM), header row = 取引日, 借方科目, 借方金額,
                     貸方科目, 貸方金額, 摘要, 借方税区分, 貸方税区分.
                     Source: https://support.freee.co.jp/hc/ja/articles/202910580
  * ``csv-mf``     — UTF-8 BOM, MoneyForward 仕訳帳 import column order.
                     Source: https://biz.moneyforward.com/support/account/guide/import/import01.html
  * ``csv-yayoi``  — Shift_JIS, 弥生会計 「振替伝票形式」column order.
                     Source: https://support.yayoi-kk.co.jp/subcontents/faq/d_faq/onyu/sw_aio_ip.html

Every variant prepends a comment row with the freee / MF / 弥生 template
URL and the §52 disclaimer so an offline-opened file is still self-
attributable. The leading ``#`` row is stripped by all three vendors'
import wizards (which read from the first non-comment row that matches
their column header).

Field-mapping policy: AutonoMath does NOT have native 仕訳 (journal-
entry) data — it has program / loan / enforcement rows. We emit a
stub row per AutonoMath row using the following deterministic mapping:

    取引日           = next_deadline OR source_fetched_at OR today
    借方科目         = "未決 (要確認)"  ← 経理担当者が手動でマップ
    貸方科目         = "未決 (要確認)"
    借方金額 / 貸方金額 = max_amount_yen if present else 0
    摘要             = primary_name + " / unified_id=" + unified_id
    備考             = source_url + " | license=" + license

The 借方科目 / 貸方科目 fields stay literal "未決 (要確認)" — we cannot
guess the customer's chart-of-accounts. The 摘要 + 備考 carry full lineage
so the bookkeeper can reconcile from the import log.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import Response

from jpintel_mcp.api._format_dispatch import (
    BRAND_FOOTER,
    DISCLAIMER_HEADER_VALUE,
    DISCLAIMER_JA,
)

# ---------------------------------------------------------------------------
# Per-vendor metadata.
# ---------------------------------------------------------------------------

_VENDORS: dict[str, dict[str, Any]] = {
    "csv-freee": {
        "encoding": "utf-8",  # freee accepts no-BOM UTF-8 in 2024+
        "bom": "",
        "template_url": (
            "https://support.freee.co.jp/hc/ja/articles/"
            "202910580"
        ),
        "columns": (
            "取引日",
            "借方勘定科目",
            "借方税区分",
            "借方金額",
            "貸方勘定科目",
            "貸方税区分",
            "貸方金額",
            "摘要",
            "備考",
        ),
        "filename_suffix": "freee.csv",
        "vendor_label": "freee 仕訳一括インポート (取引一括登録 互換)",
    },
    "csv-mf": {
        "encoding": "utf-8",
        "bom": "﻿",
        "template_url": (
            "https://biz.moneyforward.com/support/account/guide/"
            "import/import01.html"
        ),
        "columns": (
            "取引No",
            "取引日",
            "借方勘定科目",
            "借方補助科目",
            "借方部門",
            "借方税区分",
            "借方金額",
            "貸方勘定科目",
            "貸方補助科目",
            "貸方部門",
            "貸方税区分",
            "貸方金額",
            "摘要",
            "備考",
        ),
        "filename_suffix": "moneyforward.csv",
        "vendor_label": "MoneyForward クラウド会計 仕訳帳インポート",
    },
    "csv-yayoi": {
        "encoding": "shift_jis",
        "bom": "",
        "template_url": (
            "https://support.yayoi-kk.co.jp/subcontents/faq/d_faq/onyu/"
            "sw_aio_ip.html"
        ),
        "columns": (
            "識別フラグ",
            "伝票No",
            "決算",
            "取引日付",
            "借方勘定科目",
            "借方補助科目",
            "借方部門",
            "借方税区分",
            "借方金額",
            "借方税金額",
            "貸方勘定科目",
            "貸方補助科目",
            "貸方部門",
            "貸方税区分",
            "貸方金額",
            "貸方税金額",
            "摘要",
            "番号",
            "期日",
            "タイプ",
            "生成元",
            "仕訳メモ",
            "付箋1",
            "付箋2",
            "調整",
        ),
        "filename_suffix": "yayoi.csv",
        "vendor_label": "弥生会計 振替伝票形式 (Shift_JIS)",
    },
}


def _today_iso() -> str:
    """JST today ISO date (used when a row carries no deadline / fetched_at)."""
    jst = _dt.timezone(_dt.timedelta(hours=9))
    return _dt.datetime.now(jst).date().isoformat()


def _txn_date(row: dict[str, Any]) -> str:
    for k in ("next_deadline", "deadline", "source_fetched_at", "fetched_at"):
        v = row.get(k)
        if isinstance(v, str) and v:
            # Truncate to YYYY-MM-DD.
            return v[:10]
    return _today_iso()


def _amount_yen(row: dict[str, Any]) -> int:
    for k in ("max_amount_yen", "amount_yen", "max_grant_yen"):
        v = row.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _summary(row: dict[str, Any]) -> str:
    name = (
        row.get("primary_name")
        or row.get("name")
        or row.get("title")
        or ""
    )
    uid = row.get("unified_id") or ""
    return f"{name} / unified_id={uid}".strip(" /")


def _bikou(row: dict[str, Any]) -> str:
    return (
        f"{row.get('source_url', '') or ''} | "
        f"license={row.get('license', '') or ''}"
    )


def _stub_freee_row(row: dict[str, Any]) -> dict[str, Any]:
    amount = _amount_yen(row)
    return {
        "取引日": _txn_date(row),
        "借方勘定科目": "未決 (要確認)",
        "借方税区分": "対象外",
        "借方金額": amount,
        "貸方勘定科目": "未決 (要確認)",
        "貸方税区分": "対象外",
        "貸方金額": amount,
        "摘要": _summary(row),
        "備考": _bikou(row),
    }


def _stub_mf_row(row: dict[str, Any]) -> dict[str, Any]:
    amount = _amount_yen(row)
    return {
        "取引No": row.get("unified_id", ""),
        "取引日": _txn_date(row),
        "借方勘定科目": "未決 (要確認)",
        "借方補助科目": "",
        "借方部門": "",
        "借方税区分": "対象外",
        "借方金額": amount,
        "貸方勘定科目": "未決 (要確認)",
        "貸方補助科目": "",
        "貸方部門": "",
        "貸方税区分": "対象外",
        "貸方金額": amount,
        "摘要": _summary(row),
        "備考": _bikou(row),
    }


def _stub_yayoi_row(row: dict[str, Any]) -> dict[str, Any]:
    amount = _amount_yen(row)
    # Yayoi 識別フラグ: 2000 = 仕訳行 (single-line entry).
    return {
        "識別フラグ": "2000",
        "伝票No": "",
        "決算": "",
        "取引日付": _txn_date(row).replace("-", "/"),
        "借方勘定科目": "未決",
        "借方補助科目": "",
        "借方部門": "",
        "借方税区分": "対象外",
        "借方金額": amount,
        "借方税金額": 0,
        "貸方勘定科目": "未決",
        "貸方補助科目": "",
        "貸方部門": "",
        "貸方税区分": "対象外",
        "貸方金額": amount,
        "貸方税金額": 0,
        "摘要": _summary(row),
        "番号": "",
        "期日": "",
        "タイプ": "",
        "生成元": "AutonoMath",
        "仕訳メモ": _bikou(row),
        "付箋1": "",
        "付箋2": "",
        "調整": "no",
    }


_BUILDERS = {
    "csv-freee": _stub_freee_row,
    "csv-mf": _stub_mf_row,
    "csv-yayoi": _stub_yayoi_row,
}


def render_accounting_csv(
    rows: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    vendor: str,
) -> Response:
    """Render ``rows`` as a vendor-CSV stub.

    ``vendor`` MUST be one of ``csv-freee``, ``csv-mf``, ``csv-yayoi``.
    Anything else raises 400 — the dispatcher already validates, so this
    is a defense-in-depth check.
    """
    if vendor not in _VENDORS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown accounting-CSV vendor: {vendor}",
        )

    cfg = _VENDORS[vendor]
    builder = _BUILDERS[vendor]

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    # Comment rows — vendors strip these because they do not match the
    # column-header signature. We bake the freee / MF / Yayoi template URL
    # into the file so a bookkeeper opening the file offline can verify
    # the format we targeted.
    writer.writerow([f"# Source format: {cfg['template_url']}"])
    writer.writerow([f"# Vendor: {cfg['vendor_label']}"])
    writer.writerow([f"# {DISCLAIMER_JA}"])
    writer.writerow([
        f"# {BRAND_FOOTER} | "
        f"借方/貸方は '未決 (要確認)' のまま — "
        f"勘定科目は経理担当が手動でマップしてください。"
    ])

    # Header row.
    writer.writerow(list(cfg["columns"]))

    # Data rows.
    for row in rows:
        stub = builder(row)
        writer.writerow([_csv_cell(stub.get(c)) for c in cfg["columns"]])

    text = cfg["bom"] + buf.getvalue()
    body = text.encode(cfg["encoding"], errors="replace")

    filename = f"{meta.get('filename_stem', 'autonomath_export')}_{cfg['filename_suffix']}"
    return Response(
        content=body,
        media_type=f"text/csv; charset={cfg['encoding']}",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AutonoMath-Disclaimer": DISCLAIMER_HEADER_VALUE,
            "X-AutonoMath-Format": vendor,
            "X-AutonoMath-Vendor-Template": cfg["template_url"],
        },
    )


def _csv_cell(v: Any) -> str:
    """CSV-safe coercion shared with the freee / MF / Yayoi builders."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)
