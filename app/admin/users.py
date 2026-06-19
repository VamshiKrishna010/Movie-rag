import json

from psycopg.rows import dict_row

from app.db import get_connection

ALLOWED_ROLES = frozenset({"user", "admin"})


class UserRoleError(Exception):
    pass


async def list_users() -> list[dict]:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, email, role, created_at
                FROM users
                ORDER BY email
                """
            )
            return await cur.fetchall()


async def count_admins() -> int:
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def update_user_role(*, user_id: int, role: str, actor_id: int) -> dict:
    if role not in ALLOWED_ROLES:
        raise UserRoleError("Invalid role")

    if user_id == actor_id and role != "admin":
        raise UserRoleError("Cannot demote your own admin account")

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, email, role FROM users WHERE id = %(user_id)s",
                {"user_id": user_id},
            )
            target = await cur.fetchone()
            if target is None:
                raise UserRoleError("User not found")

            if target["role"] == "admin" and role == "user":
                admin_count = await count_admins()
                if admin_count <= 1:
                    raise UserRoleError("Cannot remove the last admin")

            await cur.execute(
                """
                UPDATE users
                SET role = %(role)s
                WHERE id = %(user_id)s
                RETURNING id, email, role, created_at
                """,
                {"user_id": user_id, "role": role},
            )
            row = await cur.fetchone()
            await conn.commit()
            return row
