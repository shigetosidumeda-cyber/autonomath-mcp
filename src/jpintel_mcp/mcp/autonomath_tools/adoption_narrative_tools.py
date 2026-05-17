"""Adoption narrative tools — stub.

NOTE: Created 2026-05-17 by the GG1 lane to unblock the autonomath_tools
package import gate. A parallel AA5 G6 lane committed an
``adoption_narrative_tools`` import row into ``autonomath_tools/__init__.py``
(commit 75ad67718) without committing this companion module. That mismatch
broke the package boot for every downstream commit gate.

This stub is intentionally minimal: it exposes no public API and registers
no MCP tool. The AA5 G6 lane should overwrite this file with the real
``search_adoption_narratives`` implementation in their next commit.

NO LLM inference. NO network I/O. Pure module placeholder.
"""

from __future__ import annotations

__all__: list[str] = []
