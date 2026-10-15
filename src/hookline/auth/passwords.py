import bcrypt

BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    plain_bytes = plain.encode("utf-8")
    if len(plain_bytes) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(plain_bytes, hashed.encode("ascii"))
