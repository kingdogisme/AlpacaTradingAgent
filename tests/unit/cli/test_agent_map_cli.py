from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app


def test_agent_map_json_contract_is_compact():
    result = CliRunner().invoke(app, ["agent-map", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["recommended_debug_path"] == [
        "run-index",
        "quality-index",
        "retrieval-pack",
        "raw audit excerpt",
    ]
    assert "module_entrypoints" in payload
    assert "raw output" not in result.stdout.lower()
    assert "full_states_log" not in result.stdout
