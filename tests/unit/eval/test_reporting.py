from tradingagents.eval.reporting import summarize_rows


def test_report_summary_excludes_high_leakage_upstream_and_groups_rows():
    rows = [
        {
            "symbol": "AAPL",
            "status": "completed",
            "action": "BUY",
            "oracle_label": "BUY",
            "raw_return": 0.03,
            "alpha_return": 0.01,
            "reward_scalar": 0.8,
            "reward_status": "resolved",
            "trace_span_count": 2,
            "memory_candidate_count": 1,
            "critic_failure_tags": ["wrong_direction"],
            "reward_components": {},
            "leakage_risk": "low",
            "config": {"quick_think_llm": "q", "deep_think_llm": "d"},
            "horizon": "swing",
        },
        {
            "symbol": "AAPL",
            "status": "completed",
            "action": "HOLD",
            "oracle_label": None,
            "raw_return": None,
            "alpha_return": None,
            "reward_scalar": None,
            "reward_status": "not_mature",
            "trace_span_count": 0,
            "memory_candidate_count": 0,
            "critic_failure_tags": [],
            "reward_components": {},
            "leakage_risk": "low",
            "config": {"quick_think_llm": "q", "deep_think_llm": "d"},
            "horizon": "swing",
        },
    ]

    summaries = summarize_rows(rows, ["model", "horizon", "symbol"])

    assert len(summaries) == 1
    assert summaries[0]["episodes"] == 2
    assert summaries[0]["resolved"] == 1
    assert summaries[0]["pending"] == 1
    assert summaries[0]["hit_rate"] == 1
    assert summaries[0]["avg_reward"] == 0.8
    assert summaries[0]["reward_status_distribution"] == {"resolved": 1, "not_mature": 1}
    assert summaries[0]["critic_failure_tags"] == {"wrong_direction": 1}
    assert summaries[0]["memory_candidate_count"] == 1
    assert summaries[0]["trace_coverage_rate"] == 0.5
    assert summaries[0]["soft_gate_audit"]["flagged_soft_gate_over_veto"] == 0


def test_soft_gate_audit_summarizes_counterfactual_advantage():
    rows = [
        {
            "critic_failure_tags": ["soft_gate_over_veto", "over_conservative_hold"],
            "reward_components": {
                "counterfactual_rewards": {
                    "final_action": {"action": "HOLD", "pnl_reward": -1.0},
                    "risk_manager_veto": {"action": "BUY", "pnl_reward": 0.04},
                }
            },
        },
        {
            "critic_failure_tags": [],
            "reward_components": {
                "counterfactual_rewards": {
                    "final_action": {"action": "BUY", "pnl_reward": 0.02},
                    "risk_manager_veto": {"action": None, "pnl_reward": 0.0},
                }
            },
        },
    ]

    summary = summarize_rows(rows)[0]["soft_gate_audit"]

    assert summary["flagged_soft_gate_over_veto"] == 1
    assert summary["flag_rate"] == 0.5
    assert summary["avg_risk_veto_counterfactual_advantage"] == 0.51
    assert summary["recommendation"].startswith("soft_gates_likely_over_vetoing")
