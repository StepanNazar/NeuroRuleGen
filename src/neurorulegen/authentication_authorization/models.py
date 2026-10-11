import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    LargeBinary,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurorulegen.common.db import Base


class SystemRole(str, enum.Enum):
    USER = "user"
    ADMINISTRATOR = "administrator"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(
        Text().with_variant(CITEXT(), "postgresql"), unique=True
    )
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    system_role: Mapped[SystemRole] = mapped_column(
        Enum(
            SystemRole,
            native_enum=False,
            create_constraint=True,
        ),
        server_default=SystemRole.USER.name,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    login_blocked: Mapped[bool] = mapped_column(Boolean, server_default=false())
    github_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    github_access_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())

    __table_args__ = (
        CheckConstraint(
            (password_hash.is_not(None)) | (github_user_id.is_not(None)),
            name="users_login_method",
        ),
        CheckConstraint(
            (~totp_enabled) | (totp_secret_encrypted.is_not(None)),
            name="users_totp_secret",
        ),
    )

    failed_login_attempts: Mapped[list["FailedLoginAttempt"]] = relationship(
        back_populates="user"
    )


class FailedLoginAttempt(Base):
    __tablename__ = "failed_login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id))
    entered_email: Mapped[str] = mapped_column(Text)
    ip_address: Mapped[str] = mapped_column(Text().with_variant(INET(), "postgresql"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship(back_populates="failed_login_attempts")
