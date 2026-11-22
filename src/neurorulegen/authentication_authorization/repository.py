from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from neurorulegen.authentication_authorization.models import User, FailedLoginAttempt


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

    @abstractmethod
    async def log_failed_login_attempt(self, email: str, ip_address: str, user_agent: str | None) -> None:
        pass

    @abstractmethod
    async def counts_failed_login_attempts_from_ip(self, ip_address: str, time_window_minutes: int) -> int:
        pass

    @abstractmethod
    async def counts_failed_login_attempts_from_email(self, email: str, time_window_minutes: int) -> int:
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

    async def log_failed_login_attempt(self, email: str, ip_address: str, user_agent: str | None) -> None:
        user = await self.get_user_by_email(email)
        if user is not None:
            user_id = user.id
        else:
            user_id = None
        failed_attempt = FailedLoginAttempt(
            user_id=user_id,
            entered_email=email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(failed_attempt)

    async def _count_failed_login_attempts(self, filter_condition, time_window_minutes: int) -> int:
        stmt = select(func.count()).select_from(FailedLoginAttempt).where(
            filter_condition,
            FailedLoginAttempt.attempted_at >= func.now() - timedelta(minutes=time_window_minutes)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def counts_failed_login_attempts_from_ip(self, ip_address: str, time_window_minutes: int) -> int:
        return await self._count_failed_login_attempts(FailedLoginAttempt.ip_address == ip_address, time_window_minutes)

    async def counts_failed_login_attempts_from_email(self, email: str, time_window_minutes: int) -> int:
        return await self._count_failed_login_attempts(FailedLoginAttempt.entered_email == email, time_window_minutes)

    async def commit(self) -> None:
        await self._session.commit()
