from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tradingagents.contracts import InvestmentDecision, PolicyGateResult, PortfolioContext, ResearchReport
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.trade_lifecycle.models import (
    ConditionalTradePlan,
    ExecutionPolicy,
    TradeInvalidation,
    TradeRiskBudget,
    TradeTrigger,
)

from .policy import get_portfolio_policy


@dataclass
class PortfolioDecisionService:
    """V2 Portfolio Decision Layer façade.

    This service is deliberately deterministic for the first V2 cut. LLM-backed
    explanation can be added behind the same `InvestmentDecision` contract, but
    hard policy gates and sizing must remain code-enforced.
    """

    config: dict[str, Any] | None = None

    def decide(self, report: ResearchReport, context: PortfolioContext | None = None) -> InvestmentDecision:
        cfg = {**DEFAULT_CONFIG, **(self.config or {})}
        context = context or PortfolioContext(policy_config=cfg)
        policy = get_portfolio_policy({**cfg, **(context.policy_config or {})})
        actionability = self._actionability(report, context)
        human_action = self._human_action(report, actionability, context)
        risk_budget = self._risk_budget(report, policy, actionability)
        sizing = self._sizing(policy, risk_budget, actionability)
        invalidation = self._invalidation(report, actionability)
        trigger = self._trigger(actionability)
        valid_until = self._valid_until(report.horizon, cfg) if actionability in {"buy_now", "conditional"} else None
        plan = None
        alpaca_intent = "NO_ORDER"
        if actionability in {"buy_now", "conditional"} and human_action in {"BUY", "LONG", "SELL", "SHORT"}:
            plan = self._conditional_plan(
                report=report,
                human_action=human_action,
                trigger=trigger or {"type": "market"},
                invalidation=invalidation or {},
                risk_budget=risk_budget,
                sizing=sizing,
                valid_until=valid_until,
                cfg=cfg,
            )
            alpaca_intent = "IMMEDIATE_ORDER" if actionability == "buy_now" else "CONDITIONAL_ORDER"

        gates = self._policy_gates(report, context, actionability, risk_budget)
        if any(g.severity == "hard" and not g.passed for g in gates):
            alpaca_intent = "NO_ORDER"
            plan = None
            if actionability == "buy_now":
                actionability = "watchlist"

        return InvestmentDecision(
            report_id=report.report_id,
            symbol=report.symbol,
            human_action=human_action,
            advisory_rating=self._advisory_rating(report),
            actionability=actionability,
            confidence=report.confidence,
            thesis_summary=report.thesis,
            risk_budget=risk_budget,
            sizing=sizing,
            trigger=trigger,
            invalidation=invalidation,
            valid_until=valid_until,
            alpaca_intent=alpaca_intent,
            conditional_trade_plan=plan,
            policy_gate_results=gates,
            rationale=self._rationale(report, context, actionability),
            audit_refs={
                "report_id": report.report_id,
                "research_audit_refs": report.audit_refs,
                "layer": "portfolio_decision",
            },
        )

    def _actionability(self, report: ResearchReport, context: PortfolioContext) -> str:
        if report.conclusion == "A" and report.confidence == "high":
            return "buy_now"
        if report.conclusion in {"A", "B"} and report.confidence in {"high", "medium"}:
            return "conditional"
        if report.conclusion == "C":
            return "watchlist"
        return "no_trade"

    def _human_action(self, report: ResearchReport, actionability: str, context: PortfolioContext) -> str:
        if actionability in {"buy_now", "conditional"}:
            return "BUY"
        if report.conclusion == "D" and context.current_symbol_position == "LONG":
            return "SELL"
        return "HOLD"

    def _risk_budget(self, report: ResearchReport, policy: dict[str, Any], actionability: str) -> dict[str, Any]:
        if actionability == "buy_now":
            risk_pct = min(float(policy["max_single_name_risk_pct"]), 0.015 if report.confidence == "high" else 0.01)
        elif actionability == "conditional":
            risk_pct = min(float(policy["max_single_name_risk_pct"]), 0.01)
        else:
            risk_pct = 0.0
        return {
            "risk_budget_pct": risk_pct,
            "max_notional_pct": min(float(policy["max_single_name_notional_pct"]), 0.10 if risk_pct else 0.0),
        }

    def _sizing(self, policy: dict[str, Any], risk_budget: dict[str, Any], actionability: str) -> dict[str, Any]:
        if actionability not in {"buy_now", "conditional"}:
            return {"notional_exposure_pct": 0.0, "sizing_basis": "no actionable portfolio decision"}
        return {
            "notional_exposure_pct": risk_budget["max_notional_pct"],
            "single_name_cap_pct": policy["max_single_name_notional_pct"],
            "sizing_basis": "starter allocation until explicit trigger/invalidation prices are available",
        }

    def _trigger(self, actionability: str) -> dict[str, Any] | None:
        if actionability == "buy_now":
            return {"type": "market", "description": "Portfolio decision classified as buy_now."}
        if actionability == "conditional":
            return {"type": "market", "description": "Compatibility placeholder; execution validator still requires current approval."}
        return None

    def _invalidation(self, report: ResearchReport, actionability: str) -> dict[str, Any] | None:
        if actionability not in {"buy_now", "conditional"}:
            return None
        reason = report.kill_conditions[0] if report.kill_conditions else "Research thesis invalidation is triggered."
        return {"reason": reason}

    def _valid_until(self, horizon: str, cfg: dict[str, Any]) -> str:
        configured = cfg.get("trade_lifecycle_valid_days")
        days = int(configured) if configured else {"swing": 10, "position": 45, "trend": 90}.get(horizon, 45)
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    def _conditional_plan(
        self,
        *,
        report: ResearchReport,
        human_action: str,
        trigger: dict[str, Any],
        invalidation: dict[str, Any],
        risk_budget: dict[str, Any],
        sizing: dict[str, Any],
        valid_until: str | None,
        cfg: dict[str, Any],
    ) -> dict[str, Any]:
        max_notional = self._max_notional_from_budget(risk_budget, cfg)
        trigger = self._execution_safe_trigger(trigger)
        invalidation = self._execution_safe_invalidation(invalidation)
        plan = ConditionalTradePlan(
            symbol=report.symbol,
            action=human_action,
            trigger=TradeTrigger(**trigger),
            invalidation=TradeInvalidation(**invalidation),
            valid_until=valid_until or self._valid_until(report.horizon, cfg),
            risk_budget=TradeRiskBudget(
                risk_budget_pct=risk_budget.get("risk_budget_pct"),
                max_notional=max_notional,
                max_notional_pct=risk_budget.get("max_notional_pct"),
                max_gap_pct=cfg.get("trade_lifecycle_max_gap_pct", 0.08),
            ),
            max_notional=max_notional,
            execution_policy=ExecutionPolicy(
                notional=max_notional,
                paper_only=True,
                allow_shorts=bool(cfg.get("allow_shorts", False)),
            ),
            source_run_id=report.audit_refs.get("run_id"),
            source_decision=report.markdown,
            source_audit_path=report.audit_refs.get("audit_path"),
            horizon=report.horizon,
            trading_mode=cfg.get("trading_mode", "investment"),
            metadata={
                "source_report_id": report.report_id,
                "v2_layer": "portfolio_decision",
                "sizing": sizing,
            },
        )
        return plan.model_dump(mode="json")

    def _max_notional_from_budget(self, risk_budget: dict[str, Any], cfg: dict[str, Any]) -> float:
        return float(cfg.get("trade_lifecycle_default_notional", 1000) or 1000)

    def _execution_safe_trigger(self, trigger: dict[str, Any]) -> dict[str, Any]:
        """Return a monitorable trigger shape.

        V2 report/decision may be conditional without explicit prices during the
        compatibility phase. A market trigger keeps the plan structurally valid,
        while the execution layer still requires validator approval/review.
        """

        return dict(trigger or {"type": "market"})

    def _execution_safe_invalidation(self, invalidation: dict[str, Any]) -> dict[str, Any]:
        """Return numeric invalidation for lifecycle compatibility.

        Research-only invalidation can be qualitative. The execution validator
        requires numeric bounds before approving orders, so this placeholder is
        deliberately far from normal prices and tagged in the reason.
        """

        result = dict(invalidation or {})
        if result.get("price_below") is None and result.get("price_above") is None:
            result["price_below"] = 0.01
            reason = result.get("reason") or "Qualitative invalidation only."
            result["reason"] = f"{reason} Numeric placeholder requires operator review before execution."
        return result

    def _policy_gates(
        self,
        report: ResearchReport,
        context: PortfolioContext,
        actionability: str,
        risk_budget: dict[str, Any],
    ) -> list[PolicyGateResult]:
        gates = [
            PolicyGateResult(
                name="research_confidence",
                passed=report.confidence in {"high", "medium"} or actionability == "no_trade",
                severity="soft",
                reason=f"research confidence={report.confidence}",
            ),
            PolicyGateResult(
                name="single_name_risk_budget",
                passed=float(risk_budget.get("risk_budget_pct") or 0.0) <= 0.025,
                severity="hard",
                reason="risk budget must not exceed single-name cap",
            ),
        ]
        if context.current_symbol_position == "SHORT" and actionability in {"buy_now", "conditional"}:
            gates.append(
                PolicyGateResult(
                    name="position_conflict",
                    passed=False,
                    severity="hard",
                    reason="cannot approve long actionability while current position is SHORT",
                )
            )
        return gates

    def _advisory_rating(self, report: ResearchReport) -> str:
        if report.conclusion == "A":
            return "STRONG BUY" if report.confidence == "high" else "BUY"
        if report.conclusion == "B":
            return "BUY" if report.confidence in {"high", "medium"} else "HOLD"
        if report.conclusion == "C":
            return "HOLD"
        return "SELL"

    def _rationale(self, report: ResearchReport, context: PortfolioContext, actionability: str) -> str:
        return (
            f"Research conclusion {report.conclusion}/{report.confidence}; "
            f"portfolio position is {context.current_symbol_position}; "
            f"actionability={actionability}. Alpaca intent is not broker authorization."
        )
