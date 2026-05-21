# TradingAgents/graph/__init__.py

__all__ = [
    "TradingAgentsGraph",
    "ConditionalLogic",
    "GraphSetup",
    "Propagator",
    "Reflector",
    "SignalProcessor",
]


def __getattr__(name):
    if name == "TradingAgentsGraph":
        from .trading_graph import TradingAgentsGraph

        return TradingAgentsGraph
    if name == "ConditionalLogic":
        from .conditional_logic import ConditionalLogic

        return ConditionalLogic
    if name == "GraphSetup":
        from .setup import GraphSetup

        return GraphSetup
    if name == "Propagator":
        from .propagation import Propagator

        return Propagator
    if name == "Reflector":
        from .reflection import Reflector

        return Reflector
    if name == "SignalProcessor":
        from .signal_processing import SignalProcessor

        return SignalProcessor
    raise AttributeError(name)
