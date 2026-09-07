"""
User account lifecycle + rights management tests.

Covers the Phase 7 additions: Super Admin create/edit/delete of user
accounts, revoking a role assignment (assign_role previously only ever
added), the last-super-admin safety guards, and the pre-provisioned-user
lookup-by-email path used by the real OAuth callback on first login.
"""
import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import app
from app.roles.models import RoleName
from app.roles.user_role import UserRole
from app.users.models import User


def _cookie_for(user_id) -> str:
    import base64
    import json

    import itsdangerous

    signer = itsdangerous.TimestampSigner(get_settings().APP_SECRET_KEY)
    data = json.dumps({"user_id": str(user_id)}).encode()
    return signer.sign(base64.b64encode(data)).decode()


async def _http_client_as(user_id) -> httpx.AsyncClient:
    """A fresh client per identity — see test_documents_rbac.py's note on
    why cookie jars must never be shared across identities."""
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", _cookie_for(user_id))
    return client


async def _make_user_with_role(db: AsyncSession, roles, department, role_name, email):
    user = User(entra_object_id=str(uuid.uuid4()), email=email, display_name=email)
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=roles[role_name].id, department_id=department.id if department else None))
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_super_admin_can_create_user(db: AsyncSession, seeded_roles, departments):
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin1@puma.test")

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.post("/users", json={"email": "newhire@puma.test", "display_name": "New Hire"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "newhire@puma.test"
        assert body["roles"] == []  # pre-provisioned, no roles yet

    created = (await db.execute(select(User).where(User.email == "newhire@puma.test"))).scalar_one()
    assert created.entra_object_id is None  # real oid only ever set by the real OAuth callback


@pytest.mark.asyncio
async def test_creating_duplicate_email_is_conflict(db: AsyncSession, seeded_roles, departments):
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin2@puma.test")
    existing = User(entra_object_id="oid-existing", email="taken@puma.test", display_name="Taken")
    db.add(existing)
    await db.commit()

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.post("/users", json={"email": "taken@puma.test", "display_name": "Someone Else"})
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_recreating_a_deleted_user_resurrects_the_account(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin_resurrect@puma.test")
    target = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "comeback@puma.test")
    original_oid = target.entra_object_id

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.delete(f"/users/{target.id}")
        assert resp.status_code == 204

        # Same email as the just-deleted account — must resurrect, not 409.
        resp = await client.post("/users", json={"email": "comeback@puma.test", "display_name": "Comeback Kid"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == str(target.id)  # same row, not a new one
        assert body["display_name"] == "Comeback Kid"
        assert body["roles"] == []  # old role assignment must NOT come back automatically

    await db.refresh(target)
    assert target.deleted_at is None
    assert target.is_active is True
    assert target.entra_object_id == original_oid  # identity binding preserved

    remaining_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()
    assert remaining_roles == []


@pytest.mark.asyncio
async def test_department_admin_cannot_create_user(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    dept_admin = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "deptadmin1@puma.test")

    client = await _http_client_as(dept_admin.id)
    async with client:
        resp = await client.post("/users", json={"email": "x@puma.test", "display_name": "X"})
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_update_and_deactivate_user(db: AsyncSession, seeded_roles, departments):
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin3@puma.test")
    target = User(entra_object_id="oid-target", email="target@puma.test", display_name="Old Name")
    db.add(target)
    await db.commit()
    await db.refresh(target)

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.patch(f"/users/{target.id}", json={"display_name": "New Name", "is_active": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_name"] == "New Name"
        assert body["is_active"] is False


@pytest.mark.asyncio
async def test_super_admin_cannot_deactivate_own_account(db: AsyncSession, seeded_roles, departments):
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin4@puma.test")

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.patch(f"/users/{admin.id}", json={"is_active": False})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_super_admin_can_delete_user_and_it_disappears_from_listing(db: AsyncSession, seeded_roles, departments):
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin5@puma.test")
    target = User(entra_object_id="oid-target2", email="target2@puma.test", display_name="Target Two")
    db.add(target)
    await db.commit()
    await db.refresh(target)

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.delete(f"/users/{target.id}")
        assert resp.status_code == 204

        listing = await client.get("/users")
        assert all(u["email"] != "target2@puma.test" for u in listing.json())


@pytest.mark.asyncio
async def test_deleting_a_fellow_super_admin_succeeds_when_others_remain(db: AsyncSession, seeded_roles, departments):
    """delete_user's own last-super-admin check can never actually fire in
    practice: only a Super Admin can call this endpoint (require_permission),
    and the separate self-delete guard already blocks the one case where a
    caller could remove the sole remaining admin (themselves). So the only
    reachable outcome here is "delete succeeds, caller remains" — the check
    is kept purely as defense in depth (see its comment in routes.py). The
    scenario where a lone admin could actually strand the system — revoking
    their own super_admin *role assignment* rather than deleting the account
    outright — is covered by test_cannot_remove_last_super_admin_role_assignment
    below, where the guard is genuinely reachable."""
    target = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "target@puma.test")
    caller = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "caller@puma.test")

    client = await _http_client_as(caller.id)
    async with client:
        resp = await client.delete(f"/users/{target.id}")
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cannot_delete_own_account_even_as_the_only_super_admin(db: AsyncSession, seeded_roles, departments):
    only_admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "lastadmin@puma.test")

    client = await _http_client_as(only_admin.id)
    async with client:
        resp = await client.delete(f"/users/{only_admin.id}")
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cannot_remove_last_super_admin_role_assignment(db: AsyncSession, seeded_roles, departments):
    only_admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "solo@puma.test")
    assignment = (await db.execute(select(UserRole).where(UserRole.user_id == only_admin.id))).scalar_one()

    client = await _http_client_as(only_admin.id)
    async with client:
        resp = await client.delete(f"/users/role-assignments/{assignment.id}")
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_department_admin_can_revoke_role_within_own_department(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    dept_admin = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "deptadmin2@puma.test")
    member = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "member1@puma.test")
    assignment = (await db.execute(
        select(UserRole).where(UserRole.user_id == member.id, UserRole.department_id == finance.id)
    )).scalar_one()

    client = await _http_client_as(dept_admin.id)
    async with client:
        resp = await client.delete(f"/users/role-assignments/{assignment.id}")
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_department_admin_cannot_revoke_role_in_other_department(db: AsyncSession, seeded_roles, departments):
    finance, hr = departments["finance"], departments["hr"]
    finance_admin = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "finadmin2@puma.test")
    hr_member = await _make_user_with_role(db, seeded_roles, hr, RoleName.DEPARTMENT_USER, "hrmember@puma.test")
    assignment = (await db.execute(
        select(UserRole).where(UserRole.user_id == hr_member.id, UserRole.department_id == hr.id)
    )).scalar_one()

    client = await _http_client_as(finance_admin.id)
    async with client:
        resp = await client.delete(f"/users/role-assignments/{assignment.id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_department_admin_cannot_revoke_super_admin(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    dept_admin = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "deptadmin3@puma.test")
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "adminvictim@puma.test")
    assignment = (await db.execute(select(UserRole).where(UserRole.user_id == admin.id))).scalar_one()

    client = await _http_client_as(dept_admin.id)
    async with client:
        resp = await client.delete(f"/users/role-assignments/{assignment.id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_role_assignment_is_conflict(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    admin = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin7@puma.test")
    member = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "member2@puma.test")

    client = await _http_client_as(admin.id)
    async with client:
        resp = await client.post(
            "/users/role-assignments",
            json={"user_id": str(member.id), "role": "department_user", "department_id": str(finance.id)},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_department_admin_listing_hides_roles_in_other_departments(db: AsyncSession, seeded_roles, departments):
    """Section 8's isolation principle applied to user metadata: a Finance
    Department Admin listing Finance users shouldn't see that one of them
    also holds a role in HR."""
    finance, hr = departments["finance"], departments["hr"]
    dept_admin = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "deptadmin4@puma.test")
    dual_role_user = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "dual@puma.test")
    db.add(UserRole(user_id=dual_role_user.id, role_id=seeded_roles[RoleName.READ_ONLY].id, department_id=hr.id))
    await db.commit()

    client = await _http_client_as(dept_admin.id)
    async with client:
        resp = await client.get(f"/users?department_id={finance.id}")
        assert resp.status_code == 200
        [dual_entry] = [u for u in resp.json() if u["email"] == "dual@puma.test"]
        assert all(r["department_id"] == str(finance.id) for r in dual_entry["roles"])


@pytest.mark.asyncio
async def test_pre_provisioned_user_is_found_by_email_before_first_login(db: AsyncSession):
    """Mirrors exactly the two-step lookup app/auth/routes.py's callback
    performs: first by entra_object_id (a first-time login has no match
    yet), then falling back to email for a pre-provisioned row (entra_
    object_id IS NULL). Doesn't drive the real OAuth flow (no live Entra
    tenant in CI), but pins down the query logic the callback depends on
    to link a pre-provisioned account instead of creating a duplicate."""
    pre_provisioned = User(entra_object_id=None, email="invited@puma.test", display_name="Invited Person")
    db.add(pre_provisioned)
    await db.commit()

    real_oid = "oid-from-real-entra-login"
    miss = (await db.execute(select(User).where(User.entra_object_id == real_oid))).scalar_one_or_none()
    assert miss is None

    hit = (await db.execute(
        select(User).where(User.email == "invited@puma.test", User.entra_object_id.is_(None))
    )).scalar_one_or_none()
    assert hit is not None
    assert hit.id == pre_provisioned.id

    hit.entra_object_id = real_oid
    await db.commit()

    now_found_by_oid = (await db.execute(select(User).where(User.entra_object_id == real_oid))).scalar_one_or_none()
    assert now_found_by_oid is not None
    assert now_found_by_oid.id == pre_provisioned.id
