from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("my-secret")
    assert verify_password("my-secret", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip() -> None:
    token = create_access_token("user-123")
    assert decode_token(token) == "user-123"
    assert decode_token("invalid.token.here") is None
