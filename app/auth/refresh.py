from datetime import UTC, datetime

from psycopg.rows import dict_row

from app.auth.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expires_at,
)
from app.db import get_connection


class RefreshTokenError(Exception):
    pass


async def _store_refresh_token(*, user_id: int, raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    expires_at = refresh_token_expires_at()
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)
                """,
                {"user_id": user_id, "token_hash": token_hash, "expires_at": expires_at},
            )
            await conn.commit()


async def _get_refresh_row(raw_token: str) -> dict | None:
    token_hash = hash_refresh_token(raw_token)
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked_at,
                       u.email, u.role
                FROM refresh_tokens rt
                JOIN users u ON u.id = rt.user_id
                WHERE rt.token_hash = %(token_hash)s
                """,
                {"token_hash": token_hash},
            )
            return await cur.fetchone()


async def _revoke_refresh_row(row_id: str) -> None:
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE refresh_tokens
                SET revoked_at = now()
                WHERE id = %(id)s AND revoked_at IS NULL
                """,
                {"id": row_id},
            )
            await conn.commit()


async def _revoke_all_user_tokens(user_id: int) -> None:
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE refresh_tokens
                SET revoked_at = now()
                WHERE user_id = %(user_id)s AND revoked_at IS NULL
                """,
                {"user_id": user_id},
            )
            await conn.commit()


async def issue_token_pair(user: dict) -> tuple[str, str]:
    access_token = create_access_token(subject=user["email"])
    raw_refresh = generate_refresh_token()
    await _store_refresh_token(user_id=user["id"], raw_token=raw_refresh)
    return access_token, raw_refresh


async def rotate_refresh_token(raw_token: str) -> tuple[str, str]:
    row = await _get_refresh_row(raw_token)
    if row is None:
        raise RefreshTokenError("Invalid refresh token")

    if row["revoked_at"] is not None:
        await _revoke_all_user_tokens(row["user_id"])
        raise RefreshTokenError("Refresh token reuse detected")

    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise RefreshTokenError("Refresh token expired")

    await _revoke_refresh_row(str(row["id"]))

    user = {"id": row["user_id"], "email": row["email"], "role": row["role"]}
    return await issue_token_pair(user)


async def revoke_refresh_token(raw_token: str) -> None:
    row = await _get_refresh_row(raw_token)
    if row is None:
        return
    await _revoke_refresh_row(str(row["id"]))
