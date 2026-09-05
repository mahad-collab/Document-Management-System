"""
Seeds the fixed role catalog and a baseline permission set.

Run with:  python -m app.core.seed

Unlike departments (fully admin-managed, spec Section 3), the four roles
(Section 7) are fixed by the application's design — this script exists so
a fresh database always has them, and is safe to re-run (idempotent).
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
# Import every model module up front — SQLAlchemy resolves string-based
# relationship() targets (e.g. Role.user_roles -> "UserRole") lazily, and
# that only works if all mapped classes have been imported somewhere before
# the mappers are configured. Running this script standalone (rather than
# through app.main, which imports auth routes -> rbac -> all of these
# transitively) skipped that import chain.
from app.departments.models import Department  # noqa: F401
from app.users.models import User  # noqa: F401
from app.roles.user_role import UserRole  # noqa: F401
from app.roles.models import Permission, Role, RoleName

# Baseline permission catalog. New permissions can be added here over time;
# existing ones are never silently removed by this script.
PERMISSIONS = [
    ("document:view", "View a document's metadata and preview"),
    ("document:upload", "Upload a new document"),
    ("document:download", "Download a document's file"),
    ("document:update_metadata", "Edit a document's metadata/tags"),
    ("document:move", "Move a document between folders"),
    ("document:delete", "Soft-delete a document (recycle bin)"),
    ("document:restore", "Restore a document from the recycle bin"),
    ("document:permanent_delete", "Permanently delete a document"),
    ("document:version_upload", "Upload a new version of a document"),
    ("document:version_restore", "Restore a previous document version"),
    ("folder:create", "Create a folder/subfolder"),
    ("folder:rename", "Rename a folder"),
    ("folder:archive", "Archive a folder"),
    ("search:query", "Search documents"),
    ("user:manage", "Manage user role assignments within a department"),
    ("audit:view", "View audit logs for a department"),
    ("department:manage", "Create, rename, disable, or reactivate departments (org-wide, Super Admin only)"),
]

# Which roles get which permissions by default. Super Admin bypasses this
# entirely (see rbac.py: is_super_admin short-circuits every check).
ROLE_PERMISSION_MAP = {
    RoleName.DEPARTMENT_ADMIN: [
        "document:view", "document:upload", "document:download", "document:update_metadata",
        "document:move", "document:delete", "document:restore", "document:version_upload",
        "document:version_restore", "folder:create", "folder:rename", "folder:archive",
        "search:query", "user:manage", "audit:view",
    ],
    RoleName.DEPARTMENT_USER: [
        "document:view", "document:upload", "document:download", "document:update_metadata",
        "document:version_upload", "search:query",
    ],
    RoleName.READ_ONLY: [
        "document:view", "document:download", "search:query",
    ],
}


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Permissions
        code_to_permission = {}
        for code, description in PERMISSIONS:
            existing = (await db.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
            if existing is None:
                existing = Permission(code=code, description=description)
                db.add(existing)
                await db.flush()
            code_to_permission[code] = existing

        # Roles
        for role_name in RoleName:
            desired_codes = ROLE_PERMISSION_MAP.get(role_name, [])
            desired_permissions = [code_to_permission[c] for c in desired_codes]

            stmt = select(Role).where(Role.name == role_name).options(selectinload(Role.permissions))
            existing_role = (await db.execute(stmt)).scalar_one_or_none()

            if existing_role is None:
                # Set permissions at construction time — reassigning the
                # relationship on an object that was only just flushed (and
                # hasn't had `permissions` loaded) forces a synchronous
                # lazy-load, which isn't valid on an AsyncSession.
                existing_role = Role(
                    name=role_name,
                    description=role_name.value.replace("_", " ").title(),
                    permissions=desired_permissions,
                )
                db.add(existing_role)
            else:
                existing_role.permissions = desired_permissions

        await db.commit()
    print("Seed complete: roles + permissions are up to date.")


if __name__ == "__main__":
    asyncio.run(seed())
