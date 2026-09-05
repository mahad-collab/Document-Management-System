"""
Document-level RBAC tests.

Complements test_rbac.py (which tests the `user_has_department_permission`
primitive directly) by exercising the actual document endpoints, since
that's where a real vulnerability would surface — e.g. Section 8's
guarantee that knowing a document's ID isn't enough on its own.
"""
import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.departments.models import Department
from app.documents.models import Document
from app.folders.models import Folder
from app.main import app
from app.roles.models import RoleName
from app.roles.user_role import UserRole
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client
from app.users.models import User


class _FakeMsal:
    def acquire_token_for_client(self, scopes):
        return {"access_token": "fake"}


def _fake_sharepoint_client() -> SharePointGraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "unused-in-these-tests"})

    fake_http = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0", transport=httpx.MockTransport(handler))
    return SharePointGraphClient(settings=get_settings(), http_client=fake_http, msal_app=_FakeMsal())


def _cookie_for(user_id) -> str:
    import base64
    import json

    import itsdangerous

    signer = itsdangerous.TimestampSigner(get_settings().APP_SECRET_KEY)
    data = json.dumps({"user_id": str(user_id)}).encode()
    return signer.sign(base64.b64encode(data)).decode()


async def _http_client_as(user_id) -> httpx.AsyncClient:
    """A fresh client per identity — NEVER reuse one client's cookie jar
    across identities. Reusing a jar after the server has already issued
    its own Set-Cookie response can leave two 'session' cookies with
    different domain attributes coexisting, and which one wins is not
    guaranteed — this produced a false-positive access result in ad-hoc
    testing during development. One client per identity avoids the whole
    class of bug."""
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", _cookie_for(user_id))
    return client


@pytest.mark.asyncio
async def test_finance_user_cannot_view_other_departments_document(db: AsyncSession, seeded_roles, departments):
    finance, hr = departments["finance"], departments["hr"]

    hr_folder = Folder(name="HR Docs", department_id=hr.id, sharepoint_item_id="sp-hr-folder")
    db.add(hr_folder)
    await db.flush()

    hr_user_owner = User(entra_object_id="oid-hr-owner", email="hrowner@puma.test", display_name="HR Owner")
    db.add(hr_user_owner)
    await db.flush()

    hr_document = Document(
        name="salary_review.pdf",
        department_id=hr.id,
        folder_id=hr_folder.id,
        uploaded_by=hr_user_owner.id,
        sharepoint_item_id="sp-hr-doc-1",
        file_size=1234,
        file_type="pdf",
    )
    db.add(hr_document)

    finance_user = User(entra_object_id="oid-fin-user", email="finonly@puma.test", display_name="Finance Only")
    db.add(finance_user)
    await db.flush()
    db.add(
        UserRole(
            user_id=finance_user.id,
            role_id=seeded_roles[RoleName.DEPARTMENT_USER].id,
            department_id=finance.id,
        )
    )
    await db.commit()
    await db.refresh(hr_document)

    app.dependency_overrides[get_sharepoint_client] = _fake_sharepoint_client
    try:
        client = await _http_client_as(finance_user.id)
        async with client:
            resp = await client.get(f"/documents/{hr_document.id}")
            assert resp.status_code == 404  # not 403 — existence itself shouldn't be confirmed

            resp_list = await client.get(f"/documents?department_id={hr.id}")
            assert resp_list.status_code == 403  # can't even list HR's documents
    finally:
        app.dependency_overrides.pop(get_sharepoint_client, None)


@pytest.mark.asyncio
async def test_hr_user_can_view_own_department_document(db: AsyncSession, seeded_roles, departments):
    hr = departments["hr"]

    hr_folder = Folder(name="HR Docs", department_id=hr.id, sharepoint_item_id="sp-hr-folder-2")
    db.add(hr_folder)
    await db.flush()

    hr_user = User(entra_object_id="oid-hr-user-2", email="hruser2@puma.test", display_name="HR User Two")
    db.add(hr_user)
    await db.flush()
    db.add(UserRole(user_id=hr_user.id, role_id=seeded_roles[RoleName.DEPARTMENT_USER].id, department_id=hr.id))

    hr_document = Document(
        name="policy.pdf",
        department_id=hr.id,
        folder_id=hr_folder.id,
        uploaded_by=hr_user.id,
        sharepoint_item_id="sp-hr-doc-2",
        file_size=999,
        file_type="pdf",
    )
    db.add(hr_document)
    await db.commit()
    await db.refresh(hr_document)

    app.dependency_overrides[get_sharepoint_client] = _fake_sharepoint_client
    try:
        client = await _http_client_as(hr_user.id)
        async with client:
            resp = await client.get(f"/documents/{hr_document.id}")
            assert resp.status_code == 200
            assert resp.json()["id"] == str(hr_document.id)
    finally:
        app.dependency_overrides.pop(get_sharepoint_client, None)
