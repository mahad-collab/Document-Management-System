"""
Microsoft Graph client for SharePoint document storage.

Design decisions locked in during architecture review (see conversation):
  - App-only permissions (client credentials flow), NOT delegated. One
    service identity, `Sites.Selected` scope on exactly the Puma DMS site.
    Your PostgreSQL RBAC is the sole authorization layer — this client is
    called ONLY after a request has already passed RBAC (see folders/routes.py,
    documents/routes.py in later phases). It never makes its own auth
    decisions.
  - Never expose the app-only token to the frontend (Section 25) — this
    client only runs on the backend; nothing here is importable by anything
    that runs in a browser.
  - Folder/file organization mirrors Section 4's structure: one SharePoint
    site, one document library (drive), department folders as top-level
    folders within it.

Token caching: MSAL's ConfidentialClientApplication has its own in-memory
token cache and handles refresh automatically — acquire_token_for_client()
returns a cached token if still valid, so we don't need to build our own
expiry tracking.
"""
import asyncio
from typing import Optional

import httpx
import msal

from app.core.config import Settings
from app.sharepoint.exceptions import (
    SharePointAuthError,
    SharePointConflictError,
    SharePointError,
    SharePointNotFoundError,
    SharePointRateLimitedError,
)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class SharePointGraphClient:
    """
    Thin async wrapper over the Microsoft Graph endpoints the DMS needs.

    An `httpx.AsyncClient` (or a test double / MockTransport-backed client)
    is injected via `http_client` so tests never need real network access —
    see tests/test_sharepoint_client.py for how the mocked Graph responses
    are wired up.
    """

    def __init__(
        self,
        settings: Settings,
        http_client: Optional[httpx.AsyncClient] = None,
        msal_app: Optional[msal.ConfidentialClientApplication] = None,
    ):
        self._settings = settings
        # msal.ConfidentialClientApplication's constructor performs its own
        # network call (OIDC tenant discovery against login.microsoftonline.com)
        # BEFORE any token is ever requested. Accepting an injected instance
        # lets tests substitute a fake object and avoid that call entirely —
        # there's no way to construct a real one offline.
        self._msal_app = msal_app or msal.ConfidentialClientApplication(
            client_id=settings.ENTRA_CLIENT_ID,
            client_credential=settings.ENTRA_CLIENT_SECRET,
            authority=settings.ENTRA_AUTHORITY,
        )
        # follow_redirects is required: Graph's driveItem "/content" download
        # endpoint responds with a 302 to a separate pre-authenticated blob
        # URL rather than streaming the bytes directly. Without this, the
        # 302's empty body is silently returned as if it were the file,
        # which surfaces downstream as OCR's "Cannot open empty stream" —
        # discovered only once this client was exercised against a real
        # tenant (see README's Phase 2 "verified against a real tenant" note).
        self._http = http_client or httpx.AsyncClient(base_url=GRAPH_BASE_URL, timeout=30.0, follow_redirects=True)
        self.site_id = settings.GRAPH_SITE_ID
        self.drive_id = settings.GRAPH_DRIVE_ID

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- Auth ------------------------------------------------------------

    async def _get_token(self) -> str:
        # msal's client-credential acquisition is synchronous under the
        # hood (it does its own blocking HTTP call); run it in a thread so
        # it doesn't block the event loop.
        result = await asyncio.to_thread(self._msal_app.acquire_token_for_client, scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise SharePointAuthError(
                f"Failed to acquire Graph app-only token: {result.get('error_description', result.get('error'))}"
            )
        return result["access_token"]

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._get_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        response = await self._http.request(method, path, headers=headers, **kwargs)

        if response.status_code == 401:
            raise SharePointAuthError("Graph rejected the app-only token (401)")
        if response.status_code == 404:
            raise SharePointNotFoundError(f"Graph item not found: {method} {path}")
        if response.status_code == 409:
            raise SharePointConflictError(f"Graph conflict: {method} {path}")
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "5"))
            raise SharePointRateLimitedError(retry_after)
        if response.status_code >= 400:
            raise SharePointError(f"Graph API error {response.status_code}: {response.text}")

        return response

    # ---- Folders -----------------------------------------------------------

    async def create_folder(self, name: str, parent_item_id: Optional[str] = None) -> dict:
        """
        Creates a folder. If `parent_item_id` is None, creates it at the
        drive root (used for department top-level folders); otherwise
        creates it as a child of the given item (used for subfolders).

        Returns the created DriveItem (dict) — callers store `id` as the
        folder's `sharepoint_item_id`.
        """
        parent_path = f"items/{parent_item_id}" if parent_item_id else "root"
        path = f"/drives/{self.drive_id}/{parent_path}/children"
        body = {
            "name": name,
            "folder": {},
            # "fail" (not "rename"/"replace") so a name collision surfaces as
            # a clear 409 rather than silently creating "Finance 1".
            "@microsoft.graph.conflictBehavior": "fail",
        }
        response = await self._request("POST", path, json=body)
        return response.json()

    async def list_children(self, item_id: str) -> list[dict]:
        path = f"/drives/{self.drive_id}/items/{item_id}/children"
        response = await self._request("GET", path)
        return response.json().get("value", [])

    # ---- Files ---------------------------------------------------------

    async def upload_small_file(self, parent_item_id: str, filename: str, content: bytes) -> dict:
        """
        Simple upload for files under 4MB (Graph's documented small-file
        limit). Larger files need an upload session (chunked) — not yet
        implemented; see NotImplementedError below. Most scanned invoices/
        contracts (Section 10's primary use case) are well under 4MB, so
        this covers the common path for Phase 2.
        """
        if len(content) > 4 * 1024 * 1024:
            raise NotImplementedError(
                "Files over 4MB need a Graph upload session (chunked upload) — "
                "not yet implemented in this phase."
            )
        path = f"/drives/{self.drive_id}/items/{parent_item_id}:/{filename}:/content"
        response = await self._request(
            "PUT", path, content=content, headers={"Content-Type": "application/octet-stream"}
        )
        return response.json()

    async def download_file(self, item_id: str) -> bytes:
        path = f"/drives/{self.drive_id}/items/{item_id}/content"
        response = await self._request("GET", path)
        return response.content

    async def upload_new_version(self, item_id: str, content: bytes) -> dict:
        """
        Overwrites an existing item's content by item id (as opposed to
        `upload_small_file`, which creates a NEW item under a parent by
        name). SharePoint's document library versioning (enabled by
        default) automatically snapshots the previous content as a new
        version — Graph doesn't need an explicit "create version" call.

        Same 4MB simple-upload limit as upload_small_file applies.
        """
        if len(content) > 4 * 1024 * 1024:
            raise NotImplementedError(
                "Files over 4MB need a Graph upload session (chunked upload) — "
                "not yet implemented in this phase."
            )
        path = f"/drives/{self.drive_id}/items/{item_id}/content"
        response = await self._request(
            "PUT", path, content=content, headers={"Content-Type": "application/octet-stream"}
        )
        return response.json()

    async def list_versions(self, item_id: str) -> list[dict]:
        """Returns SharePoint's own version history for this item (each with its own 'id' like '1.0', '2.0')."""
        path = f"/drives/{self.drive_id}/items/{item_id}/versions"
        response = await self._request("GET", path)
        return response.json().get("value", [])

    async def get_item(self, item_id: str) -> dict:
        path = f"/drives/{self.drive_id}/items/{item_id}"
        response = await self._request("GET", path)
        return response.json()

    # ---- Delete / restore ------------------------------------------------

    async def delete_item(self, item_id: str) -> None:
        """
        Moves the item to SharePoint's recycle bin (Graph DELETE is
        non-destructive here — SharePoint intercepts it). Per our Step-2
        decision, this is an EFFECT of PostgreSQL's soft-delete, called
        after the DB state is already updated — not the other way around.
        """
        path = f"/drives/{self.drive_id}/items/{item_id}"
        await self._request("DELETE", path)

    async def restore_item(self, item_id: str) -> dict:
        """
        Restores an item from the recycle bin back to its original location.

        CAVEAT (flagged honestly rather than assumed correct): Graph's
        documented restore behavior differs between OneDrive personal
        drives and SharePoint document libraries, and this endpoint's exact
        behavior for a SharePoint-backed drive has NOT been verified
        against a real tenant (no network access to graph.microsoft.com in
        the environment this was built in). If this 404s in your real
        tenant, the alternative is the site-level recycle bin API
        (`GET /sites/{site-id}/recycleBin` -> POST .../items/{id}/restore),
        which may be what's actually needed here — verify against a real
        site before relying on this in production.
        """
        path = f"/drives/{self.drive_id}/items/{item_id}/restore"
        response = await self._request("POST", path)
        return response.json()
