"""
webui/components/header.py - Header component for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import html

from webui.components.api_config_modal import create_config_button
from webui.i18n import t


def create_header(lang="en"):
    """Create the header component for the web UI."""
    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    [
                        dbc.Label(t(lang, "ui.language"), html_for="ui-language", className="small text-muted mb-1"),
                        dbc.Select(
                            id="ui-language",
                            options=[
                                {"label": t(lang, "ui.language.english"), "value": "en"},
                                {"label": t(lang, "ui.language.chinese"), "value": "zh"},
                            ],
                            value=lang,
                            size="sm",
                        ),
                    ],
                    width=2,
                ),
                dbc.Col([
                    html.H1(
                        t(lang, "header.title"),
                        className="text-center mb-0"
                    )
                ], width=8, className="d-flex align-items-center justify-content-center"),
                dbc.Col([
                    create_config_button(lang=lang)
                ], width=2, className="d-flex align-items-center justify-content-end"),
            ], className="align-items-center")
        ]),
        className="mb-4"
    )
