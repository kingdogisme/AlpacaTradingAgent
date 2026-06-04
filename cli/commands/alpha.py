"""Command group compatibility exports.

Implementation currently lives in `cli.legacy_main`; this module gives agents a
smaller map of ownership without changing the public CLI contract.
"""

from cli.legacy_main import (
    cron_discover, cron_confirm, cron_run, ata_run, cron_resolve, basket_list, basket_report, basket_eval_report, ad_events, ad_health, ad_ingest, cron_schedule,
)

__all__ = ['cron_discover', 'cron_confirm', 'cron_run', 'ata_run', 'cron_resolve', 'basket_list', 'basket_report', 'basket_eval_report', 'ad_events', 'ad_health', 'ad_ingest', 'cron_schedule']
