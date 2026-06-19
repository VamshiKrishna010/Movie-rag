from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.admin.movies import MovieAdminError, create_movie, get_movie, get_stats, list_movies, update_movie
from app.admin.users import UserRoleError, list_users, update_user_role
from app.auth.deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminStatsOut(BaseModel):
    user_count: int
    movie_count: int
    chunk_count: int
    genre_count: int


class AdminUserOut(BaseModel):
    id: int
    email: str
    role: str
    created_at: str


class RoleUpdateRequest(BaseModel):
    role: Literal["user", "admin"]


class MovieAdminFields(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    release_year: int | None = Field(default=None, ge=1800, le=2100)
    overview: str | None = None
    tagline: str | None = None
    runtime: int | None = Field(default=None, ge=1, le=1000)
    vote_average: float | None = Field(default=None, ge=0, le=10)
    poster_path: str | None = None
    backdrop_path: str | None = None


class MovieCreateRequest(MovieAdminFields):
    id: int = Field(..., ge=1)


class MovieAdminOut(BaseModel):
    id: int
    title: str
    release_year: int | None
    overview: str | None
    tagline: str | None
    runtime: int | None
    vote_average: float | None
    poster_path: str | None
    backdrop_path: str | None


class PaginatedMoviesAdminOut(BaseModel):
    movies: list[MovieAdminOut]
    page: int
    limit: int
    total: int
    total_pages: int


@router.get("/stats", response_model=AdminStatsOut)
async def admin_stats(_admin: Annotated[dict, Depends(require_admin)]) -> AdminStatsOut:
    row = await get_stats()
    return AdminStatsOut(**row)


@router.get("/users", response_model=list[AdminUserOut])
async def admin_list_users(_admin: Annotated[dict, Depends(require_admin)]) -> list[AdminUserOut]:
    users = await list_users()
    return [
        AdminUserOut(
            id=u["id"],
            email=u["email"],
            role=u["role"],
            created_at=u["created_at"].isoformat(),
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def admin_update_user_role(
    user_id: int,
    req: RoleUpdateRequest,
    admin: Annotated[dict, Depends(require_admin)],
) -> AdminUserOut:
    try:
        user = await update_user_role(
            user_id=user_id,
            role=req.role,
            actor_id=admin["id"],
        )
    except UserRoleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AdminUserOut(
        id=user["id"],
        email=user["email"],
        role=user["role"],
        created_at=user["created_at"].isoformat(),
    )


@router.get("/movies", response_model=PaginatedMoviesAdminOut)
async def admin_list_movies(
    _admin: Annotated[dict, Depends(require_admin)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
) -> PaginatedMoviesAdminOut:
    data = await list_movies(page=page, limit=limit, q=q.strip() if q else None)
    return PaginatedMoviesAdminOut(**data)


@router.get("/movies/{movie_id}", response_model=MovieAdminOut)
async def admin_get_movie(
    movie_id: int,
    _admin: Annotated[dict, Depends(require_admin)],
) -> MovieAdminOut:
    movie = await get_movie(movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    return MovieAdminOut(**movie)


@router.post("/movies", response_model=MovieAdminOut, status_code=status.HTTP_201_CREATED)
async def admin_create_movie(
    req: MovieCreateRequest,
    _admin: Annotated[dict, Depends(require_admin)],
) -> MovieAdminOut:
    try:
        movie = await create_movie(req.model_dump())
    except MovieAdminError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if "already exists" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return MovieAdminOut(**movie)


@router.patch("/movies/{movie_id}", response_model=MovieAdminOut)
async def admin_update_movie(
    movie_id: int,
    req: MovieAdminFields,
    _admin: Annotated[dict, Depends(require_admin)],
) -> MovieAdminOut:
    try:
        movie = await update_movie(movie_id, req.model_dump())
    except MovieAdminError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return MovieAdminOut(**movie)
