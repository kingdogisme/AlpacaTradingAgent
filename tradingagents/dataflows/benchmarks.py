from __future__ import annotations

from typing import Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.ticker_utils import is_crypto_ticker


def benchmark_for_symbol(symbol: str, config: dict | None = None) -> Optional[str]:
    """Resolve the benchmark used for alpha calculations."""
    if is_crypto_ticker(symbol):
        base = _crypto_base(symbol)
        return None if base == "BTC" else "BTC-USD"

    cfg = config or DEFAULT_CONFIG
    explicit = cfg.get("benchmark_ticker")
    if explicit:
        return str(explicit)

    benchmark_map = cfg.get("benchmark_map") or DEFAULT_CONFIG.get("benchmark_map", {})
    symbol_upper = str(symbol or "").upper()
    for suffix, benchmark in benchmark_map.items():
        if suffix and symbol_upper.endswith(str(suffix).upper()):
            return benchmark
    benchmark = benchmark_map.get("", "SPY")
    return None if symbol_upper == str(benchmark).upper() else benchmark


def _crypto_base(symbol: str) -> str:
    raw = str(symbol or "").upper().replace("/", "-")
    if "-" in raw:
        return raw.split("-")[0]
    for suffix in ("USDT", "USDC", "USD"):
        if raw.endswith(suffix) and len(raw) > len(suffix):
            return raw[: -len(suffix)]
    return raw
