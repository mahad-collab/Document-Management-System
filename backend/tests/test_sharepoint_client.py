"""
Tests for SharePointGraphClient using a fake HTTP transport.

IMPORTANT — what these tests do and don't prove:

  They DO prove: the client builds the correct Graph URLs, methods, and
  request bodies for each operation; correctly maps Graph's HTTP status
  codes to our typed exceptions; and correctly threads the bearer token
  through every request.

  They do NOT prove: that a real Entra ID app registration with real
  Sites.Selected permissions actually works against a real tenant. This
  sandbox has no network access to login.microsoftonline.com or
  graph.microsoft.com — that verification has to happen in a real
  environment with real credentials.

We bypass MSAL's real token acquisition (which would try to reach
login.microsoftonline.com) by monkeypatching `acquire_token_for_client`
directly on the client's msal app instance.
"""
import httpx
import pytest

from app.core.config import Settings
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.exceptions import (
    SharePointAuthError,
    SharePointConflictError,
    SharePointNotFoundError,
    SharePointRateLimitedError,
)


def _fake_settings() -> Settings:
    return Settings(
        APP_SECRET_KEY="test",
        DATABASE_URL="postgresql+asyncpg://x:x@localhost/x",
        DATABASE_URL_SYNC="postgresql+psycopg2://x:x@localhost/x",
        ENTRA_TENANT_ID="fake-tenant",
        ENTRA_CLIENT_ID="fake-client",
        ENTRA_CLIENT_SECRET="fake-secret",
        GRAPH_SITE_ID="fake-site-id",
        GRAPH_DRIVE_ID="fake-drive-id",
    )


class _FakeMsalApp:
    """Stands in for msal.ConfidentialClientApplication — the real class's
    constructor makes a network call (OIDC tenant discovery) we can't allow
    in this test environment, and don't want in any offline test run."""

    def __init__(self, token_response: dict):
        self._token_response = token_response

    def acquire_token_for_client(self, scopes):
        return self._token_response


def _client_with_mock_transport(handler, token_response: dict | None = None) -> SharePointGraphClient:
    """Builds a client whose httpx transport is fully faked, and whose MSAL
    app is a fake that never touches the network."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://graph.microsoft.com/v1.0", transport=transport, timeout=5.0
    )
    fake_msal = _FakeMsalApp(token_response or {"access_token": "fake-token"})
    return SharePointGraphClient(settings=_fake_settings(), http_client=http_client, msal_app=fake_msal)


@pytest.mark.asyncio
async def test_create_folder_at_root_builds_correct_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.content
        return httpx.Response(
            201,
            json={"id": "new-folder-item-id", "name": "FIN", "folder": {}},
        )

    client = _client_with_mock_transport(handler)
    result = await client.create_folder(name="FIN")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://graph.microsoft.com/v1.0/drives/fake-drive-id/root/children"
    assert captured["auth"] == "Bearer fake-token"
    assert b'"name": "FIN"' in captured["body"] or b'"name":"FIN"' in captured["body"]
    assert result["id"] == "new-folder-item-id"

    await client.aclose()


@pytest.mark.asyncio
async def test_create_folder_under_parent_uses_parent_item_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(201, json={"id": "subfolder-id", "name": "Invoices"})

    client = _client_with_mock_transport(handler)
    await client.create_folder(name="Invoices", parent_item_id="parent-item-id")

    assert (
        captured["url"]
        == "https://graph.microsoft.com/v1.0/drives/fake-drive-id/items/parent-item-id/children"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_create_folder_conflict_maps_to_typed_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"message": "name already exists"}})

    client = _client_with_mock_transport(handler)
    with pytest.raises(SharePointConflictError):
        await client.create_folder(name="Finance")
    await client.aclose()


@pytest.mark.asyncio
async def test_get_item_not_found_maps_to_typed_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    client = _client_with_mock_transport(handler)
    with pytest.raises(SharePointNotFoundError):
        await client.get_item("nonexistent-id")
    await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_maps_to_typed_exception_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"}, json={"error": {"message": "too many requests"}})

    client = _client_with_mock_transport(handler)
    with pytest.raises(SharePointRateLimitedError) as exc_info:
        await client.get_item("some-id")
    assert exc_info.value.retry_after_seconds == 12.0
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_failure_when_token_acquisition_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        # Should never actually be reached — token acquisition fails first.
        return httpx.Response(200, json={})

    client = _client_with_mock_transport(
        handler,
        token_response={"error": "invalid_client", "error_description": "Invalid client secret"},
    )

    with pytest.raises(SharePointAuthError):
        await client.get_item("some-id")
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_small_file_builds_correct_path_and_content():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content"] = request.content
        captured["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(201, json={"id": "uploaded-file-id", "name": "invoice.pdf"})

    client = _client_with_mock_transport(handler)
    result = await client.upload_small_file(
        parent_item_id="folder-item-id", filename="invoice.pdf", content=b"%PDF-1.4 fake pdf bytes"
    )

    assert captured["method"] == "PUT"
    assert (
        captured["url"]
        == "https://graph.microsoft.com/v1.0/drives/fake-drive-id/items/folder-item-id:/invoice.pdf:/content"
    )
    assert captured["content"] == b"%PDF-1.4 fake pdf bytes"
    assert result["id"] == "uploaded-file-id"
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_large_file_raises_not_implemented():
    client = _client_with_mock_transport(lambda r: httpx.Response(200, json={}))
    oversized_content = b"x" * (5 * 1024 * 1024)  # 5MB, over the 4MB simple-upload limit

    with pytest.raises(NotImplementedError):
        await client.upload_small_file(parent_item_id="x", filename="big.pdf", content=oversized_content)
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_item_calls_correct_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(204)

    client = _client_with_mock_transport(handler)
    await client.delete_item("item-to-delete")

    assert captured["method"] == "DELETE"
    assert captured["url"] == "https://graph.microsoft.com/v1.0/drives/fake-drive-id/items/item-to-delete"
    await client.aclose()
