# Research Layer Boundary

This folder owns ATA V2 research-facing services and adapters.

## Rules

- Return `ResearchReport` contracts.
- Do not read Alpaca account positions for thesis-quality decisions.
- Do not persist trade lifecycle plans by default.
- Legacy graph adapters may be used while extracting a dedicated research graph.
