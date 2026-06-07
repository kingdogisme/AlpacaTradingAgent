# Graph Boundary

This folder owns the legacy LangGraph orchestration. It currently mixes
research, portfolio decisioning, and plan persistence.

## ATA V2 Direction

- Treat `TradingAgentsGraph` as a compatibility wrapper.
- New orchestration should move toward Research and Portfolio Decision services
  with typed contracts.
- Plan persistence should not be a default side effect of research-only runs.

## Rules

- Do not expand `AgentState` for new V2 concepts unless required for
  compatibility.
- Prefer adapters that convert legacy final state into V2 contracts.
- Keep graph tests passing while extracting services.
