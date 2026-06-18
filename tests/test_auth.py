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
    assert me.json()["email"] == email


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
