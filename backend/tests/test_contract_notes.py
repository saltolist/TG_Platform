import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import sample_global_note, writer_auth_headers
from tests.contract_schemas import GlobalNoteContract, parse_global_notes_list


@pytest.mark.asyncio
async def test_global_notes_upsert_delete_contract(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    note_id = str(uuid.uuid4())
    payload = sample_global_note(note_id)

    upsert = await client.put(
        f"/api/v1/global-notes/{note_id}/",
        headers=writer_auth_headers,
        json=payload,
    )
    assert upsert.status_code == 200
    created = GlobalNoteContract.model_validate(upsert.json())
    assert created.title == payload["title"]

    listed = await client.get("/api/v1/global-notes/", headers=writer_auth_headers)
    notes = parse_global_notes_list(listed.json())
    assert any(note.id == note_id for note in notes)

    mismatch = await client.put(
        f"/api/v1/global-notes/{note_id}/",
        headers=writer_auth_headers,
        json={**payload, "id": "other-id"},
    )
    assert mismatch.status_code == 422

    delete = await client.delete(f"/api/v1/global-notes/{note_id}/", headers=writer_auth_headers)
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_global_notes_seed_string_id(client: AsyncClient, writer_auth_headers: dict) -> None:
    note_id = "pn-contract-1"
    payload = sample_global_note(note_id, title="Seed-style id")

    upsert = await client.put(
        f"/api/v1/global-notes/{note_id}/",
        headers=writer_auth_headers,
        json=payload,
    )
    assert upsert.status_code == 200
    assert GlobalNoteContract.model_validate(upsert.json()).id == note_id
