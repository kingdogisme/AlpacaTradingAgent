"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

from cli.legacy_main import (
    MessageBuffer, message_buffer, create_layout, update_display, get_user_selections, get_ticker, display_complete_report, update_research_team_status, run_analysis, analyze, ata_run, ata_report, ata_decide,
)

__all__ = ['MessageBuffer', 'message_buffer', 'create_layout', 'update_display', 'get_user_selections', 'get_ticker', 'display_complete_report', 'update_research_team_status', 'run_analysis', 'analyze', 'ata_run', 'ata_report', 'ata_decide']
