#!/usr/bin/env python3
"""Inject viewport + manifest link + theme-color + apple-touch-icon into all site/*.html. LLM 呼出ゼロ。"""
import pathlib, re
ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKER = 'data-jpcite-a11y="baseline"'
BLOCK = '''  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" data-jpcite-a11y="baseline">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="theme-color" content="#0a4d8c" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0a0a0a" media="(prefers-color-scheme: dark)">
  <link rel="apple-touch-icon" sizes="180x180" href="/assets/brand/apple-touch-icon-180.png">'''
updated = []
for f in (ROOT/"site").rglob("*.html"):
    s = str(f)
    if "_assets" in s or "/.cursor/" in s or "/.well-known/" in s: continue
    text = f.read_text("utf-8", errors="ignore")
    if MARKER in text: continue
    if "</head>" not in text: continue
    text = re.sub(r'<meta name="viewport"(?![^>]*data-jpcite-a11y)[^>]*>\s*\n?', '', text)
    text = text.replace("</head>", f"{BLOCK}\n</head>", 1)
    f.write_text(text, "utf-8")
    updated.append(str(f.relative_to(ROOT)))
print(f"Injected a11y baseline into {len(updated)} HTML files")
