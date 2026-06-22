import uuid

from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("secure-password")
    assert verify_password("secure-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_jwt_roundtrip() -> None:
    token = create_access_token(subject="user@example.com")
    assert decode_access_token(token) == "user@example.com"
    assert decode_access_token("not-a-valid-token") is None


def test_jwt_previous_key_still_decodes(monkeypatch) -> None:
    """During JWT_SECRET_KEY rotation, tokens signed by the prior key must
    still verify until they expire. New tokens are signed by the new key."""
    from jose import jwt as jose_jwt

    from app.auth import security
    from app.config import settings

    old_key = settings.jwt_secret_key
    new_key = "rotated-key-also-needs-to-be-at-least-32-characters-long"

    # Simulate a token already issued under the old key.
    old_token = create_access_token(subject="rotated@example.com")

    monkeypatch.setattr(settings, "jwt_secret_key", new_key)
    monkeypatch.setattr(settings, "jwt_secret_key_previous", old_key)

    # Old token still verifies via the fallback key.
    assert decode_access_token(old_token) == "rotated@example.com"

    # New tokens are signed with the new key.
    new_token = create_access_token(subject="rotated@example.com")
    header = jose_jwt.get_unverified_header(new_token)
    assert header["alg"] == settings.jwt_algorithm
    assert decode_access_token(new_token) == "rotated@example.com"

    # After grace window: previous key is cleared, old tokens stop verifying.
    monkeypatch.setattr(settings, "jwt_secret_key_previous", "")
    assert decode_access_token(old_token) is None
    assert decode_access_token(new_token) == "rotated@example.com"


def test_register_login_and_me(client) -> None:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"

    register = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 201
    body = register.json()
    assert body["email"] == email
    assert "id" in body

    login = client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert "movies:read" in body["scopes"]
    assert "chat:use" in body["scopes"]


def test_roles_endpoint_lists_scopes(client) -> None:
    response = client.get("/auth/roles")
    assert response.status_code == 200
    roles = response.json()["roles"]
    assert "movies:read" in roles["user"]
    assert "users:read" in roles["admin"]
    assert "database:reindex" in roles["admin"]


def test_register_duplicate_email_returns_409(client) -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"

    first = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert first.status_code == 201

    second = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert second.status_code == 409


def test_login_with_wrong_password_returns_401(client) -> None:
    email = f"bad-{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"

    client.post("/auth/register", json={"email": email, "password": password})

    login = client.post(
        "/auth/login",
        data={"username": email, "password": "wrong-password"},
    )
    assert login.status_code == 401


def test_query_requires_authentication(client) -> None:
    response = client.post("/query", json={"question": "sci-fi movies about space"})
    assert response.status_code == 401


def test_hybrid_search_requires_authentication(client) -> None:
    response = client.get(
        "/movies/search",
        params={"q": "lonely astronauts drifting through deep space"},
    )
    assert response.status_code == 401
