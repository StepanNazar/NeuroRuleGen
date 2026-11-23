#!/usr/bin/env python3
"""Script to create or promote an administrator user."""

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from neurorulegen.authentication_authorization.models import SystemRole, User
from neurorulegen.authentication_authorization.services import hash_password, validate_password_policy
from neurorulegen.common.db import create_database


async def create_or_promote_admin(email: str, password: str | None = None, display_name: str | None = None) -> None:
    clean_email = email.strip()

    engine, session_maker = create_database()
    async with session_maker() as session:
        stmt = select(User).where(User.email == clean_email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.system_role = SystemRole.ADMINISTRATOR
            if password:
                valid, msg = validate_password_policy(password)
                if not valid:
                    print(f"Error: Password policy error: {msg}")
                    return
                user.password_hash = hash_password(password)
            if display_name:
                user.display_name = display_name
            if not user.activated_at:
                user.activated_at = datetime.now(timezone.utc)
            user.login_blocked = False
            await session.commit()
            print(f"User {clean_email} successfully promoted to administrator.")
        else:
            if not password:
                print("Error: Password is required when creating a new administrator account.")
                return
            valid, msg = validate_password_policy(password)
            if not valid:
                print(f"Error: Password policy error: {msg}")
                return

            pw_hash = hash_password(password)
            new_user = User(
                email=clean_email,
                password_hash=pw_hash,
                display_name=display_name or "Administrator",
                system_role=SystemRole.ADMINISTRATOR,
                activated_at=datetime.now(timezone.utc),
                login_blocked=False,
            )
            session.add(new_user)
            await session.commit()
            print(f"Administrator {clean_email} successfully created.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote an administrator account.")
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--password", required=False, default=None, help="Administrator password")
    parser.add_argument("--name", required=False, default=None, help="Administrator display name")

    args = parser.parse_args()
    asyncio.run(create_or_promote_admin(email=args.email, password=args.password, display_name=args.name))


if __name__ == "__main__":
    main()
