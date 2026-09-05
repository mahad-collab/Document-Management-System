import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make `app` importable when alembic is invoked from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402

# Import every model module so Base.metadata is fully populated before
# autogenerate compares it against the live schema. Add new model modules
# here as new phases introduce them (folders, documents, ocr, audit, ...).
from app.departments.models import Department  # noqa: E402,F401
from app.audit.models import AuditLog  # noqa: E402,F401
from app.documents.models import Document, DocumentVersion, Tag  # noqa: E402,F401
from app.folders.models import Folder  # noqa: E402,F401
from app.roles.models import Role, Permission  # noqa: E402,F401
from app.roles.user_role import UserRole  # noqa: E402,F401
from app.users.models import User  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Never hard-code the DB URL in alembic.ini — pull it from our own Settings
# so migrations always target whatever DATABASE_URL_SYNC is configured for
# the current environment (dev/staging/prod), matching spec Section 25
# ("environment variables for secrets", "no credentials in source code").
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
