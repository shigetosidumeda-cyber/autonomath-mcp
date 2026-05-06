"""
04_pandas_export_csv.py
-----------------------
Paginate through every 補助金 / 融資 record that matches q=中小企業 (roughly
370 programs), build a pandas DataFrame, save CSV. Demonstrates the correct
pagination loop (total/limit/offset) and the 10-req/page rate-limit friendly
pacing. Output CSV is the kind of artifact a salary analyst / consultant
wants on day 1.

env vars:
    JPINTEL_API_KEY   (optional)
    JPINTEL_API_BASE  (default: https://api.jpcite.com)

run:
    pip install -r ../requirements.txt  (includes pandas)
    python 04_pandas_export_csv.py

expected output:

    page 1: 100 rows (total=369)
    page 2: 100 rows
    page 3: 100 rows
    page 4: 69 rows
    fetched: 369 rows in 4 pages

    DataFrame shape: (369, 7)
    tier counts:
    tier
    B    188
    A     89
    C     80
    S      6
    X      6

    saved: ./subsidies_chusho.csv (369 rows)
    top-5 by amount_max_man_yen:
                        primary_name  amount_max_man_yen authority_name
                         北海道 防災・減災貸付            160000.0
    省エネルギー投資促進支援事業費補助金（省エネ・非化石転換補助金）            150000.0
                     省力化支援資金（中小企業事業）            144000.0
                   新事業活動促進資金（中小企業事業）            144000.0
             事業承継・集約・活性化支援資金（中小企業事業）            144000.0
"""
from __future__ import annotations

import os
import sys
import time

import httpx
import pandas as pd

API_BASE = os.environ.get("JPINTEL_API_BASE", "https://api.jpcite.com")
API_KEY = os.environ.get("JPINTEL_API_KEY")
PAGE_SIZE = 100  # server max


def fetch_page(offset: int, query: str) -> dict:
    headers: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    try:
        resp = httpx.get(
            f"{API_BASE}/v1/programs/search",
            headers=headers,
            params={"q": query, "limit": PAGE_SIZE, "offset": offset},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(f"ERROR: transport failure: {exc}", file=sys.stderr)
        sys.exit(2)

    if resp.status_code == 401:
        print("ERROR: 401 Unauthorized — check JPINTEL_API_KEY", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 429:
        retry = float(resp.headers.get("Retry-After") or 1)
        print(f"  rate-limited, sleeping {retry}s and retrying...", file=sys.stderr)
        time.sleep(retry)
        return fetch_page(offset, query)
    if resp.status_code >= 500:
        print(f"ERROR: server {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def fetch_all(query: str) -> list[dict]:
    all_rows: list[dict] = []
    offset = 0
    page_num = 0
    while True:
        page_num += 1
        data = fetch_page(offset, query)
        results = data["results"]
        total = data["total"]
        all_rows.extend(results)

        print(f"page {page_num}: {len(results)} rows" + (f" (total={total})" if page_num == 1 else ""))

        if not results or len(all_rows) >= total:
            break
        offset += PAGE_SIZE
        # polite pacing for API-friendly pagination
        time.sleep(0.05)

    print(f"fetched: {len(all_rows)} rows in {page_num} pages\n")
    return all_rows


def to_dataframe(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "unified_id",
        "primary_name",
        "tier",
        "authority_name",
        "prefecture",
        "amount_max_man_yen",
        "program_kind",
    ]
    return pd.DataFrame([{c: r.get(c) for c in cols} for r in rows])


def main() -> None:
    rows = fetch_all(query="中小企業")
    df = to_dataframe(rows)

    print(f"DataFrame shape: {df.shape}")
    print("tier counts:")
    print(df["tier"].value_counts().to_string())
    print()

    out = "./subsidies_chusho.csv"
    df.to_csv(out, index=False)
    print(f"saved: {out} ({len(df)} rows)")

    top = df.sort_values("amount_max_man_yen", ascending=False).head(5)
    print("top-5 by amount_max_man_yen:")
    print(top[["primary_name", "amount_max_man_yen", "authority_name"]].to_string(index=False))


if __name__ == "__main__":
    main()
