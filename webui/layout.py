"""
Layout module for TradingAgents WebUI
Organizes the main application layout and component assembly
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from webui.components.header import create_header
from webui.components.config_panel import create_config_panel
from webui.components.status_panel import create_status_panel
from webui.components.chart_panel import create_chart_panel
from webui.components.decision_panel import create_decision_panel
from webui.components.reports_panel import create_reports_panel
from webui.components.alpaca_account import render_alpaca_account_section
from webui.components.api_config_modal import create_api_config_modal
from webui.config.constants import COLORS, REFRESH_INTERVALS
from webui.i18n import t


def create_intervals():
    """Create interval components for auto-refresh"""
    return [
        # Fast refresh for critical updates during analysis
        dcc.Interval(
            id='refresh-interval',
            interval=REFRESH_INTERVALS["fast"],
            n_intervals=0,
            disabled=True  # Start disabled, only enable when analysis is running
        ),
        
        # Medium refresh for reports and non-critical updates
        dcc.Interval(
            id='medium-refresh-interval',
            interval=REFRESH_INTERVALS["medium"],
            n_intervals=0,
            disabled=True
        ),
        
        # Slow refresh for account data
        dcc.Interval(
            id='slow-refresh-interval', 
            interval=REFRESH_INTERVALS["slow"],
            n_intervals=0,
            disabled=False  # Always enabled for account data
        )
    ]


def create_stores():
    """Create store components for state management"""
    from webui.utils.storage import create_storage_store_component, create_api_keys_store_component
    return [
        dcc.Store(id='app-store'),
        dcc.Store(id='chart-store', data={'last_symbol': None, 'selected_period': '1y'}),
        create_storage_store_component(),
        create_api_keys_store_component()
    ]


def create_footer(lang="en"):
    """Create the footer section"""
    return dbc.Row(
        [
            dbc.Col(
                dbc.Button(t(lang, "footer.refresh"), id="refresh-btn", color="secondary", className="mb-2"),
                width="auto",
                className="d-flex justify-content-center"
            ),
            dbc.Col(
                html.Div(t(lang, "footer.auto_refresh"), className="text-info small"),
                width="auto",
                className="d-flex align-items-center"
            ),
        ],
        className="d-flex justify-content-center"
    )


def create_main_content(lang="en"):
    """Create the main visible content for the application layout."""

    header = create_header(lang=lang)
    config_card = create_config_panel(lang=lang)
    status_card = create_status_panel(lang=lang)
    chart_card = create_chart_panel(lang=lang)
    decision_card = create_decision_panel(lang=lang)
    reports_card = create_reports_panel()

    alpaca_account_card = dbc.Card(
        dbc.CardBody([
            render_alpaca_account_section(lang=lang)
        ]),
        className="mb-4"
    )

    return [
        header,
        alpaca_account_card,
        dbc.Row([
            dbc.Col(config_card, md=6),
            dbc.Col([
                chart_card,
                html.Div(className="mb-3"),
                status_card,
                html.Div(className="mb-3"),
                decision_card,
            ], md=6)
        ]),
        reports_card,
        html.Div(className="mt-4"),
        create_footer(lang=lang),
    ]


def create_main_layout(lang="zh"):
    """Create the main application layout"""

    api_config_modal = html.Div(
        create_api_config_modal(lang=lang),
        id="api-config-modal-container"
    )

    layout = dbc.Container(
        [
            *create_intervals(),
            *create_stores(),
            api_config_modal,
            html.Script("""
                window.addEventListener('message', function(event) {
                    if (event.data && event.data.type === 'showPrompt') {
                        // Find and trigger the appropriate show prompt button
                        const buttons = document.querySelectorAll('[id*="show-prompt-"]');
                        const reportType = event.data.reportType;
                        
                        // Find the button that matches this report type
                        let targetButton = null;
                        for (let button of buttons) {
                            const buttonId = button.getAttribute('id');
                            if (buttonId && buttonId.includes(reportType)) {
                                targetButton = button;
                                break;
                            }
                        }
                        
                        // If no direct match, try pattern matching
                        if (!targetButton) {
                            for (let button of buttons) {
                                const buttonData = button.getAttribute('data-dash-props');
                                if (buttonData && buttonData.includes(reportType)) {
                                    targetButton = button;
                                    break;
                                }
                            }
                        }
                        
                        // Trigger the button click if found
                        if (targetButton) {
                            targetButton.click();
                        } else {
                            console.log('Could not find button for:', reportType);
                            // Fallback: trigger any show prompt button and set content manually
                            const anyPromptBtn = document.querySelector('[id*="show-prompt-"]');
                            if (anyPromptBtn) {
                                anyPromptBtn.click();
                                // Try to set the modal content directly after a short delay
                                setTimeout(() => {
                                    const modalTitle = document.querySelector('#prompt-modal-title');
                                    const modalContent = document.querySelector('#prompt-modal-content');
                                    if (modalTitle) modalTitle.textContent = event.data.title;
                                    if (modalContent) {
                                        // This will be filled by the callback, but we can try to trigger it
                                        console.log('Showing prompt for:', reportType);
                                    }
                                }, 100);
                            }
                        }
                    }
                });
            """),
            
            html.Div(create_main_content(lang=lang), id="ui-content"),
        ],
        fluid=True,
        className="p-4",
        style={"backgroundColor": COLORS["background"]}
    )
    
    return layout 