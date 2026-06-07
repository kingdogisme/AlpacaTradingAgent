from __future__ import annotations

from webui.layout import create_main_layout


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, (str, bytes)):
        yield from _walk(children)


def test_v2_layer_workspace_separates_research_decision_and_execution_surfaces():
    layout = create_main_layout(lang="en")
    components = list(_walk(layout))
    by_id = {
        getattr(component, "id", None): component
        for component in components
        if isinstance(getattr(component, "id", None), str)
    }

    assert "ata-v2-layer-workspace" in by_id
    tabs = by_id["ata-v2-layer-tabs"]
    assert tabs.active_tab == "v2-research-layer"
    assert [tab.tab_id for tab in tabs.children] == [
        "v2-research-layer",
        "v2-decision-layer",
        "v2-execution-layer",
    ]
    assert [tab.label for tab in tabs.children] == [
        "Research Report",
        "Portfolio Decision",
        "Execution Lifecycle",
    ]

    assert "tabs" in by_id
    assert "decision-summary" in by_id
    assert "positions-table-container" in by_id
    assert "orders-table-container" in by_id
