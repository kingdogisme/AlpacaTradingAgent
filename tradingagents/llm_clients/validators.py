"""Model validators.

Model selection now supports dynamic provider discovery and custom model ids.
Runtime validation should stay permissive so newly available provider models do
not trigger stale local whitelist warnings.
"""


def validate_model(provider: str, model: str) -> bool:
    """Accept provider model ids without local static whitelist enforcement."""
    return True
