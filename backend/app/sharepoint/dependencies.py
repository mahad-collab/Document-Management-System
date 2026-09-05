"""
Provides a single, reused SharePointGraphClient for the app's lifetime,
rather than constructing a new httpx.AsyncClient (and therefore a new
connection pool) per request.
"""
from app.core.config import get_settings
from app.sharepoint.client import SharePointGraphClient

_client: SharePointGraphClient | None = None


def get_sharepoint_client() -> SharePointGraphClient:
    global _client
    if _client is None:
        _client = SharePointGraphClient(settings=get_settings())
    return _client


async def close_sharepoint_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
