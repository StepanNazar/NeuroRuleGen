"""Small async SQLAlchemy example for a lab report; cleans up its own rows."""

import asyncio
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from neurorulegen.authentication_authorization.models import User
from neurorulegen.common.db import create_database
from neurorulegen.project_management.models import Project, ProjectDeveloper
from neurorulegen.rule_management.models import DeterministicRule, RuleState


async def main() -> None:
    engine, sessions = create_database(echo=True)
    try:
        async with sessions.begin() as session:
            print("Creating users...")
            marker = uuid4().hex
            owner = User(
                email=f"owner-{marker}@example.test",
                github_user_id=uuid4().int % (2**63 - 1),
            )
            developer = User(
                email=f"developer-{marker}@example.test",
                github_user_id=uuid4().int % (2**63 - 1),
            )
            session.add_all([owner, developer])
            await session.flush()

            print("Creating project...")
            project = Project(
                name="Lab example",
                github_repository_id=uuid4().int % (2**63 - 1),
                created_by_user_id=owner.id,
            )
            session.add(project)
            await session.flush()

            print("Adding developer and rules to project...")
            session.add(ProjectDeveloper(project_id=project.id, user_id=developer.id))
            session.add_all(
                [
                    DeterministicRule(
                        project_id=project.id,
                        name="No eval",
                        code="print('demo: eval check')",
                    ),
                    DeterministicRule(
                        project_id=project.id,
                        name="No exec",
                        code="print('demo: exec check')",
                    ),
                ]
            )
            await session.flush()

            print("Reading emails of project's developers...")
            rows = await session.execute(
                select(Project.name, User.email)
                .join(ProjectDeveloper, ProjectDeveloper.project_id == Project.id)
                .join(User, User.id == ProjectDeveloper.user_id)
                .where(Project.id == project.id)
            )
            print("Project and developers:", rows.all())
            print("Reading count of rules in project...")
            count = await session.scalar(
                select(func.count())
                .select_from(DeterministicRule)
                .where(DeterministicRule.project_id == project.id)
            )
            print("Rule count:", count)

            print("Updating rule status...")
            await session.execute(
                update(DeterministicRule)
                .where(DeterministicRule.project_id == project.id)
                .values(state=RuleState.ENABLED)
            )

            print("Reading rule names and statuses...")
            rules = await session.execute(
                select(DeterministicRule.name, DeterministicRule.state).where(
                    DeterministicRule.project_id == project.id
                )
            )
            print("Updated rules:", rules.all())

            print("Deleting all demo data...")
            await session.execute(
                delete(DeterministicRule).where(
                    DeterministicRule.project_id == project.id
                )
            )
            await session.execute(
                delete(ProjectDeveloper).where(
                    ProjectDeveloper.project_id == project.id
                )
            )
            await session.execute(delete(Project).where(Project.id == project.id))
            await session.execute(
                delete(User).where(User.id.in_([owner.id, developer.id]))
            )
            print("All demo rows deleted.")
        # An exception rolls back the entire transaction, including inserted rows.
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
