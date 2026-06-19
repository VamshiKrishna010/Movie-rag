from typing import Final

Scope = str

MOVIES_READ: Final = "movies:read"
MOVIES_CREATE: Final = "movies:create"
MOVIES_UPDATE: Final = "movies:update"
MOVIES_DELETE: Final = "movies:delete"
CHAT_USE: Final = "chat:use"
FAVORITES_CREATE: Final = "favorites:create"
PROFILE_UPDATE: Final = "profile:update"
USERS_READ: Final = "users:read"
USERS_DISABLE: Final = "users:disable"
DATABASE_REINDEX: Final = "database:reindex"

USER_SCOPES: tuple[Scope, ...] = (
    MOVIES_READ,
    CHAT_USE,
    FAVORITES_CREATE,
    PROFILE_UPDATE,
)

ADMIN_SCOPES: tuple[Scope, ...] = USER_SCOPES + (
    MOVIES_CREATE,
    MOVIES_UPDATE,
    MOVIES_DELETE,
    USERS_READ,
    USERS_DISABLE,
    DATABASE_REINDEX,
)

ROLE_SCOPES: dict[str, tuple[Scope, ...]] = {
    "user": USER_SCOPES,
    "admin": ADMIN_SCOPES,
}


def scopes_for_role(role: str) -> list[Scope]:
    return list(ROLE_SCOPES.get(role, USER_SCOPES))


def has_scope(user_scopes: list[Scope], scope: Scope) -> bool:
    return scope in user_scopes


def has_all_scopes(user_scopes: list[Scope], *required: Scope) -> bool:
    scope_set = set(user_scopes)
    return all(scope in scope_set for scope in required)
