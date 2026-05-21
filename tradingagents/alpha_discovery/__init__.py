"""Alpha Discovery collectors and scoring helpers."""

from .models import DiscoveryBatch, Handoff, OpportunityCandidate, Outcome, SourceSignal
from .repository import AlphaDiscoveryRepository
from .sellthenews_dd import (
    DDCandidate,
    DDSourceSignal,
    collect_sellthenews_dd_candidates,
)
from .service import AlphaDiscoveryService

try:
    from .market_data import AlpacaPriceVolumeProvider, price_volume_confirmation_from_bars
except Exception:  # optional dependency path for isolated AD tests
    AlpacaPriceVolumeProvider = None
    price_volume_confirmation_from_bars = None

__all__ = [
    "AlphaDiscoveryRepository",
    "AlphaDiscoveryService",
    "AlpacaPriceVolumeProvider",
    "DDCandidate",
    "DDSourceSignal",
    "DiscoveryBatch",
    "Handoff",
    "OpportunityCandidate",
    "Outcome",
    "SourceSignal",
    "collect_sellthenews_dd_candidates",
    "price_volume_confirmation_from_bars",
]
