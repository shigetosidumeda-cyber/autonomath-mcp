"""TKC FX2 顧問先一覧 CSV → jpcite client_profiles JSON 変換。

TKC の FX2 (会計ソフト) は税理士事務所側で「関与先一覧」を CSV エクスポート
できる。jpcite の `/v1/me/client_profiles/bulk_import` (migration 096) は
最大 200 行までの顧問先メタデータを upsert で取り込む。

このスクリプトは TKC FX2 の典型的な CSV 列名 (日本語、cp932 / utf-8-sig)
を jpcite が要求するスキーマに直線変換するだけの **stateless converter** で、
LLM 推論は一切行わない。

入力列の対応 (TKC → jpcite):

  関与先コード        → (drop, name_label が PK 役)
  関与先名            → name_label  (必須)
  業種コード          → jsic_major  (4 文字までに丸め: E26 → E26)
  業種名              → (drop, jsic_major が canonical)
  所在地都道府県      → prefecture  (例: 東京都, 大阪府)
  従業員数            → employee_count
  資本金（千円）      → capital_yen (×1,000 倍して円単位に正規化)
  前年売上（千円）    → (drop, jpcite には売上枠なし)
  適用補助金履歴      → last_active_program_ids (| 区切り)

CLI:

    python import_tkc_fx2.py path/to/tkc_export.csv \
        --output  /tmp/jpcite_profiles.json \
        --encoding utf-8-sig

`--encoding` は `utf-8-sig` (TKC 新版) / `cp932` (TKC 旧版 + Excel 既定)
の両方を試行 (auto-detect)。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# --- 列名マッピング (TKC FX2 export 既定) ---------------------------------

# 観測に基づく既定マッピング。TKC のテンプレを編集している顧問先用に
# `--column-map` で上書きできる。
DEFAULT_COLUMN_MAP: dict[str, str] = {
    "関与先名": "name_label",
    "業種コード": "jsic_major",
    "所在地都道府県": "prefecture",
    "従業員数": "employee_count",
    "資本金（千円）": "capital_yen_sen",
    "適用補助金履歴": "last_active_program_ids",
    # 半角括弧版も accept (TKC エクスポートのバージョン揺れ対策)
    "資本金(千円)": "capital_yen_sen",
}


# --- データクラス -----------------------------------------------------------


@dataclass(frozen=True)
class ClientProfileRecord:
    """jpcite client_profiles bulk_import が受け取れる 1 行ぶん。"""

    name_label: str
    jsic_major: str | None = None
    prefecture: str | None = None
    employee_count: int | None = None
    capital_yen: int | None = None
    target_types: list[str] | None = None
    last_active_program_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [])}


# --- 変換ロジック -----------------------------------------------------------


def _coerce_int(raw: Any) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # TKC が "1,000" / "30000人" などの suffix を出すことがある
    digits = "".join(c for c in s if c.isdigit() or c == "-")
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _split_pipe(raw: Any) -> list[str]:
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    return [token.strip() for token in s.split("|") if token.strip()]


def _decode_bytes(raw_bytes: bytes, prefer: str | None = None) -> str:
    """utf-8-sig → cp932 → utf-8 の順で decode を試す。"""
    candidates = []
    if prefer:
        candidates.append(prefer)
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        if enc not in candidates:
            candidates.append(enc)
    last_err: Exception | None = None
    for enc in candidates:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise UnicodeDecodeError(  # type: ignore[misc]
        "tkc-csv",
        raw_bytes,
        0,
        1,
        f"could not decode TKC CSV with any of {candidates}: {last_err}",
    )


def convert_row(
    row: dict[str, Any],
    *,
    column_map: dict[str, str] | None = None,
) -> ClientProfileRecord | None:
    """1 行を ClientProfileRecord に変換。name_label が空なら None を返す。"""

    cmap = column_map or DEFAULT_COLUMN_MAP
    normalized: dict[str, Any] = {}
    for src_col, dst_col in cmap.items():
        if src_col in row and row[src_col] not in (None, ""):
            normalized[dst_col] = row[src_col]
        elif src_col.strip() in row and row[src_col.strip()] not in (None, ""):
            normalized[dst_col] = row[src_col.strip()]

    name_label = (
        str(normalized.get("name_label", "")).strip()
        if normalized.get("name_label") is not None
        else ""
    )
    if not name_label:
        return None

    jsic_raw = normalized.get("jsic_major")
    jsic = (str(jsic_raw).strip() or None) if jsic_raw is not None else None
    if jsic and len(jsic) > 4:
        # FX2 は中分類まで (3-4 文字) しか出さない想定。
        # jpcite の jsic_major カラムは 4 文字上限なので念のため切り詰める。
        jsic = jsic[:4]

    pref_raw = normalized.get("prefecture")
    prefecture = (str(pref_raw).strip() or None) if pref_raw is not None else None

    emp = _coerce_int(normalized.get("employee_count"))

    capital_sen = _coerce_int(normalized.get("capital_yen_sen"))
    capital_yen = capital_sen * 1000 if capital_sen is not None else None

    last_active = _split_pipe(normalized.get("last_active_program_ids"))

    return ClientProfileRecord(
        name_label=name_label,
        jsic_major=jsic,
        prefecture=prefecture,
        employee_count=emp,
        capital_yen=capital_yen,
        last_active_program_ids=last_active or None,
    )


def convert_csv_text(
    csv_text: str,
    *,
    column_map: dict[str, str] | None = None,
    max_rows: int = 200,
) -> tuple[list[ClientProfileRecord], list[dict[str, Any]]]:
    """CSV テキスト → (records, errors)。errors は行単位のスキップ理由。"""

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        return [], [{"error": "csv_no_header"}]

    records: list[ClientProfileRecord] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, start=1):
        if idx > max_rows:
            errors.append({"row_index": idx, "error": "exceeded_row_cap", "cap": max_rows})
            break
        rec = convert_row(raw, column_map=column_map)
        if rec is None:
            errors.append({"row_index": idx, "error": "missing_name_label"})
            continue
        records.append(rec)
    return records, errors


def convert_csv_path(
    path: Path,
    *,
    encoding: str | None = None,
    column_map: dict[str, str] | None = None,
    max_rows: int = 200,
) -> tuple[list[ClientProfileRecord], list[dict[str, Any]]]:
    raw_bytes = path.read_bytes()
    text = _decode_bytes(raw_bytes, prefer=encoding)
    return convert_csv_text(text, column_map=column_map, max_rows=max_rows)


# --- CLI --------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="import_tkc_fx2",
        description="Convert TKC FX2 顧問先一覧 CSV → jpcite client_profiles JSON",
    )
    p.add_argument("input", type=Path, help="path to TKC FX2 CSV export")
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="path to write JSON (default: stdout)",
    )
    p.add_argument(
        "--encoding",
        type=str,
        default=None,
        help="force decode encoding (utf-8-sig / cp932 / utf-8). " "default: auto-detect.",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=200,
        help="hard cap on rows read (default 200, matches client_profiles cap)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, errors = convert_csv_path(
        args.input,
        encoding=args.encoding,
        max_rows=args.max_rows,
    )
    payload = {
        "records": [r.to_dict() for r in records],
        "errors": errors,
        "summary": {
            "input_path": str(args.input),
            "record_count": len(records),
            "error_count": len(errors),
        },
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"wrote {len(records)} records to {args.output}")
    else:
        print(output)
    return 0 if not errors else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
