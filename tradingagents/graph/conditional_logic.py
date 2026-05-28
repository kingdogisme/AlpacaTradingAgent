# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_macro(self, state: AgentState):
        """Determine if macro analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_macro"
        return "Msg Clear Macro"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        risk_state = state["risk_debate_state"]
        phase = risk_state.get("phase", "rebuttal")
        rebuttal_rounds_completed = int(risk_state.get("rebuttal_rounds_completed", 0))
        latest_speaker = risk_state.get("latest_speaker", "Risky")

        if phase == "opening":
            return "Risky Analyst"

        if latest_speaker == "Opening":
            return "Risky Analyst"

        if rebuttal_rounds_completed < 1:
            if latest_speaker.startswith("Risky"):
                return "Safe Analyst"
            if latest_speaker.startswith("Safe"):
                return "Neutral Analyst"
            return "Risk Judge"

        if (
            risk_state["count"] >= 3 * (self.max_risk_discuss_rounds + 1)
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Risk Judge"
            
        # Check if latest_speaker exists in the state, if not initialize it
        if "latest_speaker" not in risk_state:
            # Default to Risky Analyst as the first speaker
            risk_state["latest_speaker"] = "Risky"
            
        if risk_state["latest_speaker"].startswith("Risky"):
            return "Safe Analyst"
        if risk_state["latest_speaker"].startswith("Safe"):
            return "Neutral Analyst"
        return "Risky Analyst"
