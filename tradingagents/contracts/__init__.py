"""ATA V2 layer contracts.

These models define the typed handoff boundaries between research, portfolio
decisioning, execution, and evaluation. They are intentionally side-effect free
and can be imported by services, CLI commands, tests, and future agents.
"""

from .research import (
    EvidenceItem,
    PricingCheck,
    ResearchReport,
    ResearchRequest,
    ResearchVariable,
)
from .decision import (
    InvestmentDecision,
    PolicyGateResult,
    PortfolioContext,
    PositionSnapshot,
)
from .execution import ExecutionResult
from .eval import (
    EvaluationLayer,
    LayerEvaluationRecord,
    LayerEvaluationTarget,
)

__all__ = [
    "EvidenceItem",
    "EvaluationLayer",
    "ExecutionResult",
    "InvestmentDecision",
    "LayerEvaluationRecord",
    "LayerEvaluationTarget",
    "PolicyGateResult",
    "PortfolioContext",
    "PositionSnapshot",
    "PricingCheck",
    "ResearchReport",
    "ResearchRequest",
    "ResearchVariable",
]
