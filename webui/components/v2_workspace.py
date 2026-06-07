"""ATA V2 layer workspace components."""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html

from webui.i18n import t


def create_v2_layer_workspace(*, research_view, decision_view, execution_view, lang="en"):
    """Create a tabbed workspace that separates V2 layer surfaces."""

    return html.Section(
        [
            dbc.Tabs(
                [
                    dbc.Tab(
                        research_view,
                        label=t(lang, "v2.layer.research"),
                        tab_id="v2-research-layer",
                        label_style={"color": "#94A3B8", "fontWeight": "600"},
                        active_label_style={"color": "#FFFFFF", "fontWeight": "700"},
                    ),
                    dbc.Tab(
                        decision_view,
                        label=t(lang, "v2.layer.decision"),
                        tab_id="v2-decision-layer",
                        label_style={"color": "#94A3B8", "fontWeight": "600"},
                        active_label_style={"color": "#FFFFFF", "fontWeight": "700"},
                    ),
                    dbc.Tab(
                        execution_view,
                        label=t(lang, "v2.layer.execution"),
                        tab_id="v2-execution-layer",
                        label_style={"color": "#94A3B8", "fontWeight": "600"},
                        active_label_style={"color": "#FFFFFF", "fontWeight": "700"},
                    ),
                ],
                id="ata-v2-layer-tabs",
                active_tab="v2-research-layer",
                className="enhanced-tabs ata-v2-layer-tabs",
            )
        ],
        id="ata-v2-layer-workspace",
        className="ata-v2-layer-workspace mb-4",
    )
