from __future__ import annotations

from pathlib import Path


def test_gitignore_covers_agent_noise_paths():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in [
        "eval_results_*/",
        "eval_results_quarantine/",
        ".env.bak.*",
        "logs/",
        "**/__pycache__/",
        ".pytest_cache/",
        ".idea/",
    ]:
        assert pattern in ignore
