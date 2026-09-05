"""
OCR + Search integration test — deliberately NOT mocked.

Unlike the SharePoint client tests, this exercises the real `tesseract`
binary and real PostgreSQL full-text search. Both run entirely inside this
sandbox with no external network dependency, so there's no reason to fake
them — a mock here would prove nothing that matters (whether text
extraction and search actually work is exactly the question).
"""
import asyncio
import uuid

import httpx
import pymupdf
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.documents.models import Document, OCRStatus
from app.folders.models import Folder
from app.main import app
from app.sharepoint.client import SharePointGraphClient
from app.sharepoint.dependencies import get_sharepoint_client


class _FakeMsal:
    def acquire_token_for_client(self, scopes):
        return {"access_token": "fake"}


def _fake_sharepoint_with_storage():
    """The only thing faked here is the Graph HTTP layer (still no real
    network to Microsoft) — but it genuinely stores and returns the actual
    uploaded bytes, so the OCR step downloads and processes real content."""
    storage: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "PUT" and ":/content" in url:
            item_id = f"sp-item-{uuid.uuid4().hex[:8]}"
            storage[item_id] = request.content
            return httpx.Response(201, json={"id": item_id, "cTag": '"c:1.0"'})
        if request.method == "GET" and url.endswith("/content"):
            item_id = url.rsplit("/", 2)[-2]
            return httpx.Response(200, content=storage.get(item_id, b""))
        return httpx.Response(404, json={"error": "unhandled"})

    fake_http = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0", transport=httpx.MockTransport(handler))
    return SharePointGraphClient(settings=get_settings(), http_client=fake_http, msal_app=_FakeMsal())


@pytest.mark.asyncio
async def test_upload_triggers_real_ocr_and_search_finds_it(db: AsyncSession, seeded_roles, departments):
    from app.roles.models import RoleName
    from app.roles.user_role import UserRole
    from app.users.models import User

    finance = departments["finance"]
    folder = Folder(name="Invoices", department_id=finance.id, sharepoint_item_id="sp-folder-real-ocr")
    db.add(folder)
    await db.flush()

    user = User(entra_object_id="oid-real-ocr", email="ocrtest@puma.test", display_name="OCR Tester")
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=seeded_roles[RoleName.DEPARTMENT_USER].id, department_id=finance.id))
    await db.commit()

    # A real PDF with a real embedded text layer — exercises PyMuPDF's
    # direct-text-extraction path (no image rasterization needed).
    pdf_doc = pymupdf.open()
    page = pdf_doc.new_page()
    page.insert_text((72, 72), "Contract Number: CNT-9981\nParty: Acme Trading Co")
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    fake_sp_client = _fake_sharepoint_with_storage()
    app.dependency_overrides[get_sharepoint_client] = lambda: fake_sp_client
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            import base64
            import json

            import itsdangerous

            secret = get_settings().APP_SECRET_KEY
            signer = itsdangerous.TimestampSigner(secret)
            client.cookies.set(
                "session", signer.sign(base64.b64encode(json.dumps({"user_id": str(user.id)}).encode())).decode()
            )

            resp = await client.post(
                "/documents",
                data={"folder_id": str(folder.id)},
                files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            )
            assert resp.status_code == 201
            document_id = resp.json()["id"]
            assert resp.json()["ocr_status"] == "pending"

            # Background task runs after the response is sent — poll briefly
            # rather than a fixed sleep, since this is real (fast) extraction.
            for _ in range(20):
                await asyncio.sleep(0.1)
                check = await client.get(f"/documents/{document_id}")
                if check.json()["ocr_status"] != "pending":
                    break
            assert check.json()["ocr_status"] == "completed"

            # Search by a term that ONLY exists in the OCR-extracted text,
            # not in the filename or any metadata field — proves search is
            # genuinely reading ocr_text, not just matching the filename.
            search_resp = await client.get(f"/search?department_id={finance.id}&q=CNT-9981")
            assert search_resp.status_code == 200
            results = search_resp.json()
            assert len(results) == 1
            assert results[0]["id"] == document_id

            search_resp_2 = await client.get(f"/search?department_id={finance.id}&q=Acme")
            assert len(search_resp_2.json()) == 1

            # Sanity: a term that appears nowhere should return no results.
            search_resp_3 = await client.get(f"/search?department_id={finance.id}&q=totallyabsentterm")
            assert search_resp_3.json() == []
    finally:
        app.dependency_overrides.pop(get_sharepoint_client, None)
