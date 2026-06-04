"""Compatibility exports for dataflow interface functions."""

from .legacy import (
    get_alpaca_data_window,
    get_alpaca_data,
    get_sellthenews_options_data,
)

__all__ = [
    "get_alpaca_data_window",
    "get_alpaca_data",
    "get_sellthenews_options_data",
]
