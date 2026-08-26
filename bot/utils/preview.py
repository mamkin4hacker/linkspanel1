import secrets

from api.cache import set_preview_config


def _generate_token() -> str:
    return secrets.token_urlsafe(12)


async def create_preview(user_id: int, config: dict) -> str:
    token = _generate_token()
    await set_preview_config(user_id, config, token, ttl=600)
    return token
