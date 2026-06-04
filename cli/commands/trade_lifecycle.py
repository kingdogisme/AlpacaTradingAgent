"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

from cli.legacy_main import (
    trade_monitor, trade_plan_list, trade_plan_show, trade_plan_events, trade_plan_health, trade_monitor_status, trade_monitor_preflight, trade_plan_reconcile, trade_plan_action,
)

__all__ = ['trade_monitor', 'trade_plan_list', 'trade_plan_show', 'trade_plan_events', 'trade_plan_health', 'trade_monitor_status', 'trade_monitor_preflight', 'trade_plan_reconcile', 'trade_plan_action']
