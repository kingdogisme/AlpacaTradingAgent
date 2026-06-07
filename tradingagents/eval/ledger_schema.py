"""SQLite schema for EpisodeLedger."""

from __future__ import annotations

SCHEMA_SQL = r"""
                CREATE TABLE IF NOT EXISTS episodes (
                    run_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    selected_analysts_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    final_signal TEXT,
                    audit_path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_symbol_date ON episodes(symbol, trade_date);
                CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);

                CREATE TABLE IF NOT EXISTS decisions (
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    action TEXT,
                    confidence TEXT,
                    advisory_rating TEXT,
                    trading_mode TEXT,
                    horizon TEXT,
                    thesis TEXT,
                    invalidation TEXT,
                    risk_budget TEXT,
                    position_plan TEXT,
                    raw_text TEXT NOT NULL,
                    parser_status TEXT NOT NULL,
                    parser_warnings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, stage, agent_name),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action);

                CREATE TABLE IF NOT EXISTS rewards (
                    run_id TEXT NOT NULL,
                    reward_version TEXT NOT NULL,
                    reward_status TEXT NOT NULL DEFAULT 'resolved',
                    holding_days INTEGER NOT NULL,
                    raw_return REAL,
                    benchmark_return REAL,
                    alpha_return REAL,
                    oracle_label TEXT,
                    classification_reward REAL,
                    pnl_reward REAL,
                    reward_scalar REAL,
                    components_json TEXT NOT NULL,
                    resolved_at TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    PRIMARY KEY(run_id, reward_version),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );

                CREATE TABLE IF NOT EXISTS evaluation_targets (
                    target_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    run_id TEXT,
                    plan_id TEXT,
                    candidate_id TEXT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    horizon TEXT,
                    anchor_date TEXT NOT NULL,
                    holding_days INTEGER NOT NULL,
                    source TEXT,
                    trigger_status TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    system_version TEXT,
                    prompt_version TEXT,
                    config_hash TEXT,
                    run_policy TEXT,
                    leakage_risk TEXT NOT NULL DEFAULT 'unknown',
                    data_cutoff TEXT,
                    source_time_range_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_targets_type_symbol
                    ON evaluation_targets(target_type, symbol);
                CREATE INDEX IF NOT EXISTS idx_eval_targets_anchor
                    ON evaluation_targets(anchor_date);
                CREATE INDEX IF NOT EXISTS idx_eval_targets_run
                    ON evaluation_targets(run_id);
                CREATE INDEX IF NOT EXISTS idx_eval_targets_plan
                    ON evaluation_targets(plan_id);
                CREATE INDEX IF NOT EXISTS idx_eval_targets_candidate
                    ON evaluation_targets(candidate_id);

                CREATE TABLE IF NOT EXISTS evaluation_outcomes (
                    target_id TEXT NOT NULL,
                    reward_version TEXT NOT NULL,
                    evaluation_status TEXT NOT NULL,
                    holding_days INTEGER NOT NULL,
                    raw_return REAL,
                    benchmark_return REAL,
                    alpha_return REAL,
                    oracle_label TEXT,
                    classification_reward REAL,
                    pnl_reward REAL,
                    reward_scalar REAL,
                    mfe REAL,
                    mae REAL,
                    components_json TEXT NOT NULL,
                    system_version TEXT,
                    prompt_version TEXT,
                    config_hash TEXT,
                    run_policy TEXT,
                    leakage_risk TEXT NOT NULL DEFAULT 'unknown',
                    data_cutoff TEXT,
                    source_time_range_json TEXT NOT NULL DEFAULT '{}',
                    resolved_at TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    PRIMARY KEY(target_id, reward_version),
                    FOREIGN KEY(target_id) REFERENCES evaluation_targets(target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_outcomes_status
                    ON evaluation_outcomes(evaluation_status);

                CREATE TABLE IF NOT EXISTS layer_evaluation_targets (
                    target_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    run_id TEXT,
                    report_id TEXT,
                    decision_id TEXT,
                    plan_id TEXT,
                    execution_id TEXT,
                    symbol TEXT NOT NULL,
                    horizon TEXT,
                    anchor_date TEXT NOT NULL,
                    audit_refs_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_layer_type
                    ON layer_evaluation_targets(layer, target_type);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_run
                    ON layer_evaluation_targets(run_id);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_symbol_date
                    ON layer_evaluation_targets(symbol, anchor_date);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_report
                    ON layer_evaluation_targets(report_id);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_decision
                    ON layer_evaluation_targets(decision_id);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_plan
                    ON layer_evaluation_targets(plan_id);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_execution
                    ON layer_evaluation_targets(execution_id);

                CREATE TABLE IF NOT EXISTS layer_evaluation_records (
                    evaluation_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    evaluator_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    failure_tags_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL DEFAULT '',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES layer_evaluation_targets(target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_layer_eval_records_target
                    ON layer_evaluation_records(target_id);
                CREATE INDEX IF NOT EXISTS idx_layer_eval_records_layer_status
                    ON layer_evaluation_records(layer, status);

                CREATE TABLE IF NOT EXISTS trace_spans (
                    run_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    span_type TEXT NOT NULL,
                    agent_name TEXT,
                    node_name TEXT,
                    tool_name TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    artifact_ref TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, span_id),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_trace_spans_run_type ON trace_spans(run_id, span_type);

                CREATE TABLE IF NOT EXISTS experiments (
                    run_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    quick_model TEXT NOT NULL,
                    deep_model TEXT NOT NULL,
                    selected_analysts_json TEXT NOT NULL,
                    memory_policy TEXT NOT NULL,
                    critic_version TEXT,
                    reward_version TEXT,
                    leakage_risk TEXT NOT NULL,
                    system_version TEXT,
                    git_commit TEXT,
                    dirty_diff_hash TEXT,
                    run_policy TEXT,
                    data_snapshot_id TEXT,
                    run_started_at TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_experiments_hash ON experiments(config_hash);
                CREATE INDEX IF NOT EXISTS idx_experiments_experiment_id ON experiments(experiment_id);

                CREATE TABLE IF NOT EXISTS memory_items (
                    memory_item_id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT,
                    horizon TEXT,
                    state TEXT,
                    created_by TEXT,
                    promotion_score REAL NOT NULL DEFAULT 0,
                    last_evaluated_at TEXT,
                    source_run_id TEXT,
                    source_ref TEXT,
                    evidence_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_items_type_status ON memory_items(memory_type, status);

                CREATE TABLE IF NOT EXISTS memory_links (
                    memory_item_id TEXT NOT NULL,
                    linked_type TEXT NOT NULL,
                    linked_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(memory_item_id, linked_type, linked_id, relation),
                    FOREIGN KEY(memory_item_id) REFERENCES memory_items(memory_item_id)
                );

                CREATE TABLE IF NOT EXISTS memory_retrievals (
                    run_id TEXT NOT NULL,
                    memory_item_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    score REAL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, memory_item_id, stage),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id),
                    FOREIGN KEY(memory_item_id) REFERENCES memory_items(memory_item_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_retrievals_run ON memory_retrievals(run_id);

                CREATE TABLE IF NOT EXISTS memory_promotions (
                    memory_item_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    promoted_by TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(memory_item_id, to_status, created_at),
                    FOREIGN KEY(memory_item_id) REFERENCES memory_items(memory_item_id)
                );

                CREATE TABLE IF NOT EXISTS critic_records (
                    run_id TEXT NOT NULL,
                    critic_version TEXT NOT NULL,
                    failure_tags_json TEXT NOT NULL,
                    evidence_spans_json TEXT NOT NULL,
                    reward_snapshot_json TEXT NOT NULL,
                    reflection_text TEXT NOT NULL,
                    improvement_candidates_json TEXT NOT NULL,
                    parser_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, critic_version),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );

                CREATE TABLE IF NOT EXISTS run_index (
                    index_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    horizon TEXT,
                    status TEXT NOT NULL,
                    final_action TEXT,
                    confidence TEXT,
                    advisory_rating TEXT,
                    final_signal TEXT,
                    prompt_version TEXT,
                    config_hash TEXT,
                    model_provider TEXT,
                    quick_model TEXT,
                    deep_model TEXT,
                    selected_analysts_json TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    quality_pass INTEGER NOT NULL,
                    quality_warn INTEGER NOT NULL,
                    quality_fail INTEGER NOT NULL,
                    quality_unknown INTEGER NOT NULL,
                    critical_failures_json TEXT NOT NULL,
                    stale_sources_json TEXT NOT NULL,
                    fallback_sources_json TEXT NOT NULL,
                    flags_json TEXT NOT NULL,
                    audit_ref TEXT,
                    audit_path TEXT,
                    decision_ref TEXT,
                    quality_index_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_index_symbol_date ON run_index(symbol, trade_date);
                CREATE INDEX IF NOT EXISTS idx_run_index_horizon ON run_index(horizon);
                CREATE INDEX IF NOT EXISTS idx_run_index_prompt ON run_index(prompt_version);
                CREATE INDEX IF NOT EXISTS idx_run_index_config ON run_index(config_hash);
                CREATE INDEX IF NOT EXISTS idx_run_index_quality ON run_index(quality_status);

                CREATE TABLE IF NOT EXISTS quality_index (
                    run_id TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    tool_name TEXT,
                    agent_type TEXT,
                    source_id TEXT NOT NULL,
                    provider TEXT,
                    dataset_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    freshness TEXT NOT NULL,
                    accuracy TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    criticality TEXT,
                    flags_json TEXT NOT NULL,
                    observed_at TEXT,
                    source_age_days INTEGER,
                    fallback_from TEXT,
                    timestamp TEXT,
                    requested_trade_date TEXT,
                    source_timestamp TEXT,
                    max_allowed_timestamp TEXT,
                    leakage_status TEXT NOT NULL DEFAULT 'unknown',
                    inputs_json TEXT NOT NULL,
                    output_preview TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, artifact_ref),
                    FOREIGN KEY(run_id) REFERENCES episodes(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_quality_index_status ON quality_index(status);
                CREATE INDEX IF NOT EXISTS idx_quality_index_source ON quality_index(source_id);
                CREATE INDEX IF NOT EXISTS idx_quality_index_dataset ON quality_index(dataset_type);

                CREATE TABLE IF NOT EXISTS retrieval_packs (
                    pack_id TEXT PRIMARY KEY,
                    pack_type TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    run_id TEXT,
                    symbol TEXT,
                    horizon TEXT,
                    token_budget INTEGER NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_retrieval_packs_type ON retrieval_packs(pack_type);
                CREATE INDEX IF NOT EXISTS idx_retrieval_packs_run ON retrieval_packs(run_id);
                CREATE INDEX IF NOT EXISTS idx_retrieval_packs_symbol_horizon ON retrieval_packs(symbol, horizon);

                CREATE TABLE IF NOT EXISTS retrieval_pack_items (
                    pack_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(pack_id, item_id),
                    FOREIGN KEY(pack_id) REFERENCES retrieval_packs(pack_id)
                );

                CREATE TABLE IF NOT EXISTS quality_observations (
                    run_id TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    symbol TEXT,
                    source_id TEXT NOT NULL,
                    dataset_type TEXT NOT NULL,
                    observation_type TEXT NOT NULL,
                    observed_at TEXT,
                    value_num REAL,
                    unit TEXT,
                    extraction_status TEXT NOT NULL,
                    flags_json TEXT NOT NULL,
                    source_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, artifact_ref, observation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_quality_observations_run ON quality_observations(run_id);
                CREATE INDEX IF NOT EXISTS idx_quality_observations_symbol ON quality_observations(symbol, dataset_type);

                CREATE TABLE IF NOT EXISTS quality_reconciliation (
                    reconciliation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    symbol TEXT,
                    dataset_type TEXT NOT NULL,
                    check_type TEXT NOT NULL,
                    primary_source TEXT,
                    comparison_source TEXT,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    delta_pct REAL,
                    flags_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quality_reconciliation_run ON quality_reconciliation(run_id);
                CREATE INDEX IF NOT EXISTS idx_quality_reconciliation_status ON quality_reconciliation(status);

                CREATE TABLE IF NOT EXISTS source_reliability (
                    source_id TEXT NOT NULL,
                    dataset_type TEXT NOT NULL,
                    window_days INTEGER NOT NULL,
                    quality_pass INTEGER NOT NULL,
                    quality_warn INTEGER NOT NULL,
                    quality_fail INTEGER NOT NULL,
                    quality_unknown INTEGER NOT NULL,
                    fallback_count INTEGER NOT NULL,
                    stale_count INTEGER NOT NULL,
                    critical_fail_count INTEGER NOT NULL,
                    pass_rate REAL NOT NULL,
                    fallback_rate REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_id, dataset_type, window_days)
                );
"""


def apply_schema_migrations(conn) -> None:
    reward_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(rewards)").fetchall()
    }
    if "reward_status" not in reward_columns:
        conn.execute(
            "ALTER TABLE rewards ADD COLUMN reward_status TEXT NOT NULL DEFAULT 'resolved'"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rewards_status ON rewards(reward_status)")
    memory_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()
    }
    memory_migrations = {
        "symbol": "ALTER TABLE memory_items ADD COLUMN symbol TEXT",
        "horizon": "ALTER TABLE memory_items ADD COLUMN horizon TEXT",
        "state": "ALTER TABLE memory_items ADD COLUMN state TEXT",
        "created_by": "ALTER TABLE memory_items ADD COLUMN created_by TEXT",
        "promotion_score": "ALTER TABLE memory_items ADD COLUMN promotion_score REAL NOT NULL DEFAULT 0",
        "last_evaluated_at": "ALTER TABLE memory_items ADD COLUMN last_evaluated_at TEXT",
        "source_run_id": "ALTER TABLE memory_items ADD COLUMN source_run_id TEXT",
        "source_ref": "ALTER TABLE memory_items ADD COLUMN source_ref TEXT",
    }
    for column, statement in memory_migrations.items():
        if column not in memory_columns:
            conn.execute(statement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_symbol_horizon ON memory_items(symbol, horizon)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_state ON memory_items(state)")
    target_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(evaluation_targets)").fetchall()
    }
    target_migrations = {
        "system_version": "ALTER TABLE evaluation_targets ADD COLUMN system_version TEXT",
        "prompt_version": "ALTER TABLE evaluation_targets ADD COLUMN prompt_version TEXT",
        "config_hash": "ALTER TABLE evaluation_targets ADD COLUMN config_hash TEXT",
        "run_policy": "ALTER TABLE evaluation_targets ADD COLUMN run_policy TEXT",
        "leakage_risk": "ALTER TABLE evaluation_targets ADD COLUMN leakage_risk TEXT NOT NULL DEFAULT 'unknown'",
        "data_cutoff": "ALTER TABLE evaluation_targets ADD COLUMN data_cutoff TEXT",
        "source_time_range_json": "ALTER TABLE evaluation_targets ADD COLUMN source_time_range_json TEXT NOT NULL DEFAULT '{}'",
    }
    for column, statement in target_migrations.items():
        if column not in target_columns:
            conn.execute(statement)
    outcome_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(evaluation_outcomes)").fetchall()
    }
    outcome_migrations = {
        "system_version": "ALTER TABLE evaluation_outcomes ADD COLUMN system_version TEXT",
        "prompt_version": "ALTER TABLE evaluation_outcomes ADD COLUMN prompt_version TEXT",
        "config_hash": "ALTER TABLE evaluation_outcomes ADD COLUMN config_hash TEXT",
        "run_policy": "ALTER TABLE evaluation_outcomes ADD COLUMN run_policy TEXT",
        "leakage_risk": "ALTER TABLE evaluation_outcomes ADD COLUMN leakage_risk TEXT NOT NULL DEFAULT 'unknown'",
        "data_cutoff": "ALTER TABLE evaluation_outcomes ADD COLUMN data_cutoff TEXT",
        "source_time_range_json": "ALTER TABLE evaluation_outcomes ADD COLUMN source_time_range_json TEXT NOT NULL DEFAULT '{}'",
    }
    for column, statement in outcome_migrations.items():
        if column not in outcome_columns:
            conn.execute(statement)
    experiment_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()
    }
    experiment_migrations = {
        "system_version": "ALTER TABLE experiments ADD COLUMN system_version TEXT",
        "git_commit": "ALTER TABLE experiments ADD COLUMN git_commit TEXT",
        "dirty_diff_hash": "ALTER TABLE experiments ADD COLUMN dirty_diff_hash TEXT",
        "run_policy": "ALTER TABLE experiments ADD COLUMN run_policy TEXT",
        "data_snapshot_id": "ALTER TABLE experiments ADD COLUMN data_snapshot_id TEXT",
        "run_started_at": "ALTER TABLE experiments ADD COLUMN run_started_at TEXT",
    }
    for column, statement in experiment_migrations.items():
        if column not in experiment_columns:
            conn.execute(statement)
    quality_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(quality_index)").fetchall()
    }
    quality_migrations = {
        "requested_trade_date": "ALTER TABLE quality_index ADD COLUMN requested_trade_date TEXT",
        "source_timestamp": "ALTER TABLE quality_index ADD COLUMN source_timestamp TEXT",
        "max_allowed_timestamp": "ALTER TABLE quality_index ADD COLUMN max_allowed_timestamp TEXT",
        "leakage_status": "ALTER TABLE quality_index ADD COLUMN leakage_status TEXT NOT NULL DEFAULT 'unknown'",
    }
    for column, statement in quality_migrations.items():
        if column not in quality_columns:
            conn.execute(statement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_targets_provenance ON evaluation_targets(system_version, prompt_version, config_hash, leakage_risk)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_outcomes_leakage ON evaluation_outcomes(leakage_risk)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_index_leakage ON quality_index(leakage_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_layer_type ON layer_evaluation_targets(layer, target_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_run ON layer_evaluation_targets(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_symbol_date ON layer_evaluation_targets(symbol, anchor_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_report ON layer_evaluation_targets(report_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_decision ON layer_evaluation_targets(decision_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_plan ON layer_evaluation_targets(plan_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_targets_execution ON layer_evaluation_targets(execution_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_records_target ON layer_evaluation_records(target_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_eval_records_layer_status ON layer_evaluation_records(layer, status)")
