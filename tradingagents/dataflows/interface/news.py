"""Compatibility exports for dataflow interface functions."""

from .legacy import (
    get_finnhub_news,
    get_coindesk_news,
    get_google_news,
    get_reddit_global_news,
    get_reddit_company_news,
    get_stock_news_openai,
    get_global_news_openai,
    get_sellthenews_stock_news,
    get_sellthenews_social_sentiment,
)

__all__ = [
    "get_finnhub_news",
    "get_coindesk_news",
    "get_google_news",
    "get_reddit_global_news",
    "get_reddit_company_news",
    "get_stock_news_openai",
    "get_global_news_openai",
    "get_sellthenews_stock_news",
    "get_sellthenews_social_sentiment",
]
