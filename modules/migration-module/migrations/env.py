import os

from alembic import context
from sqlalchemy import create_engine, pool

target_metadata = None


def run_migrations_online():
    connectable = context.config.attributes.get("connection")

    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        url = os.environ["DATABASE_URL"]
        context.config.set_main_option("sqlalchemy.url", url)
        connectable = create_engine(
            context.config.get_main_option("sqlalchemy.url"),
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()


run_migrations_online()
