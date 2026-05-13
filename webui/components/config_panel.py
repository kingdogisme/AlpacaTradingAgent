"""
webui/components/config_panel.py - Configuration panel for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from tradingagents.openai_model_registry import (
    PARAMETER_HELP,
    get_default_model_params,
    get_llm_provider_options,
    get_model_options_for_provider,
)
from webui.i18n import t


ANALYSTS = [
    ("analyst-market", "Market", "fa-chart-line"),
    ("analyst-social", "Social", "fa-comments"),
    ("analyst-news", "News", "fa-newspaper"),
    ("analyst-fundamentals", "Fundamentals", "fa-building-columns"),
    ("analyst-macro", "Macro", "fa-globe"),
]


def _accordion_title(icon, title, meta):
    return html.Div(
        [
            html.I(className=f"fa-solid {icon} config-accordion-icon"),
            html.Div(
                [
                    html.Span(title, className="config-accordion-title"),
                    html.Small(meta, className="config-accordion-meta"),
                ],
                className="config-accordion-copy",
            ),
        ],
        className="config-accordion-heading",
    )


def _field(label, control, icon=None, class_name=""):
    label_children = []
    if icon:
        label_children.append(html.I(className=f"fa-solid {icon} me-2"))
    label_children.append(label)

    return html.Div(
        [
            dbc.Label(label_children, className="config-label"),
            control,
        ],
        className=f"config-field {class_name}".strip(),
    )


def _help_label(label, tooltip_id, help_key):
    return html.Div(
        [
            dbc.Label(label, className="config-label mb-0"),
            html.Span("?", id=tooltip_id, className="llm-param-help", title=PARAMETER_HELP[help_key]),
            dbc.Tooltip(PARAMETER_HELP[help_key], target=tooltip_id, placement="top"),
        ],
        className="config-label-row",
    )


def _analyst_checkbox(component_id, label, icon):
    return html.Div(
        html.Label(
            [
                dbc.Checkbox(
                    id=component_id,
                    value=True,
                    className="analyst-checkbox",
                ),
                html.Span(
                    [
                        html.I(className=f"fa-solid {icon} me-2"),
                        html.Span(label),
                    ],
                    className="analyst-tile-label",
                ),
            ],
            className="analyst-tile-click-target",
        ),
        className="analyst-tile",
    )


def _switch_with_help(component_id, label, default_value, help_key):
    tooltip_id = f"{component_id}-help"
    return html.Div(
        [
            html.Div(
                [
                    dbc.Switch(
                        id=component_id,
                        label=label,
                        value=default_value,
                        className="config-switch",
                    ),
                    html.Span("?", id=tooltip_id, className="llm-param-help", title=PARAMETER_HELP[help_key]),
                    dbc.Tooltip(PARAMETER_HELP[help_key], target=tooltip_id, placement="top"),
                ],
                className="config-switch-row",
            ),
        ]
    )


def _llm_param_controls(role, default_model):
    defaults = get_default_model_params(default_model, role)
    prefix = f"{role}-llm"
    return html.Div(
        [
            html.Div(
                [
                    _help_label("Reasoning effort", f"{prefix}-reasoning-help", "reasoning_effort"),
                    dbc.Select(
                        id=f"{prefix}-reasoning-effort",
                        value=defaults.get("reasoning_effort"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-reasoning-effort-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Text verbosity", f"{prefix}-verbosity-help", "text_verbosity"),
                    dbc.Select(
                        id=f"{prefix}-verbosity",
                        value=defaults.get("text_verbosity"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-verbosity-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Reasoning summary", f"{prefix}-summary-help", "reasoning_summary"),
                    dbc.Select(
                        id=f"{prefix}-summary",
                        value=defaults.get("reasoning_summary", "auto"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-summary-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Temperature", f"{prefix}-temperature-help", "temperature"),
                    dbc.Input(
                        id=f"{prefix}-temperature",
                        type="number",
                        min=0,
                        max=2,
                        step=0.1,
                        value=defaults.get("temperature"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-temperature-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Top P", f"{prefix}-top-p-help", "top_p"),
                    dbc.Input(
                        id=f"{prefix}-top-p",
                        type="number",
                        min=0,
                        max=1,
                        step=0.05,
                        value=defaults.get("top_p"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-top-p-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Max output tokens", f"{prefix}-max-output-help", "max_output_tokens"),
                    dbc.Input(
                        id=f"{prefix}-max-output-tokens",
                        type="number",
                        min=64,
                        step=128,
                        placeholder="No cap",
                        value=defaults.get("max_output_tokens"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-max-output-group",
                className="llm-param-field",
            ),
            html.Div(
                _switch_with_help(
                    f"{prefix}-store",
                    "Store responses",
                    defaults.get("store", False),
                    "store",
                ),
                id=f"{prefix}-store-group",
                className="llm-param-field llm-param-switch",
            ),
            html.Div(
                _switch_with_help(
                    f"{prefix}-parallel-tool-calls",
                    "Parallel tool calls",
                    defaults.get("parallel_tool_calls", True),
                    "parallel_tool_calls",
                ),
                id=f"{prefix}-parallel-tool-calls-group",
                className="llm-param-field llm-param-switch",
            ),
        ],
        className="llm-param-controls",
    )


def _model_panel(role, title, icon, default_model, lang="en"):
    prefix = f"{role}-llm"
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className=f"fa-solid {icon} model-panel-icon"),
                            html.Div(
                                [
                                    html.H6(title, className="model-panel-title"),
                                    html.Small("Model and supported parameters", className="model-panel-meta"),
                                ]
                            ),
                        ],
                        className="model-panel-heading",
                    ),
                    dbc.Select(
                        id=prefix,
                        options=get_model_options_for_provider("openai", role),
                        value=default_model,
                        className="config-select mt-3",
                    ),
                    html.Div(
                        _field(
                            "Custom model ID",
                            dbc.Input(
                                id=f"{prefix}-custom-model",
                                type="text",
                                placeholder="provider/model-name",
                                value="",
                                className="config-input",
                            ),
                            "keyboard",
                        ),
                        id=f"{prefix}-custom-model-group",
                        className="model-custom-field",
                        style={"display": "none"},
                    ),
                    html.Div(id=f"{prefix}-info", className="llm-model-info"),
                    dbc.Accordion(
                        [
                            dbc.AccordionItem(
                                _llm_param_controls(role, default_model),
                                title=t(lang, "config.advanced_parameters"),
                                item_id=f"{role}-params",
                            )
                        ],
                        id=f"{prefix}-params-accordion",
                        start_collapsed=True,
                        flush=True,
                        className="config-subaccordion mt-3",
                    ),
                ]
            )
        ],
        className="model-panel",
    )


def _run_button(lang="en"):
    return dbc.Button(
        [html.I(className="fa-solid fa-play me-2"), t(lang, "config.start_analysis")],
        id="control-btn",
        color="primary",
        size="lg",
        className="w-100 config-primary-action",
    )


def _core_setup(lang="en"):
    return html.Div(
        [
            _field(
                t(lang, "config.symbols"),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Div(id="symbol-selected-chips", className="symbol-chip-list"),
                                        dcc.Input(
                                            id="symbol-query-input",
                                            type="text",
                                            value="",
                                            debounce=False,
                                            placeholder=t(lang, "config.symbols.placeholder"),
                                            className="symbol-query-input",
                                        ),
                                    ],
                                    className="symbol-combobox",
                                ),
                                html.Div(id="symbol-suggestions", className="symbol-suggestions-menu"),
                            ],
                            className="symbol-combobox-wrap",
                        ),
                        dcc.Input(
                            id="ticker-input",
                            type="hidden",
                            value="NVDA, AMD, TSLA",
                        ),
                        html.Div(id="symbol-search-status", className="symbol-search-status"),
                    ],
                    className="symbol-picker",
                ),
                "tag",
            ),
            html.Div(
                [_analyst_checkbox(component_id, label, icon) for component_id, label, icon in ANALYSTS],
                className="analyst-grid",
            ),
            html.Div(
                [
                    _field(
                        t(lang, "config.research_depth"),
                        dbc.RadioItems(
                            id="research-depth",
                            options=[
                                {"label": t(lang, "config.depth.shallow"), "value": "Shallow"},
                                {"label": t(lang, "config.depth.medium"), "value": "Medium"},
                                {"label": t(lang, "config.depth.deep"), "value": "Deep"},
                            ],
                            value="Shallow",
                            inline=True,
                            className="segmented-radio",
                        ),
                        "layer-group",
                    ),
                    html.Div(id="research-depth-info", className="config-status-slot"),
                ],
                className="config-two-column",
            ),
            html.Div(
                [
                    _field(
                        t(lang, "config.trading_horizon"),
                        dbc.RadioItems(
                            id="trading-horizon",
                            options=[
                                {"label": t(lang, "config.horizon.swing"), "value": "swing"},
                                {"label": t(lang, "config.horizon.position"), "value": "position"},
                                {"label": t(lang, "config.horizon.trend"), "value": "trend"},
                            ],
                            value="swing",
                            inline=True,
                            className="segmented-radio",
                        ),
                        "timeline",
                    ),
                    html.Div(id="trading-horizon-info", className="config-status-slot"),
                ],
                className="config-two-column",
            ),
            html.Div(
                [
                    html.Div(
                        dbc.Switch(
                            id="allow-shorts",
                            label=t(lang, "config.allow_shorts"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                    html.Div(id="trading-mode-info", className="config-status-slot"),
                ],
                className="config-two-column",
            ),
        ],
        className="config-section-body",
    )


def _schedule_and_trading(lang="en"):
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        dbc.Switch(
                            id="loop-enabled",
                            label=t(lang, "config.loop_mode"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                    _field(
                        t(lang, "config.loop_interval"),
                        dbc.Input(
                            id="loop-interval",
                            type="number",
                            placeholder="60",
                            value=60,
                            min=1,
                            max=1440,
                            className="config-input",
                        ),
                        "clock",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(
                [
                    html.Div(
                        dbc.Switch(
                            id="market-hour-enabled",
                            label=t(lang, "config.market_hour"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                    _field(
                        t(lang, "config.trading_hours"),
                        dbc.Input(
                            id="market-hours-input",
                            type="text",
                            placeholder="11,13",
                            value="",
                            className="config-input",
                        ),
                        "calendar-days",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(id="market-hours-validation", className="config-validation-slot"),
            html.Div(id="scheduling-mode-info", className="config-status-slot"),
            html.Div(
                [
                    html.Div(
                        dbc.Switch(
                            id="trade-after-analyze",
                            label=t(lang, "config.trade_after"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                    _field(
                        t(lang, "config.order_amount"),
                        dbc.InputGroup(
                            [
                                dbc.InputGroupText("$"),
                                dbc.Input(
                                    id="trade-dollar-amount",
                                    type="number",
                                    placeholder="4500",
                                    value=4500,
                                    min=1,
                                    max=10000000,
                                    className="config-input",
                                ),
                            ],
                            className="config-input-group",
                        ),
                        "sack-dollar",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(
                [
                    html.Div(
                        dbc.Switch(
                            id="trend-execution-enabled",
                            label=t(lang, "config.trend_execution"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                    html.Div(
                        "Research-only unless trend execution is explicitly enabled.",
                        className="config-muted-note",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(id="trade-after-analyze-info", className="config-status-slot"),
        ],
        className="config-section-body",
    )


def _model_setup(lang="en"):
    return html.Div(
        [
            html.Div(
                [
                    _field(
                        t(lang, "config.provider"),
                        dbc.Select(
                            id="llm-provider",
                            options=get_llm_provider_options(),
                            value="openai",
                            className="config-select",
                        ),
                        "network-wired",
                    ),
                    html.Div(
                        _field(
                            t(lang, "config.endpoint_override"),
                            dbc.Input(
                                id="backend-url",
                                type="text",
                                placeholder=t(lang, "config.endpoint_placeholder"),
                                value="",
                                className="config-input",
                            ),
                            "server",
                        ),
                        id="backend-url-group",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(id="llm-provider-info", className="config-status-slot"),
            html.Div(
                [
                    html.Div(
                        _field(
                            t(lang, "config.gemini_thinking"),
                            dbc.Select(
                                id="google-thinking-level",
                                options=[
                                    {"label": t(lang, "config.provider_default"), "value": ""},
                                    {"label": t(lang, "config.high_thinking"), "value": "high"},
                                    {"label": t(lang, "config.minimal_disabled"), "value": "minimal"},
                                ],
                                value="",
                                className="config-select",
                            ),
                            "lightbulb",
                        ),
                        id="google-thinking-level-group",
                        style={"display": "none"},
                    ),
                    html.Div(
                        _field(
                            t(lang, "config.claude_effort"),
                            dbc.Select(
                                id="anthropic-effort",
                                options=[
                                    {"label": t(lang, "config.provider_default"), "value": ""},
                                    {"label": t(lang, "config.high"), "value": "high"},
                                    {"label": t(lang, "config.medium"), "value": "medium"},
                                    {"label": t(lang, "config.low"), "value": "low"},
                                ],
                                value="",
                                className="config-select",
                            ),
                            "gauge-high",
                        ),
                        id="anthropic-effort-group",
                        style={"display": "none"},
                    ),
                ],
                className="config-two-column provider-options-grid",
            ),
            html.Div(
                [
                    _field(
                        t(lang, "config.output_language"),
                        dbc.Input(
                            id="output-language",
                            type="text",
                            value="zh-CN",
                            className="config-input",
                        ),
                        "language",
                    ),
                    html.Div(
                        dbc.Switch(
                            id="checkpoint-enabled",
                            label=t(lang, "config.checkpoint"),
                            value=False,
                            className="config-switch",
                        ),
                        className="config-toggle-tile",
                    ),
                ],
                className="config-two-column",
            ),
            html.Div(
                [
                    _model_panel("quick", t(lang, "config.quick_thinker"), "bolt", "gpt-5.4-mini", lang=lang),
                    _model_panel("deep", t(lang, "config.deep_thinker"), "brain", "gpt-5.4", lang=lang),
                ],
                className="model-grid",
            ),
        ],
        className="config-section-body",
    )


def create_config_panel(lang="en"):
    """Create the configuration panel for the web UI."""
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.H4(t(lang, "config.title"), className="config-title"),
                                html.Div(t(lang, "config.subtitle"), className="config-subtitle"),
                            ]
                        ),
                        html.Div(
                            [
                                html.I(className="fa-solid fa-wand-magic-sparkles me-2"),
                                t(lang, "config.badge"),
                            ],
                            className="config-badge",
                        ),
                    ],
                    className="config-header",
                ),
                dbc.Accordion(
                    [
                        dbc.AccordionItem(
                            _core_setup(lang=lang),
                            title=_accordion_title("fa-sliders", t(lang, "config.setup.title"), t(lang, "config.setup.subtitle")),
                            item_id="setup",
                        ),
                        dbc.AccordionItem(
                            _schedule_and_trading(lang=lang),
                            title=_accordion_title("fa-calendar-check", t(lang, "config.execution.title"), t(lang, "config.execution.subtitle")),
                            item_id="automation",
                        ),
                        dbc.AccordionItem(
                            _model_setup(lang=lang),
                            title=_accordion_title("fa-microchip", t(lang, "config.models.title"), t(lang, "config.models.subtitle")),
                            item_id="models",
                        ),
                    ],
                    active_item=["setup", "models"],
                    always_open=True,
                    className="config-accordion",
                ),
                html.Div(
                    [
                        html.Div(id="control-button-container", children=[_run_button(lang=lang)]),
                        html.Div(id="result-text", className="result-status mt-3"),
                    ],
                    className="config-action-bar",
                ),
            ]
        ),
        className="mb-4 analysis-config-card",
    )
