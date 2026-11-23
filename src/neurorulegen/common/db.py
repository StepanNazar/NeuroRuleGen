from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from neurorulegen.common.config import get_settings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s`",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def create_database(echo: bool | str = False):
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=echo)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# Lazy-loaded async sessionmaker
_engine = None
_sessionmaker = None


def get_sessionmaker():
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine, _sessionmaker = create_database()
    return _sessionmaker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    maker = get_sessionmaker()
    async with maker() as session:
        yield session
