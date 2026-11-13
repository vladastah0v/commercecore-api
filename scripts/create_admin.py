import argparse
import asyncio
import getpass
import sys
import warnings

import asyncpg
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import create_database_engine
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.admin_service import AdminBootstrapService


def prompt_admin() -> RegisterRequest:
    if not sys.stdin.isatty():
        raise RuntimeError("An interactive terminal is required for password entry.")
    email = input("Email: ")
    full_name = input("Full name: ")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return RegisterRequest(email=email, full_name=full_name, password=password)


async def create_admin(data: RegisterRequest) -> None:
    engine = create_database_engine(get_settings())
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await AdminBootstrapService(session).create_admin(data)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an administrator interactively.")
    parser.parse_args()
    try:
        data = prompt_admin()
        asyncio.run(create_admin(data))
    except ValidationError as error:
        for item in error.errors():
            print(f"{'.'.join(map(str, item['loc']))}: {item['msg']}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, EmailAlreadyRegisteredError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (SQLAlchemyError, asyncpg.PostgresError, OSError):
        print("Database operation failed. Check the connection and migrations.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("Administrator creation cancelled.", file=sys.stderr)
        return 1
    print("Administrator created successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
