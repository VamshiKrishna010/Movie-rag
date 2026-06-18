from psycopg.rows import dict_row

from app.db import get_connection


async def get_user_by_email(email: str) -> dict | None:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, email, hashed_password, role, created_at FROM users WHERE email = %(email)s",
                {"email": email.lower()},
            )
            return await cur.fetchone()


async def create_user(email: str, hashed_password: str) -> dict:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO users (email, hashed_password)
                VALUES (%(email)s, %(hashed_password)s)
                RETURNING id, email, role, created_at
                """,
                {"email": email.lower(), "hashed_password": hashed_password},
            )
            row = await cur.fetchone()
            await conn.commit()
            return row
