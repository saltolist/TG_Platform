"""Launch immutable formal canaries from query digests already present in AgentRun history."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.models import AgentRun, User
from app.db.session import async_session_factory
from app.services.agent.runtime.runs import start_run
from app.tasks.agent_runs import execute_agent_run_task


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    BACKEND_ROOT
    / "tests/fixtures/agent_unified_phase6/v174/formal_canary_manifest.json"
)
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sequences(value: str, maximum: int) -> list[int]:
    if value.strip().lower() == "all":
        return list(range(1, maximum + 1))
    result = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not result or any(item < 1 or item > maximum for item in result):
        raise ValueError(f"sequences must be within 1..{maximum}")
    return result


async def launch(
    *,
    manifest_path: Path,
    sequences_text: str,
    user_email: str,
    wait: bool,
    timeout_seconds: int,
    shadow_reasoner_model: str | None = None,
    shadow_reasoner_provider: str | None = None,
    answer_model_id: str | None = None,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenarios = list(manifest.get("scenarios") or ())
    sequences = _sequences(sequences_text, len(scenarios))
    wanted = {
        str(scenarios[sequence - 1]["query_digest"]): sequence for sequence in sequences
    }

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.email == user_email))
        if user is None:
            raise RuntimeError("canary_user_not_found")
        historical = list(
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.user_id == user.id)
                .order_by(AgentRun.created_at.desc())
            )
        )
        queries: dict[str, str] = {}
        for run in historical:
            query = str((run.snapshot or {}).get("user_text") or "").strip()
            if query and (query_digest := _digest(query)) in wanted:
                queries.setdefault(query_digest, query)
            if wanted.keys() <= queries.keys():
                break
        missing = sorted(set(wanted) - set(queries))
        if missing:
            raise RuntimeError("missing_historical_query_digests:" + ",".join(missing))

        stamp = int(time.time())
        run_ids: dict[int, str] = {}
        for query_digest, sequence in sorted(wanted.items(), key=lambda item: item[1]):
            run, _ = await start_run(
                session,
                user=user,
                thread_id=f"formal-canary-{stamp}-{sequence:02d}",
                scope="global",
                answer_llm_id=answer_model_id,
            )
            run_ids[sequence] = str(run.id)
            execute_agent_run_task.apply_async(
                args=[str(run.id), queries[query_digest], shadow_reasoner_model]
                + ([shadow_reasoner_provider] if shadow_reasoner_provider else [])
                if shadow_reasoner_model
                else [str(run.id), queries[query_digest]],
                queue="agent-interactive",
            )

    result: dict[str, object] = {
        "manifest": str(manifest_path),
        "mode": "shadow" if shadow_reasoner_model else "production_selector",
        "shadow_reasoner_model": shadow_reasoner_model,
        "shadow_reasoner_provider": shadow_reasoner_provider,
        "answer_model_id": answer_model_id,
        "runs": {str(sequence): run_id for sequence, run_id in run_ids.items()},
    }
    if not wait:
        return result

    deadline = time.monotonic() + timeout_seconds
    statuses: dict[int, str] = {}
    while time.monotonic() < deadline:
        async with async_session_factory() as session:
            rows = list(
                await session.scalars(
                    select(AgentRun).where(
                        AgentRun.id.in_([uuid.UUID(value) for value in run_ids.values()])
                    )
                )
            )
        statuses = {
            sequence: next(
                (row.status for row in rows if str(row.id) == run_id), "missing"
            )
            for sequence, run_id in run_ids.items()
        }
        if all(status in TERMINAL_STATUSES for status in statuses.values()):
            break
        await asyncio.sleep(2)
    result["statuses"] = {
        str(sequence): status for sequence, status in sorted(statuses.items())
    }
    result["timed_out"] = not all(
        status in TERMINAL_STATUSES for status in statuses.values()
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sequences", default="all")
    parser.add_argument("--user-email", default="prime1@mail.ru")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--shadow-reasoner-model",
        default=None,
        help=(
            "Diagnostic-only planner/research model override. The normal user "
            "selector and answer model are unchanged."
        ),
    )
    parser.add_argument(
        "--answer-model-id",
        default=None,
        help=(
            "Diagnostic canary override for the persisted user-selected answer "
            "model id. The API's normal selector remains unchanged."
        ),
    )
    parser.add_argument(
        "--shadow-reasoner-provider",
        default=None,
        help="Diagnostic provider paired with --shadow-reasoner-model.",
    )
    args = parser.parse_args()
    result = asyncio.run(
        launch(
            manifest_path=args.manifest,
            sequences_text=args.sequences,
            user_email=args.user_email,
            wait=args.wait,
            timeout_seconds=args.timeout_seconds,
            shadow_reasoner_model=args.shadow_reasoner_model,
            shadow_reasoner_provider=args.shadow_reasoner_provider,
            answer_model_id=args.answer_model_id,
        )
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
