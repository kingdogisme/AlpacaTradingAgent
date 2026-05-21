"""
webui/components/status_panel.py - Status panel for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import html

from webui.i18n import t


def create_status_panel(lang="en"):
    """Create the status panel for the web UI."""
    return dbc.Card(
        dbc.CardBody([
            html.H4(t(lang, "status.title"), className="mb-3"),
            html.Hr(),
            html.Div(id="status-table"),
            dbc.Row([
                dbc.Col([
                    html.Div(id="tool-calls-text", children=t(lang, "status.tool_calls", count=0)),
                ], width=4),
                dbc.Col([
                    html.Div(id="llm-calls-text", children=t(lang, "status.llm_calls", count=0)),
                ], width=4),
                dbc.Col([
                    html.Div(id="reports-text", children=t(lang, "status.reports", count=0)),
                ], width=4),
            ], className="mt-3"),
            html.Div(id="data-quality-panel"),
            html.Div(id="refresh-status", children=t(lang, "status.paused"), className="text-secondary mt-2")
        ]),
        className="mb-4"
    )
