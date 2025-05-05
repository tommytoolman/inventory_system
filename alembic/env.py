# alembic/env.py
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import get_settings
from app.database import Base
from app.models.ebay import EbayListing
from app.models.product import Product
from app.models.platform_common import PlatformCommon
from app.models.reverb import ReverbListing
from app.models.vr import VRListing
from app.models.website import WebsiteListing

settings = get_settings()

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata
target_metadata = Base.metadata

def include_object_filter(object, name, type_, reflected, compare_to):
    """
    Filter function for Alembic autogenerate to exclude specific tables.
    """
    if type_ == "table" and name == "product_merges":
        # Ignore the 'product_merges' table
        return False
    elif type_ == "table" and name == "product_mappings":
        return False
    elif type_ == "table" and name == "csv_import_logs":
        return False
    else:
        # Include all other objects (tables, columns, indexes, etc.)
        return True

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # url = config.get_main_option("sqlalchemy.url") # deprecated for ser
    url = settings.DATABASE_URL # Get URL from settings
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object_filter
    )

    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Run migrations in async mode.

    This function is adapted to load the database URL from application
    settings (`app.core.config`) instead of the alembic.ini file,
    ensuring consistency between the application and migrations.
    """
    # Get application settings to access the database URL
    settings = get_settings()

    # Get the Alembic configuration section (usually [alembic])
    # This dictionary contains settings from alembic.ini like sqlalchemy.url
    alembic_config_section = config.get_section(config.config_ini_section, {})

    # **** IMPORTANT: Override the sqlalchemy.url from alembic.ini ****
    # Use the DATABASE_URL from your application settings instead
    alembic_config_section["sqlalchemy.url"] = settings.DATABASE_URL

    # Create the async engine using the MODIFIED configuration dictionary
    # which now contains the correct database URL from settings.
    connectable = async_engine_from_config(
        alembic_config_section, # Use the dictionary we prepared
        prefix="sqlalchemy.",     # Standard prefix for SQLAlchemy keys
        poolclass=pool.NullPool,  # Use NullPool for migrations
    )

    # Connect to the database and run migrations
    async with connectable.connect() as connection:
        # Configure the Alembic context with the database connection
        # and target metadata (your Base.metadata)
        await connection.run_sync(do_run_migrations)

    # Dispose of the engine connection
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

# from logging.config import fileConfig

# from sqlalchemy import engine_from_config
# from sqlalchemy import pool

# from alembic import context

# # this is the Alembic Config object, which provides
# # access to the values within the .ini file in use.
# config = context.config

# # Interpret the config file for Python logging.
# # This line sets up loggers basically.
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

# # add your model's MetaData object here
# # for 'autogenerate' support
# # from myapp import mymodel
# # target_metadata = mymodel.Base.metadata
# target_metadata = None

# # other values from the config, defined by the needs of env.py,
# # can be acquired:
# # my_important_option = config.get_main_option("my_important_option")
# # ... etc.


# def run_migrations_offline() -> None:
#     """Run migrations in 'offline' mode.

#     This configures the context with just a URL
#     and not an Engine, though an Engine is acceptable
#     here as well.  By skipping the Engine creation
#     we don't even need a DBAPI to be available.

#     Calls to context.execute() here emit the given string to the
#     script output.

#     """
#     url = config.get_main_option("sqlalchemy.url")
#     context.configure(
#         url=url,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#     )

#     with context.begin_transaction():
#         context.run_migrations()


# def run_migrations_online() -> None:
#     """Run migrations in 'online' mode.

#     In this scenario we need to create an Engine
#     and associate a connection with the context.

#     """
#     connectable = engine_from_config(
#         config.get_section(config.config_ini_section, {}),
#         prefix="sqlalchemy.",
#         poolclass=pool.NullPool,
#     )

#     with connectable.connect() as connection:
#         context.configure(
#             connection=connection, target_metadata=target_metadata
#         )

#         with context.begin_transaction():
#             context.run_migrations()


# if context.is_offline_mode():
#     run_migrations_offline()
# else:
#     run_migrations_online()
