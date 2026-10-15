import runpy
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hookline.auth.passwords import verify_password
from hookline.cli import main
from hookline.users.models import User

pytestmark = pytest.mark.integration

PASSWORD = "a-long-admin-password"


def test_create_admin_creates_an_admin_user(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOOKLINE_ADMIN_PASSWORD", PASSWORD)

    exit_code = main(["create-admin", "--email", "Admin@Example.com"])

    assert exit_code == 0
    assert capsys.readouterr().out == "Created admin user admin@example.com.\n"
    user = db_session.scalars(select(User)).one()
    assert user.email == "admin@example.com"
    assert user.role == "admin"
    assert user.is_active is True
    assert verify_password(PASSWORD, user.password_hash)


def test_create_admin_refuses_a_duplicate_email(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOOKLINE_ADMIN_PASSWORD", PASSWORD)
    assert main(["create-admin", "--email", "admin@example.com"]) == 0

    exit_code = main(["create-admin", "--email", "ADMIN@example.com"])

    assert exit_code == 1
    assert "A user with this email already exists." in capsys.readouterr().err
    assert len(db_session.scalars(select(User)).all()) == 1


def test_create_admin_runs_as_a_module(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOOKLINE_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setattr(sys, "argv", ["hookline.cli", "create-admin", "--email", "a@example.com"])
    monkeypatch.delitem(sys.modules, "hookline.cli")

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("hookline.cli", run_name="__main__", alter_sys=True)

    assert exit_info.value.code == 0
    assert db_session.scalars(select(User.email)).all() == ["a@example.com"]
