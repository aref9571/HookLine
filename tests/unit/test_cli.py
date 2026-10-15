import getpass

import pytest

from hookline.cli import main


def test_create_admin_rejects_a_short_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOOKLINE_ADMIN_PASSWORD", "too-short")

    exit_code = main(["create-admin", "--email", "admin@example.com"])

    assert exit_code == 1
    error_output = capsys.readouterr().err
    assert error_output.startswith("password: ")
    assert "too-short" not in error_output


def test_create_admin_rejects_an_invalid_email(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOOKLINE_ADMIN_PASSWORD", "a-long-admin-password")

    exit_code = main(["create-admin", "--email", "not-an-email"])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("email: ")


def test_create_admin_asks_for_the_password_when_the_variable_is_not_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HOOKLINE_ADMIN_PASSWORD", raising=False)
    answers = iter(["a-long-admin-password", "a-different-password"])
    prompts: list[str] = []

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(getpass, "getpass", fake_getpass)

    exit_code = main(["create-admin", "--email", "admin@example.com"])

    assert exit_code == 1
    assert prompts == ["Password: ", "Repeat password: "]
    assert capsys.readouterr().err == "The passwords do not match.\n"


def test_create_admin_requires_an_email(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["create-admin"])

    assert exit_info.value.code == 2
    assert "--email" in capsys.readouterr().err


def test_create_admin_does_not_accept_a_password_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["create-admin", "--email", "admin@example.com", "--password", "secret"])

    assert "unrecognized arguments" in capsys.readouterr().err


def test_create_admin_validates_a_password_typed_at_the_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HOOKLINE_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "short")

    exit_code = main(["create-admin", "--email", "admin@example.com"])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("password: ")
