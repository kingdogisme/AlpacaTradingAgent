"""ResearchReport construction helpers for ATA V2.

This module exists as the report-builder boundary for agents. The first V2 cut
reuses the legacy graph state adapter; future extraction can move richer report
assembly here without changing `ResearchService`.
"""

from __future__ import annotations

from .service import research_report_from_legacy_state

__all__ = ["research_report_from_legacy_state"]
