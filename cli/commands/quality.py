"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

from cli.legacy_main import (
    run_index, buy_runs, quality_index, quality_reconcile, source_reliability, retrieval_pack, quality_summary, quality_events, quality_open,
)

__all__ = ['run_index', 'buy_runs', 'quality_index', 'quality_reconcile', 'source_reliability', 'retrieval_pack', 'quality_summary', 'quality_events', 'quality_open']
