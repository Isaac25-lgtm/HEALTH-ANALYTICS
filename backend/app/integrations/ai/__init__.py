"""AI Gateway boundary. Disabled unless AI_ENABLED and a key are configured."""

from app.config import get_settings


def ai_enabled() -> bool:
    settings = get_settings()
    return settings.ai_enabled and bool(settings.ai_api_key and settings.ai_base_url)
