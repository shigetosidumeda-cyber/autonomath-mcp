#!/usr/bin/env python3
# ruff: noqa: N803,N806,SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017
"""Inject common @graph JSON-LD into all site/*.html in <head>. LLM 呼出ゼロ。"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
common = (ROOT / "site/_assets/jsonld/_common.json").read_text("utf-8").strip()
MARKER = 'data-jpcite-jsonld="common"'
inject = f'<script type="application/ld+json" {MARKER}>{common}</script>'
updated = []
for f in (ROOT / "site").rglob("*.html"):
    s = str(f)
    if "_assets" in s or "/.cursor/" in s or "/.well-known/" in s:
        continue
    text = f.read_text("utf-8", errors="ignore")
    if "</head>" not in text:
        continue
    if MARKER in text:
        text = re.sub(
            r'<script type="application/ld\+json" data-jpcite-jsonld="common">.*?</script>',
            inject,
            text,
            flags=re.DOTALL,
        )
    else:
        text = text.replace("</head>", f"  {inject}\n</head>", 1)
    f.write_text(text, "utf-8")
    updated.append(str(f.relative_to(ROOT)))
print(f"Injected/updated common JSON-LD into {len(updated)} HTML files")
if "--list" in sys.argv:
    for p in updated[:20]:
        print(p)
