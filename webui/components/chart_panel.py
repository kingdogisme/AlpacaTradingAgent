"""
webui/components/chart_panel.py - Chart panel with symbol-based pagination
"""

import dash_bootstrap_components as dbc
from dash import dcc, html
from webui.utils.charts import create_welcome_chart
from webui.i18n import t


def create_symbol_pagination(pagination_id, max_symbols=1, lang="en"):
    """Create a custom pagination component using symbol names instead of page numbers"""
    return html.Div(id=f"{pagination_id}-container", 
                   children=[
                       html.Div(t(lang, "chart.no_symbols"), 
                               className="text-muted text-center",
                               style={"padding": "10px"})
                   ],
                   className="symbol-pagination-container")


def create_chart_panel(lang="en"):
    """Create the chart panel for the web UI with symbol-based pagination."""
    return dbc.Card(
        dbc.CardBody([
            html.H4(t(lang, "chart.title"), className="mb-3"),
            html.Hr(),
            dbc.Row([
                dbc.Col([
                    create_symbol_pagination("chart-pagination", lang=lang)
                ], width=8),
                dbc.Col([
                    dbc.Button(t(lang, "chart.refresh"), id="manual-chart-refresh", color="outline-secondary", size="sm", className="float-end"),
                ], width=4)
            ], className="mb-2"),
            html.Div(id="current-symbol-display", className="text-center my-2"),
            html.Div(id="chart-last-updated", className="text-muted text-center small mb-2"),
            dbc.ButtonGroup([
                dbc.Button("1D", id="period-1d", color="secondary", outline=True, className="me-1"),
                dbc.Button("1W", id="period-1w", color="secondary", outline=True, className="me-1"),
                dbc.Button("1M", id="period-1mo", color="secondary", outline=True, className="me-1"),
                dbc.Button("1Y", id="period-1y", color="secondary", outline=True),
            ], className="mb-3"),
            html.Div(
                dcc.Graph(
                    id="chart-container", 
                    figure=create_welcome_chart(),
                    config={'displayModeBar': True, 'responsive': True},
                    style={"height": "400px", "width": "100%"}
                ),
                style={"height": "400px", "width": "100%", "overflow": "hidden"}
            ),
            html.Div([
                dbc.Pagination(
                    id="chart-pagination",
                    max_value=1,
                    fully_expanded=True,
                    first_last=True,
                    previous_next=True,
                    className="d-none"
                )
            ], style={"display": "none"})
        ]),
        className="mb-4"
    )
