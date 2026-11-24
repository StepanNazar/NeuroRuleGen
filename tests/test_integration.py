import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

_TEST_SETTINGS = {
    "POSTGRES_PASSWORD": "test",
    "SECRET_KEY": "test-secret",
    "PASSWORD_PEPPER": "test-pepper",
    "HCAPTCHA_SITEKEY": "test-sitekey",
    "HCAPTCHA_SECRET": "test-secret",
    "BREVO_API_KEY": "test-api-key",
    "BREVO_SENDER_NAME": "Test Sender",
    "BREVO_SENDER_EMAIL": "test@example.com",
    "ACTIVATION_TOKEN_EXPIRATION_MINUTES": "60",
    "PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES": "60",
    "EMAIL_JWT_SECRET": "test-email-secret",
    "BASE_URL": "http://testserver",
    "FERNET_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "MAX_LOGIN_ATTEMPTS_PER_IP": "5",
    "MAX_LOGIN_ATTEMPTS_PER_EMAIL": "5",
    "MAX_LOGIN_ATTEMPTS_TIME_WINDOW_MINUTES": "15",
}
for _key, _value in _TEST_SETTINGS.items():
    os.environ.setdefault(_key, _value)

from neurorulegen.common.db import Base
from neurorulegen.authentication_authorization.models import User
from neurorulegen.authentication_authorization.repository import (
    SQLAlchemyAuthRepository,
)
from neurorulegen.project_management.models import (
    DeveloperInvitation,
    Project,
    ProjectDeveloper,
)
from neurorulegen.github_integration.services import GitHubClient
from neurorulegen.project_management.repository import SQLAlchemyProjectRepository
from neurorulegen.project_management.services import ProjectManagementService
from neurorulegen.web_controllers import project_management
from neurorulegen.web_controllers.middlewares import CSRFHeaderProtectionMiddleware

OWNER_ID = 101
DEVELOPER_ID = 102
TARGET_ID = 103
PROJECT_ID = 201


class RecordingEmailService:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_email(
        self,
        to_name: str,
        to_email: str,
        subject: str,
        body: str,
    ) -> None:
        self.sent.append(
            {
                "to_name": to_name,
                "to_email": to_email,
                "subject": subject,
                "body": body,
            }
        )


@pytest.fixture
def client_and_email():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_service = RecordingEmailService()
    now = datetime.now(timezone.utc)
    users = {
        OWNER_ID: User(
            id=OWNER_ID,
            email="owner@example.com",
            password_hash="test-hash",
            activated_at=now,
        ),
        DEVELOPER_ID: User(
            id=DEVELOPER_ID,
            email="developer@example.com",
            password_hash="test-hash",
            activated_at=now,
        ),
        TARGET_ID: User(
            id=TARGET_ID,
            email="target@example.com",
            password_hash="test-hash",
            activated_at=now,
        ),
    }
    authenticated_user = {"user": users[OWNER_ID]}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=[
                        User.__table__,
                        Project.__table__,
                        ProjectDeveloper.__table__,
                        DeveloperInvitation.__table__,
                    ],
                )
            )
        async with session_factory() as session:
            session.add_all(
                [
                    *users.values(),
                    Project(
                        id=PROJECT_ID,
                        name="Integration test project",
                        github_repository_id=987654,
                        github_repo_url="https://github.com/example/repository",
                        created_by_user_id=OWNER_ID,
                    ),
                    ProjectDeveloper(
                        project_id=PROJECT_ID,
                        user_id=DEVELOPER_ID,
                    ),
                ]
            )
            await session.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CSRFHeaderProtectionMiddleware)
    app.include_router(project_management.router)

    async def override_db_session():
        async with session_factory() as session:
            yield session

    async def override_project_service(
        session: AsyncSession = Depends(override_db_session),
    ) -> ProjectManagementService:
        return ProjectManagementService(
            repository=SQLAlchemyProjectRepository(session),
            auth_repository=SQLAlchemyAuthRepository(session),
            github_client=GitHubClient(),
            email_service=email_service,
        )

    def override_authenticated_user() -> User:
        return authenticated_user["user"]

    app.dependency_overrides[project_management.get_project_service] = (
        override_project_service
    )
    app.dependency_overrides[project_management.get_current_activated_user] = (
        override_authenticated_user
    )

    with TestClient(app) as client:
        yield client, email_service, authenticated_user, users


def test_owner_adds_existing_developer_and_membership_is_persisted(
    client_and_email,
):
    """Checks that the project owner can add an activated user to the project."""
    client, _, authenticated_user, _ = client_and_email
    authenticated_user["user"] = User(
        id=OWNER_ID,
        email="owner@example.com",
        password_hash="test-hash",
        activated_at=datetime.now(timezone.utc),
    )
    headers = {"sec-fetch-site": "same-origin"}

    response = client.post(
        f"/projects/{PROJECT_ID}/developers",
        data={"email": "target@example.com"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice_type=success" in response.headers["location"]

    removal = client.delete(
        f"/api/projects/{PROJECT_ID}/developers/{TARGET_ID}",
        headers=headers,
    )
    assert removal.status_code == 200
    assert removal.json() == {"removed": TARGET_ID}


def test_owner_invites_unknown_email_and_invitation_is_persisted(
    client_and_email,
):
    """Checks that an invitation is created and emailed to an unknown user."""
    client, email_service, authenticated_user, _ = client_and_email
    authenticated_user["user"] = User(
        id=OWNER_ID,
        email="owner@example.com",
        password_hash="test-hash",
        activated_at=datetime.now(timezone.utc),
    )
    headers = {"sec-fetch-site": "same-origin"}
    invited_email = "new-developer@example.com"

    response = client.post(
        f"/projects/{PROJECT_ID}/developers",
        data={"email": invited_email},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice_type=success" in response.headers["location"]
    assert len(email_service.sent) == 1
    assert email_service.sent[0]["to_email"] == invited_email

    removal = client.delete(
        f"/api/projects/{PROJECT_ID}/invitations",
        params={"email": invited_email},
        headers=headers,
    )
    assert removal.status_code == 200
    assert removal.json() == {"removed": invited_email}


def test_developer_cannot_add_another_project_member(client_and_email):
    """Checks that a developer without the owner role cannot add project members."""
    client, _, authenticated_user, _ = client_and_email
    authenticated_user["user"] = User(
        id=DEVELOPER_ID,
        email="developer@example.com",
        password_hash="test-hash",
        activated_at=datetime.now(timezone.utc),
    )
    headers = {"sec-fetch-site": "same-origin"}

    response = client.post(
        f"/projects/{PROJECT_ID}/developers",
        data={"email": "target@example.com"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice_type=danger" in response.headers["location"]
