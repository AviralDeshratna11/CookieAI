from alembic import context
from sqlalchemy import create_engine, pool

from database.registry import register_tables
from database.tables import metadata
from memory.config import Settings

register_tables()

settings = Settings()
url = settings.migration_database_url or settings.database_url
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Qualify the version table so another schema on search_path cannot make
        # a fresh schema appear migrated already.
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=metadata,
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()
