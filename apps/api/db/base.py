"""SQLAlchemy declarative base."""
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names. Without this, Postgres invents names, and Alembic cannot
# reliably drop or alter a constraint it did not name itself.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(constraint_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    # No %(constraint_name)s here: single-column foreign keys are declared without a name, and that
    # token needs one. The composite foreign keys in models.py are named in full instead.
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
