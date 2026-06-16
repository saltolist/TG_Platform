import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.db.models import Post
from app.schemas.requests import ReorderRequest
from app.schemas.resources import PostIn

router = APIRouter(prefix="/posts", tags=["Posts"])


async def _get_owned(session: DbSession, user_id: uuid.UUID, post_id: str) -> Post:
    try:
        pid = uuid.UUID(post_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Post not found")
    post = await session.get(Post, pid)
    if post is None or post.user_id != user_id:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("/")
async def list_posts(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(Post).where(Post.user_id == user.id).order_by(Post.position, Post.created_at)
    )
    return [post.data for post in result.scalars().all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_post(payload: PostIn, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    try:
        post_id = uuid.UUID(payload.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный id поста")

    data = payload.model_dump()
    count = await session.scalar(
        select(func.count()).select_from(Post).where(Post.user_id == user.id)
    )
    session.add(Post(id=post_id, user_id=user.id, position=count or 0, data=data))
    await session.commit()
    return data


@router.put("/reorder/")
async def reorder_posts(
    payload: ReorderRequest, user: CurrentUser, session: DbSession
) -> list[dict[str, Any]]:
    result = await session.execute(select(Post).where(Post.user_id == user.id))
    by_id = {str(post.id): post for post in result.scalars().all()}

    ordered: list[dict[str, Any]] = []
    for index, item in enumerate(payload.posts):
        post = by_id.get(str(item.get("id")))
        if post is None:
            continue
        post.position = index
        post.data = item
        ordered.append(item)

    await session.commit()
    return ordered


@router.patch("/{post_id}/")
async def update_post(
    post_id: str, patch: dict[str, Any], user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    post = await _get_owned(session, user.id, post_id)
    merged = {**post.data, **patch}
    merged["id"] = post.data.get("id", str(post.id))
    post.data = merged
    await session.commit()
    return merged


@router.delete("/{post_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: str, user: CurrentUser, session: DbSession) -> Response:
    post = await _get_owned(session, user.id, post_id)
    await session.delete(post)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
