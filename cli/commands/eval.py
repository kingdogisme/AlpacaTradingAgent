"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

from cli.legacy_main import (
    eval_target_build, eval_target_list, eval_target_resolve, eval_target_report,
    pit_run, pit_audit, pit_benchmark,
)

__all__ = [
    'eval_target_build',
    'eval_target_list',
    'eval_target_resolve',
    'eval_target_report',
    'pit_run',
    'pit_audit',
    'pit_benchmark',
]
