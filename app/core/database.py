from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings


class Base(DeclarativeBase):
    metadata = MetaData(
        schema="custodian",
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Identity(Record, Base):
    __tablename__ = "identities"
    display_name: Mapped[str]
    version: Mapped[int] = mapped_column(default=1, server_default="1")


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        echo=False,
        connect_args={"ssl": "require"} if settings.database_ssl else {},
    )


async def check_runtime(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        role = (
            (
                await conn.execute(
                    text("""
            SELECT rolsuper, rolcreatedb, rolcreaterole,
              has_schema_privilege(current_user, 'custodian', 'CREATE') AS schema_write,
              EXISTS(SELECT 1 FROM pg_class WHERE relnamespace = 'custodian'::regnamespace
                AND relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)) AS owns_tables
            FROM pg_roles WHERE rolname = current_user
        """)
                )
            )
            .mappings()
            .one()
        )
        if any(role.values()):
            raise RuntimeError(
                "Application DB role must not own schema/tables or have administrative privileges"
            )
        await conn.execute(text("SELECT id FROM custodian.identities LIMIT 0"))


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session, session.begin():
        yield session
