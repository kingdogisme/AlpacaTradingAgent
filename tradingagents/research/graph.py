"""Research graph boundary for ATA V2.

The current implementation delegates to `TradingAgentsGraph` in
`v2_research_only` mode. Keeping this module explicit gives agents a stable
place to look when the dedicated research graph is extracted.
"""

from __future__ import annotations

from typing import Any


def create_research_graph(*, selected_analysts: list[str], config: dict[str, Any], debug: bool = False):
    """Create the current research-only graph adapter."""

    cfg = dict(config)
    cfg["v2_research_only"] = True
    cfg["persist_conditional_trade_plan"] = False
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(selected_analysts=selected_analysts, config=cfg, debug=debug)


__all__ = ["create_research_graph"]
