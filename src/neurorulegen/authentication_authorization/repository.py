from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.authentication_authorization.models import User


class AuthRepository(ABC):
    @abstractmethod
    async def get_user_by_email(self, email: str) -> User | None:
        pass

    @abstractmethod
    async def get_user_by_id(self, user_id: int) -> User | None:
        pass

    @abstractmethod
    async def get_user_by_github_id(self, github_user_id: int) -> User | None:
        pass

    @abstractmethod
    async def create_user(
        self,
        email: str,
        password_hash: str | None = None,
        display_name: str | None = None,
        github_user_id: int | None = None,
        github_access_token_encrypted: bytes | None = None,
        github_refresh_token_encrypted: bytes | None = None,
        activated_at: datetime | None = None,
    ) -> User:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass

    @abstractmethod
    def activate_user(self, user: User) -> None:
        pass

    @abstractmethod
    def update_user_display_name(self, user: User, new_display_name: str) -> None:
        pass

    @abstractmethod
    def update_user_password(self, user: User, new_password_hash: str) -> None:
        pass


class SQLAlchemyAuthRepository(AuthRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_github_id(self, github_user_id: int) -> User | None:
        stmt = select(User).where(User.github_user_id == github_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        password_hash: str | None = None,
        display_name: str | None = None,
        github_user_id: int | None = None,
        github_access_token_encrypted: bytes | None = None,
        github_refresh_token_encrypted: bytes | None = None,
        activated_at: datetime | None = None,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            github_user_id=github_user_id,
            github_access_token_encrypted=github_access_token_encrypted,
            github_refresh_token_encrypted=github_refresh_token_encrypted,
            activated_at=activated_at,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    def activate_user(self, user: User) -> None:
        user.activated_at = datetime.now(timezone.utc)

    def update_user_display_name(self, user: User, new_display_name: str) -> None:
        user.display_name = new_display_name

    def update_user_password(self, user: User, new_password_hash: str) -> None:
        user.password_hash = new_password_hash

    async def commit(self) -> None:
        await self._session.commit()
