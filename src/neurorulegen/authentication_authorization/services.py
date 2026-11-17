import re
from abc import abstractmethod, ABC
from datetime import datetime, timezone, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
import httpx
import pyotp
import segno
from brevo import AsyncBrevo, SendTransacEmailRequestSender, SendTransacEmailRequestToItem

from neurorulegen.authentication_authorization.models import User
from neurorulegen.authentication_authorization.repository import AuthRepository
from neurorulegen.common.config import get_settings

MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Base exception for authentication & authorization domain errors."""


class UserAlreadyExistsError(AuthError):
    """Raised when an account with the given email already exists."""


class PasswordPolicyError(AuthError):
    """Raised when a password does not satisfy security requirements."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

class NoPasswordError(AuthError):
    """Raised when a user does not have a password set."""


_ph = PasswordHasher()
settings = get_settings()
FAKE_HASHED_PASSWORD = _ph.hash(f"fake_password{settings.password_pepper}") # used for timing attack mitigation


def get_password_hasher() -> PasswordHasher:
    return _ph


def hash_password(password: str) -> str:
    peppered = f"{password}{settings.password_pepper}"
    return _ph.hash(peppered)  # salt is automatically generated and included in the hash


def verify_password(password: str, hashed: str) -> bool:
    peppered = f"{password}{settings.password_pepper}"
    try:
        return _ph.verify(hashed, peppered)
    except (VerifyMismatchError, VerificationError):
        return False


def validate_password_policy(password: str) -> tuple[bool, str]:
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must contain at least one special character."
    return True, ""


class AuthService:
    def __init__(self, repository: AuthRepository) -> None:
        self.repository = repository

    def hash_password(self, password: str) -> str:
        return hash_password(password)

    def verify_password(self, password: str, hashed: str) -> bool:
        return verify_password(password, hashed)

    def validate_password_policy(self, password: str) -> tuple[bool, str]:
        return validate_password_policy(password)

    async def register_user(
        self,
        email: str,
        password: str,
        name: str | None = None,
    ) -> User:
        clean_email = email.strip()
        clean_name = name.strip() if name else None

        valid, error_msg = self.validate_password_policy(password)
        if not valid:
            raise PasswordPolicyError(reason=error_msg)

        existing_user = await self.repository.get_user_by_email(clean_email)
        if existing_user:
            raise UserAlreadyExistsError("Email is already registered.")

        pw_hash = self.hash_password(password)
        user = await self.repository.create_user(
            email=clean_email,
            password_hash=pw_hash,
            display_name=clean_name,
        )
        await self.repository.commit()
        return user

    async def login_user(self, email: str, password: str) -> User | None:
        clean_email = email.strip()
        user = await self.repository.get_user_by_email(clean_email)
        if not user:
            self.verify_password(password, FAKE_HASHED_PASSWORD)  # Mitigate timing attacks
            return None
        if not user.password_hash:
            self.verify_password(password, FAKE_HASHED_PASSWORD)  # Mitigate timing attacks
            raise NoPasswordError("User does not have a password.")
        if not self.verify_password(password, user.password_hash):
            return None
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        return await self.repository.get_user_by_email(email)

    async def update_user_display_name(self, user: User, new_display_name: str) -> User:
        self.repository.update_user_display_name(user, new_display_name)
        await self.repository.commit()
        return user

    async def update_user_password(self, user: User, new_password: str, current_password: str) -> User:
        if not user.password_hash or not self.verify_password(current_password, user.password_hash):
                raise AuthError("Current password is incorrect.")
        valid, error_msg = self.validate_password_policy(new_password)
        if not valid:
            raise PasswordPolicyError(reason=error_msg)
        new_hashed_password = self.hash_password(new_password)
        self.repository.update_user_password(user, new_hashed_password)
        await self.repository.commit()
        return user

    async def generate_activation_link(self, user: User) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "user_id": user.email,
            "scope": "account_activation",  # Ensures token can't be used for login
            "iat": now,  # Issued at
            "exp": now + timedelta(hours=settings.activation_token_expiration_minutes / 60),
        }

        token = jwt.encode(payload, settings.email_jwt_secret, algorithm="HS256")
        activation_link = f"{settings.base_url}/activate?token={token}"
        return activation_link

    async def generate_password_reset_code(self, user: User) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "user_id": user.email,
            "scope": "password_reset",  # Ensures token can't be used for login
            "iat": now,  # Issued at
            "exp": now + timedelta(hours=settings.password_reset_token_expiration_minutes / 60),
        }

        reset_code = jwt.encode(payload, settings.email_jwt_secret, algorithm="HS256")
        return reset_code

    async def activate_user(self, token: str) -> User:
        try:
            payload = jwt.decode(token, settings.email_jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthError("Activation token has expired.")
        except jwt.InvalidTokenError:
            raise AuthError("Invalid activation token.")

        if payload.get("scope") != "account_activation":
            raise AuthError("Invalid activation token scope.")

        user_email = payload.get("user_id")
        if not user_email:
            raise AuthError("Invalid activation token payload.")

        user = await self.repository.get_user_by_email(user_email)
        if not user:
            raise AuthError("User not found.")

        if user.activated_at is not None:
            raise AuthError("User account is already activated.")

        self.repository.activate_user(user)
        await self.repository.commit()
        return user

    async def reset_user_password(self, token: str, new_password: str) -> User:
        try:
            payload = jwt.decode(token, settings.email_jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthError("Password reset token has expired.")
        except jwt.InvalidTokenError:
            raise AuthError("Invalid password reset token.")

        if payload.get("scope") != "password_reset":
            raise AuthError("Invalid password reset token scope.")

        user_email = payload.get("user_id")
        if not user_email:
            raise AuthError("Invalid password reset token payload.")

        user = await self.repository.get_user_by_email(user_email)
        if not user:
            raise AuthError("User not found.")

        valid, error_msg = self.validate_password_policy(new_password)
        if not valid:
            raise PasswordPolicyError(reason=error_msg)

        new_hashed_password = self.hash_password(new_password)
        self.repository.update_user_password(user, new_hashed_password)
        await self.repository.commit()
        return user

class CaptchaService(ABC):
    @abstractmethod
    async def verify_captcha(self, *args, **kwargs) -> bool:
        ...

class HCaptchaService(CaptchaService):
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    async def verify_captcha(self, response_token: str, remote_ip: str | None = None) -> bool:
        url = "https://hcaptcha.com/siteverify"
        data = {
            "secret": self.secret_key,
            "response": response_token,
        }
        if remote_ip:
            data["remoteip"] = remote_ip

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            return result.get("success", False)


class EmailService(ABC):
    @abstractmethod
    async def send_email(self, to_name: str, to_email: str, subject: str, body: str) -> None:
        ...

    async def send_activation_email(self, user: User, activation_link: str) -> None:
        subject = "Activate Your NeuroRuleGen Account"
        body = f"Hello {user.display_name or user.email},\n\nPlease activate your account by clicking the following link:\n{activation_link}\n\nThank you!"
        await self.send_email(to_name=user.display_name or user.email, to_email=user.email, subject=subject, body=body)

    async def send_password_reset_email(self, user: User, reset_code: str) -> None:
        subject = "Reset Your NeuroRuleGen Password"
        body = f"Hello {user.display_name or user.email},\n\nYour password reset code is: {reset_code}\n\nIf you did not request a password reset, please ignore this email."
        await self.send_email(to_name=user.display_name or user.email, to_email=user.email, subject=subject, body=body)

class BrevoEmailService(EmailService):
    def __init__(self):
        settings = get_settings()
        self._client = AsyncBrevo(api_key=get_settings().brevo_api_key)
        self._sender_name = settings.brevo_sender_name
        self._sender_email = settings.brevo_sender_email

    async def send_email(self, to_name: str, to_email: str, subject: str, body: str) -> None:
        await self._client.transactional_emails.send_transac_email(
            subject=subject,
            html_content=f"<html><body><p>{body}</p></body></html>",
            sender=SendTransacEmailRequestSender(
                name=self._sender_name,
                email=self._sender_email,
            ),
            to=[
                SendTransacEmailRequestToItem(
                    email=to_email,
                    name=to_name,
                )
            ],
        )

class MockEmailService(EmailService):
    async def send_email(self, to_name: str, to_email: str, subject: str, body: str) -> None:
        print(f"Mock email sent to {to_name} <{to_email}> with subject '{subject}' and body:\n{body}")


class TOTPService:
    def __init__(self, repository: AuthRepository) -> None:
        self.repository = repository

    def generate_secret(self) -> str:
        return pyotp.random_base32()

    def get_provisioning_uri(self, secret: str, email: str, issuer_name: str = "NeuroRuleGen") -> str:
        """Get the URI which will be used to generate the QR code for TOTP setup."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=issuer_name)

    def generate_qr_svg(self, uri: str) -> str:
        qr = segno.make_qr(uri)
        return qr.svg_data_uri()

    def verify_code(self, secret: str, code: str) -> bool:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code.strip()))

    async def setup_totp(self, user: User, secret: str, code: str) -> bool:
        if not self.verify_code(secret, code):
            return False
        user.totp_secret_encrypted = secret.encode()
        user.totp_enabled = True
        await self.repository.commit()
        return True

    async def disable_totp(self, user: User) -> None:
        user.totp_enabled = False
        user.totp_secret_encrypted = None
        await self.repository.commit()

    async def verify_user_totp(self, user: User, code: str) -> bool:
        if not user.totp_enabled or not user.totp_secret_encrypted:
            return False
        secret = user.totp_secret_encrypted.decode()
        return self.verify_code(secret, code)
