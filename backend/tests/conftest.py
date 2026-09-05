"""
Shared pytest fixtures.

Runs against a DEDICATED test database (puma_dms_test, see .env.test) — never
the dev database. Tests here do full CREATE/DROP TABLE cycles per test, so
sharing a database with the running app would (and once did, during
development of this suite) wipe real seeded data out from under it.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Must happen BEFORE any `app.*` import, since app.core.config.get_settings()
# is cached on first call and app.core.database creates the engine at import
# time. override=True ensures .env.test wins even if .env was already loaded
# into the environment by something else in this process.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=True)

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, Base, engine
from app.departments.models import Department
from app.roles.models import Permission, Role, RoleName
from app.roles.user_role import UserRole
from app.users.models import User


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncSession:
    # Hard guard: never let this fixture run its CREATE/DROP TABLE cycle
    # against anything that isn't obviously a test database, regardless of
    # what .env.test currently says. This is the safety net for the exact
    # mistake made once already while building this suite.
    db_name = engine.url.database or ""
    assert "test" in db_name, (
        f"Refusing to run destructive schema operations against database '{db_name}' — "
        "it doesn't look like a test database. Check .env.test / DATABASE_URL."
    )

    # Pooled asyncpg connections are bound to the event loop they were
    # created on. Since each test function gets its own loop, we dispose the
    # pool first so connections are (re)created fresh under the current loop.
    await engine.dispose()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded_roles(db: AsyncSession):
    """Creates the 4 roles with a minimal permission set, without importing the seed script's full catalog."""
    view_perm = Permission(code="document:view", description="View a document")
    upload_perm = Permission(code="document:upload", description="Upload a document")
    manage_perm = Permission(code="user:manage", description="Manage users")
    search_perm = Permission(code="search:query", description="Search documents")
    db.add_all([view_perm, upload_perm, manage_perm, search_perm])
    await db.flush()

    roles = {
        RoleName.SUPER_ADMIN: Role(name=RoleName.SUPER_ADMIN, permissions=[view_perm, upload_perm, manage_perm, search_perm]),
        RoleName.DEPARTMENT_ADMIN: Role(name=RoleName.DEPARTMENT_ADMIN, permissions=[view_perm, upload_perm, manage_perm, search_perm]),
        RoleName.DEPARTMENT_USER: Role(name=RoleName.DEPARTMENT_USER, permissions=[view_perm, upload_perm, search_perm]),
        RoleName.READ_ONLY: Role(name=RoleName.READ_ONLY, permissions=[view_perm, search_perm]),
    }
    db.add_all(roles.values())
    await db.commit()
    return roles


@pytest_asyncio.fixture
async def departments(db: AsyncSession):
    finance = Department(name="Finance", code="FIN")
    hr = Department(name="HR", code="HR")
    db.add_all([finance, hr])
    await db.commit()
    return {"finance": finance, "hr": hr}
