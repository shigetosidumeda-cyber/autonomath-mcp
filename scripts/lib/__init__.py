"""Shared helpers for scripts/ (ingest, watchers, one-offs).

Keep this package dependency-light: stdlib + httpx only. Anything that
needs the full API runtime should live under src/jpintel_mcp/.
"""
