"""TKC FX2 由来 JSON → jpcite REST API `/v1/me/client_profiles/bulk_import`。

`import_tkc_fx2.py` が出力した records JSON、または同形式の dict list を
`/v1/me/client_profiles/bulk_import` (multipart CSV upload) に POST する。

なぜ multipart CSV upload かというと、jpcite REST 側の bulk_import が
`UploadFile` を要求しているため (`api/client_profiles.py`)。本スクリプトは
records → in-memory CSV → multipart POST に直接組み立てる。

直接 SQL 書き込みは禁止 (CLAUDE.md 制約)。必ず REST API 経由。

CLI:

    python apply_to_client_profiles.py /tmp/jpcite_profiles.json \
        --api-base https://api.jpcite.com \
        --api-key  $JPCITE_API_KEY \
        [--no-upsert]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_API_BASE = "https://api.jpcite.com"


# 顧問先 record → CSV 行に展開するときの header 順 (jpcite 側が受け付ける順)
_CSV_FIELDS = (
    "name_label",
    "jsic_major",
    "prefecture",
    "employee_count",
    "capital_yen",
    "target_types",
    "last_active_program_ids",
)


def _records_to_csv_text(records: list[dict[str, Any]]) -> str:
    """records → in-memory CSV (UTF-8-sig)。

    jpcite 側の DictReader は utf-8-sig を fallback で受けつける。
    list 型 (target_types / last_active_program_ids) は `|` 区切りに直す。
    """

    buf = io.StringIO()
    # BOM 付き UTF-8 で書き出す: jpcite REST 側で utf-8-sig を最初に試すため。
    buf.write("﻿")
    writer = csv.DictWriter(buf, fieldnames=list(_CSV_FIELDS))
    writer.writeheader()
    for rec in records:
        row = {}
        for field in _CSV_FIELDS:
            val = rec.get(field)
            if isinstance(val, list):
                row[field] = "|".join(str(v) for v in val if v not in (None, ""))
            elif val is None:
                row[field] = ""
            else:
                row[field] = str(val)
        writer.writerow(row)
    return buf.getvalue()


def _build_multipart(
    csv_text: str, *, upsert: bool
) -> tuple[bytes, str]:
    """multipart/form-data 本文と Content-Type を組み立てる。

    依存追加なし (urllib stdlib のみ) で動かすため手書き。
    """

    boundary = f"----jpciteTkcCsvBoundary{uuid4().hex}"
    crlf = "\r\n"
    parts: list[bytes] = []

    # CSV file part
    parts.append(f"--{boundary}{crlf}".encode("utf-8"))
    parts.append(
        (
            'Content-Disposition: form-data; name="file"; '
            'filename="tkc_fx2.csv"'
            + crlf
            + "Content-Type: text/csv; charset=utf-8"
            + crlf + crlf
        ).encode("utf-8")
    )
    parts.append(csv_text.encode("utf-8"))
    parts.append(crlf.encode("utf-8"))

    # upsert flag (Form() field)
    parts.append(f"--{boundary}{crlf}".encode("utf-8"))
    parts.append(
        (
            'Content-Disposition: form-data; name="upsert"'
            + crlf + crlf + ("true" if upsert else "false") + crlf
        ).encode("utf-8")
    )

    parts.append(f"--{boundary}--{crlf}".encode("utf-8"))
    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def _load_records(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return list(payload["records"])
    raise ValueError(
        f"{path}: expected JSON list or {{records: [...]}}; got {type(payload).__name__}"
    )


def post_bulk_import(
    *,
    api_base: str,
    api_key: str,
    records: list[dict[str, Any]],
    upsert: bool = True,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """`/v1/me/client_profiles/bulk_import` に POST して JSON 応答を返す。"""

    if not api_key:
        raise ValueError(
            "api_key is required (jpcite REST 側 require_key で 401)"
        )
    if not records:
        return {
            "imported": 0, "updated": 0, "skipped": 0,
            "errors": [], "total_after_import": 0,
            "_note": "no records sent",
        }

    csv_text = _records_to_csv_text(records)
    body, content_type = _build_multipart(csv_text, upsert=upsert)
    url = f"{api_base.rstrip('/')}/v1/me/client_profiles/bulk_import"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            # jpcite は X-API-Key と Authorization: Bearer の両方を受け付ける。
            # X-API-Key の方が freee/MF plugin の流儀と合うのでこちらを採用。
            "X-API-Key": api_key,
            "User-Agent": "jpcite-tkc-csv-importer/0.1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
        except Exception:
            err_body = "(unreadable)"
        raise RuntimeError(
            f"bulk_import failed: HTTP {exc.code} {exc.reason}: {err_body[:512]}"
        ) from exc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="apply_to_client_profiles",
        description=(
            "POST TKC FX2-derived records JSON to jpcite "
            "/v1/me/client_profiles/bulk_import via REST."
        ),
    )
    p.add_argument(
        "input_json",
        type=Path,
        help="path to JSON written by import_tkc_fx2.py "
        "(or any list/{records:[]})",
    )
    p.add_argument(
        "--api-base",
        type=str,
        default=os.environ.get("JPCITE_API_BASE", DEFAULT_API_BASE),
        help="jpcite REST base (default: env JPCITE_API_BASE or "
        f"{DEFAULT_API_BASE})",
    )
    p.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("JPCITE_API_KEY", ""),
        help="jpcite API key (default: env JPCITE_API_KEY)",
    )
    p.add_argument(
        "--no-upsert",
        action="store_true",
        help="disable name_label upsert (will insert duplicates)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be POSTed without contacting the server",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records = _load_records(args.input_json)
    if args.dry_run:
        print(json.dumps(
            {"would_post": len(records),
             "api_base": args.api_base,
             "upsert": not args.no_upsert,
             "first_record": records[0] if records else None},
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    result = post_bulk_import(
        api_base=args.api_base,
        api_key=args.api_key,
        records=records,
        upsert=not args.no_upsert,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("errors") else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
