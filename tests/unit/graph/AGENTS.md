# Graph Unit Tests Boundary

Tests here cover legacy graph logging, state propagation, and compatibility
behavior.

## Rules

- Mock LLM and tool boundaries.
- Protect compatibility while V2 services are extracted.
- Avoid adding new V2 logic assertions here unless testing adapters.
