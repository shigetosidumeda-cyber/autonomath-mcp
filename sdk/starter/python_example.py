"""Minimal AutonoMath query: search 東京都 subsidies.

Run:
    export AUTONOMATH_API_KEY=am_xxx   # optional; anon tier works without
    python python_example.py
"""

import os
import json
import urllib.request
import urllib.parse

API_BASE = os.environ.get("AUTONOMATH_API_BASE", "https://api.autonomath.ai")
API_KEY = os.environ.get("AUTONOMATH_API_KEY", "")

params = urllib.parse.urlencode({"q": "東京都", "kind": "subsidy", "limit": 5})
req = urllib.request.Request(f"{API_BASE}/v1/programs/search?{params}")
if API_KEY:
    req.add_header("X-API-Key", API_KEY)

with urllib.request.urlopen(req, timeout=10) as r:
    print(json.dumps(json.loads(r.read()), ensure_ascii=False, indent=2))
