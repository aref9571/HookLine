import argparse
import getpass
import os
import sys

from pydantic import ValidationError

from hookline.config import Settings
from hookline.database import create_engine_from_settings, create_session_factory
from hookline.errors import ConflictError
from hookline.users.models import UserRole
from hookline.users.schemas import AdminCreate
from hookline.users.service import create_user

ADMIN_PASSWORD_VARIABLE = "HOOKLINE_ADMIN_PASSWORD"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hookline.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin_parser = commands.add_parser("create-admin", help="Create an admin user.")
    create_admin_parser.add_argument("--email", required=True)
    return parser


def read_admin_password() -> str | None:
    password = os.environ.get(ADMIN_PASSWORD_VARIABLE)
    if password:
        return password
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        return None
    return password


def print_validation_errors(error: ValidationError) -> None:
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        print(f"{field}: {item['msg']}", file=sys.stderr)


def create_admin(email: str) -> int:
    password = read_admin_password()
    if password is None:
        print("The passwords do not match.", file=sys.stderr)
        return 1
    try:
        admin = AdminCreate(email=email, password=password)
    except ValidationError as error:
        print_validation_errors(error)
        return 1

    engine = create_engine_from_settings(Settings())
    try:
        with create_session_factory(engine)() as session:
            create_user(session, admin.email, admin.password, UserRole.ADMIN)
    except ConflictError as error:
        print(error.detail, file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(f"Created admin user {admin.email}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return create_admin(args.email)


if __name__ == "__main__":
    sys.exit(main())
