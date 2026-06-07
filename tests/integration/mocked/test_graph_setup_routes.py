from __future__ import annotations

from unittest.mock import patch

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


class DummyWorkflow:
    def __init__(self, _state_type):
        self.nodes = []
        self.edges = []
        self.conditional_edges = []

    def add_node(self, name, _node):
        self.nodes.append(name)

    def add_edge(self, start, end):
        self.edges.append((start, end))

    def add_conditional_edges(self, start, _condition, edges):
        self.conditional_edges.append((start, edges))


class FakeToolNode:
    pass


class FakeToolkit:
    config = {"parallel_analysts": True, "parallel_risk_first_round": True}


def _setup(config):
    return GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        toolkit=FakeToolkit(),
        tool_nodes={name: FakeToolNode() for name in ("market", "social", "news", "fundamentals", "macro")},
        bull_memory=object(),
        bear_memory=object(),
        trader_memory=object(),
        invest_judge_memory=object(),
        risk_manager_memory=object(),
        conditional_logic=ConditionalLogic(),
        config=config,
    )


def _patch_agent_factories():
    def node(_state):
        return {}

    patches = [
        patch("tradingagents.graph.setup.StateGraph", DummyWorkflow),
        patch("tradingagents.graph.setup.create_market_analyst", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_social_media_analyst", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_news_analyst", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_fundamentals_analyst", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_macro_analyst", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_bull_researcher", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_bear_researcher", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_research_manager", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_trader", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_risky_debator", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_safe_debator", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_neutral_debator", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_risk_manager", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_msg_delete", return_value=node, create=True),
        patch("tradingagents.graph.setup.create_report_context_node", return_value=node, create=True),
    ]
    return patches


def test_parallel_graph_setup_routes_analysts_through_context_builder():
    config = {"parallel_analysts": True, "parallel_risk_first_round": True}
    patches = _patch_agent_factories()
    for item in patches:
        item.start()
    try:
        workflow = _setup(config).setup_graph(["market", "news", "macro"])
    finally:
        for item in reversed(patches):
            item.stop()

    assert "Parallel Analysts" in workflow.nodes
    assert "Build Report Context" in workflow.nodes
    assert ("Parallel Analysts", "Build Report Context") in workflow.edges
    assert ("Build Report Context", "Bull Researcher") in workflow.edges
    assert ("Trader", "Parallel Risk Round 1") in workflow.edges
    assert any(start == "Parallel Risk Round 1" and "Risk Judge" in edges for start, edges in workflow.conditional_edges)


def test_sequential_graph_setup_routes_selected_analysts_in_order():
    config = {"parallel_analysts": False, "parallel_risk_first_round": False}
    patches = _patch_agent_factories()
    for item in patches:
        item.start()
    try:
        workflow = _setup(config).setup_graph(["market", "news"])
    finally:
        for item in reversed(patches):
            item.stop()

    assert "Market Analyst" in workflow.nodes
    assert "News Analyst" in workflow.nodes
    assert ("Msg Clear Market", "News Analyst") in workflow.edges
    assert ("Msg Clear News", "Build Report Context") in workflow.edges
    assert ("Trader", "Risky Analyst") in workflow.edges


def test_research_only_graph_setup_ends_after_research_manager():
    config = {"parallel_analysts": True, "parallel_risk_first_round": True, "v2_research_only": True}
    patches = _patch_agent_factories()
    for item in patches:
        item.start()
    try:
        workflow = _setup(config).setup_graph(["market", "news"])
    finally:
        for item in reversed(patches):
            item.stop()

    assert "Research Manager" in workflow.nodes
    assert "Trader" not in workflow.nodes
    assert "Risk Judge" not in workflow.nodes
    assert ("Research Manager", "__end__") in workflow.edges
