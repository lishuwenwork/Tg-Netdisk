from alembic import context
from sqlalchemy import create_engine

from tg_netdisk.models.database import Base

config = context.config
engine = create_engine(config.get_main_option("sqlalchemy.url"))
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
