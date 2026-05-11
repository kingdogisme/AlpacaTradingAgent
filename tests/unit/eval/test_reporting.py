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
