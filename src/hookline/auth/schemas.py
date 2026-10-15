from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from hookline.auth.passwords import BCRYPT_MAX_BYTES

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def check_password_byte_length(password: str) -> str:
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"must be at most {BCRYPT_MAX_BYTES} bytes when encoded as UTF-8")
    return password


Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=EMAIL_PATTERN),
]
Password = Annotated[
    str, Field(min_length=12, max_length=128), AfterValidator(check_password_byte_length)
]


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
