from __future__ import annotations


DEFAULT_OUTPUT_LANGUAGE = "zh-CN"


def output_language(config: dict | None = None) -> str:
    configured = (config or {}).get("output_language") or DEFAULT_OUTPUT_LANGUAGE
    text = str(configured).strip()
    return text or DEFAULT_OUTPUT_LANGUAGE


def language_instruction(config: dict | None = None) -> str:
    language = output_language(config)
    return (
        f"Write the analysis in {language}; keep exact action tokens and the final "
        "transaction proposal line in English, for example "
        "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**."
    )
