from logging.config import fileConfig
from os import environ

from alembic import context
from sqlalchemy import engine_from_config, pool

from dokura.metadata.models import Base

config = context.config
if migration_url := environ.get("DOKURA_MIGRATION_URL"):
    config.set_main_option("sqlalchemy.url", migration_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def include_object(object_, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    # FTS5 virtual tables and their shadow tables are created explicitly by the
    # stage 3 migration and intentionally have no SQLAlchemy ORM representation.
    return not (reflected and type_ == "table" and name is not None and name.startswith("files_fts"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
        literal_binds=True, include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=True, include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
