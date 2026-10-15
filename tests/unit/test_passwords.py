from hookline.auth.passwords import hash_password, verify_password


def test_hash_then_verify_accepts_the_same_password() -> None:
    hashed = hash_password("correct horse battery")

    assert verify_password("correct horse battery", hashed)


def test_hash_does_not_contain_the_password() -> None:
    hashed = hash_password("correct horse battery")

    assert "correct horse battery" not in hashed
    assert hashed.startswith("$2b$")


def test_verify_rejects_a_wrong_password() -> None:
    hashed = hash_password("correct horse battery")

    assert not verify_password("wrong horse battery", hashed)


def test_hashing_the_same_password_twice_gives_different_hashes() -> None:
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_verify_rejects_a_password_over_72_bytes_with_the_same_first_72_bytes() -> None:
    password = "a" * 72
    hashed = hash_password(password)

    assert verify_password(password, hashed)
    assert not verify_password(password + "b", hashed)
