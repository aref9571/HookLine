import pytest
from pydantic import ValidationError

from hookline.users.schemas import AdminCreate


def test_admin_create_accepts_a_valid_email_and_password() -> None:
    admin = AdminCreate(email="  Admin@Example.COM ", password="a" * 12)

    assert admin.email == "admin@example.com"
    assert admin.password == "a" * 12


@pytest.mark.parametrize("password", ["a" * 11, "a" * 129])
def test_admin_create_rejects_passwords_outside_12_to_128_characters(password: str) -> None:
    with pytest.raises(ValidationError) as error:
        AdminCreate(email="admin@example.com", password=password)

    assert error.value.errors()[0]["loc"] == ("password",)


def test_admin_create_accepts_a_password_of_exactly_72_bytes() -> None:
    password = "é" * 36

    admin = AdminCreate(email="admin@example.com", password=password)

    assert len(admin.password.encode("utf-8")) == 72


def test_admin_create_rejects_a_password_over_72_bytes() -> None:
    password = "é" * 37

    with pytest.raises(ValidationError) as error:
        AdminCreate(email="admin@example.com", password=password)

    assert len(password) == 37
    assert error.value.errors()[0]["loc"] == ("password",)
    assert "72 bytes" in error.value.errors()[0]["msg"]


@pytest.mark.parametrize("email", ["", "admin", "admin@example", "ad min@example.com"])
def test_admin_create_rejects_invalid_emails(email: str) -> None:
    with pytest.raises(ValidationError) as error:
        AdminCreate(email=email, password="a" * 12)

    assert error.value.errors()[0]["loc"] == ("email",)
