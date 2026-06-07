# Analyst Agents Boundary

Analysts produce domain-specific research reports for the Research Layer.

## Owned Roles

- `market_analyst.py`: price action, technical context, market data.
- `news_analyst.py`: news and catalyst evidence.
- `social_media_analyst.py`: social/retail sentiment evidence.
- `fundamentals_analyst.py`: company/fundamental evidence.
- `macro_analyst.py`: macro and liquidity evidence.

## Rules

- Analysts may use market/news/fundamental data tools.
- Analysts must not read account positions or execution state.
- Reports should cite source quality/freshness when available.
- Keep report fields compatible with `report_context.py`.
