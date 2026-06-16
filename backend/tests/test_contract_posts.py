import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import sample_post, writer_auth_headers
from tests.contract_schemas import PostContract, parse_posts_list


@pytest.mark.asyncio
async def test_posts_list_matches_contract(client: AsyncClient, writer_auth_headers: dict) -> None:
    response = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert response.status_code == 200
    parse_posts_list(response.json())


@pytest.mark.asyncio
async def test_posts_create_patch_delete_contract(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Before patch")

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201
    created = PostContract.model_validate(create.json())
    assert created.text == "Before patch"

    patch = await client.patch(
        f"/api/v1/posts/{post_id}/",
        headers=writer_auth_headers,
        json={"text": "After patch", "rubric": "News"},
    )
    assert patch.status_code == 200
    patched = PostContract.model_validate(patch.json())
    assert patched.text == "After patch"
    assert patched.rubric == "News"
    assert patched.id == post_id

    listed = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    posts = parse_posts_list(listed.json())
    assert any(post.id == post_id and post.text == "After patch" for post in posts)

    delete = await client.delete(f"/api/v1/posts/{post_id}/", headers=writer_auth_headers)
    assert delete.status_code == 204

    after_delete = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert all(post.id != post_id for post in parse_posts_list(after_delete.json()))


@pytest.mark.asyncio
async def test_posts_reorder_contract(client: AsyncClient, writer_auth_headers: dict) -> None:
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    first = sample_post(first_id, text="First")
    second = sample_post(second_id, text="Second")

    await client.post("/api/v1/posts/", headers=writer_auth_headers, json=first)
    await client.post("/api/v1/posts/", headers=writer_auth_headers, json=second)

    reorder = await client.put(
        "/api/v1/posts/reorder/",
        headers=writer_auth_headers,
        json={"posts": [second, first]},
    )
    assert reorder.status_code == 200
    ordered = parse_posts_list(reorder.json())
    assert [post.id for post in ordered] == [second_id, first_id]


@pytest.mark.asyncio
async def test_posts_trailing_slash(client: AsyncClient, writer_auth_headers: dict) -> None:
    response = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert response.status_code == 200

    no_slash = await client.get("/api/v1/posts", headers=writer_auth_headers, follow_redirects=True)
    assert no_slash.status_code == 200
