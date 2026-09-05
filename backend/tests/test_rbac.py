"""
RBAC security tests — spec Section 37's explicit test matrix:

    Finance User      -> Finance document -> ALLOW
    Finance User      -> HR document      -> DENY
    HR User           -> Finance document -> DENY
    Super Admin       -> Finance document -> ALLOW
    Super Admin       -> HR document      -> ALLOW

These test the actual authorization primitive (`user_has_department_permission`)
directly rather than through HTTP, since that primitive is what every
endpoint's dependency ultimately calls — if it's correct, every endpoint that
uses it inherits the guarantee.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import CurrentUser, user_has_department_permission
from app.roles.models import RoleName
from app.roles.user_role import UserRole
from app.users.models import User


async def _make_user_with_role(db: AsyncSession, roles, department, role_name, email):
    user = User(entra_object_id=str(uuid.uuid4()), email=email, display_name=email)
    db.add(user)
    await db.flush()

    ur = UserRole(user_id=user.id, role_id=roles[role_name].id, department_id=department.id if department else None)
    db.add(ur)
    await db.commit()
    return user


def _current_user_from(user: User, department_permissions: dict, is_super_admin: bool = False) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_super_admin=is_super_admin,
        department_permissions=department_permissions,
    )


@pytest.mark.asyncio
async def test_finance_user_can_access_finance(db: AsyncSession, seeded_roles, departments):
    finance = departments["finance"]
    user = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "fin@puma.test")
    cu = _current_user_from(user, {finance.id: {"document:view"}})

    assert user_has_department_permission(cu, finance.id, "document:view") is True


@pytest.mark.asyncio
async def test_finance_user_cannot_access_hr(db: AsyncSession, seeded_roles, departments):
    finance, hr = departments["finance"], departments["hr"]
    user = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "fin2@puma.test")
    # This user only has permissions scoped to Finance — HR was never granted.
    cu = _current_user_from(user, {finance.id: {"document:view"}})

    assert user_has_department_permission(cu, hr.id, "document:view") is False


@pytest.mark.asyncio
async def test_hr_user_cannot_access_finance(db: AsyncSession, seeded_roles, departments):
    finance, hr = departments["finance"], departments["hr"]
    user = await _make_user_with_role(db, seeded_roles, hr, RoleName.DEPARTMENT_USER, "hr@puma.test")
    cu = _current_user_from(user, {hr.id: {"document:view"}})

    assert user_has_department_permission(cu, finance.id, "document:view") is False


@pytest.mark.asyncio
async def test_super_admin_can_access_any_department(db: AsyncSession, seeded_roles, departments):
    finance, hr = departments["finance"], departments["hr"]
    user = await _make_user_with_role(db, seeded_roles, None, RoleName.SUPER_ADMIN, "admin@puma.test")
    # Super Admin has no department-scoped permissions at all — access comes
    # purely from the is_super_admin flag short-circuiting the check.
    cu = _current_user_from(user, {}, is_super_admin=True)

    assert user_has_department_permission(cu, finance.id, "document:view") is True
    assert user_has_department_permission(cu, hr.id, "document:view") is True


@pytest.mark.asyncio
async def test_department_admin_of_finance_cannot_manage_hr_users(db: AsyncSession, seeded_roles, departments):
    """Even a Department ADMIN role is confined to their own department (Section 7)."""
    finance, hr = departments["finance"], departments["hr"]
    user = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_ADMIN, "finadmin@puma.test")
    cu = _current_user_from(user, {finance.id: {"document:view", "user:manage"}})

    assert user_has_department_permission(cu, finance.id, "user:manage") is True
    assert user_has_department_permission(cu, hr.id, "user:manage") is False


@pytest.mark.asyncio
async def test_read_only_user_cannot_upload(db: AsyncSession, seeded_roles, departments):
    """Read-only users (Section 7) should never pass an upload/delete check even in their own department."""
    finance = departments["finance"]
    user = await _make_user_with_role(db, seeded_roles, finance, RoleName.READ_ONLY, "readonly@puma.test")
    cu = _current_user_from(user, {finance.id: {"document:view"}})  # no "document:upload" granted

    assert user_has_department_permission(cu, finance.id, "document:view") is True
    assert user_has_department_permission(cu, finance.id, "document:upload") is False


@pytest.mark.asyncio
async def test_unauthorized_department_lookup_returns_false_not_error(db: AsyncSession, seeded_roles, departments):
    """A user with NO role in a department at all (not even in the dict) must be denied, not raise."""
    finance = departments["finance"]
    user = await _make_user_with_role(db, seeded_roles, finance, RoleName.DEPARTMENT_USER, "noaccess@puma.test")
    cu = _current_user_from(user, {})  # department_permissions is empty entirely

    assert user_has_department_permission(cu, finance.id, "document:view") is False
    assert user_has_department_permission(cu, uuid.uuid4(), "document:view") is False
