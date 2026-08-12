"""PostgreSQL corpus, query-plan and mixed-load benchmark for agent phase 8."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.services.agent.research.prefetch import DISCOVERY_FTS_DOCUMENT_SQL
from app.services.agent.runtime.profile_limits import limits_for_profile

BENCHMARK_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000008008")
TENANT_KEY = "phase8-tenant"
MODEL_KEY = "phase8-benchmark:3d"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://tg:tg@localhost:5432/tg_test"

FTS_SQL = text(
    f"""
    SELECT note_id
    FROM note_embeddings
    WHERE user_id = :user_id
      AND tenant_key = :tenant_key
      AND scope = 'global'
      AND node_type IN ('note_summary', 'post_summary')
      AND object_status IN ('active', 'published')
      AND model_key = :model_key
      AND {DISCOVERY_FTS_DOCUMENT_SQL} @@ plainto_tsquery('simple', :query)
    ORDER BY ts_rank(
      {DISCOVERY_FTS_DOCUMENT_SQL}, plainto_tsquery('simple', :query)
    ) DESC, note_id
    LIMIT 5
    """
)

METADATA_SQL = text(
    """
    SELECT count(*)
    FROM note_embeddings
    WHERE user_id = :user_id
      AND tenant_key = :tenant_key
      AND scope = 'global'
      AND node_type = 'note_summary'
      AND object_status = 'active'
      AND index_revision >= :min_revision
      AND model_key = :model_key
    """
)


def _database_name(url: str) -> str:
    return urlparse(url.replace("+asyncpg", "")).path.lstrip("/").split("?", 1)[0]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile) - 1))
    return ordered[index]


def _plan_indexes(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    result = {str(node["Index Name"])} if node.get("Index Name") else set()
    for child in node.get("Plans") or ():
        result.update(_plan_indexes(child))
    return result


async def _prepare_corpus(engine: AsyncEngine, objects_per_kind: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": BENCHMARK_USER_ID},
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, is_seed) "
                "VALUES (:user_id, 'agent-phase8-benchmark@example.invalid', 'benchmark', false)"
            ),
            {"user_id": BENCHMARK_USER_ID},
        )
        await conn.execute(
            text(
                """
                INSERT INTO global_notes (id, user_id, data, created_at)
                SELECT md5('phase8-note-row-' || value)::uuid,
                       :user_id,
                       jsonb_build_object(
                         'id', 'note-' || value,
                         'title', 'Note topic ' || (value % 25) || ' object ' || value,
                         'body', 'Tenant launch knowledge sentinel' || value ||
                                 ' topic' || (value % 25),
                         'status', 'active',
                         'revision', value
                       ),
                       now() - make_interval(secs => value)
                FROM generate_series(1, :count) AS value
                """
            ),
            {"user_id": BENCHMARK_USER_ID, "count": objects_per_kind},
        )
        await conn.execute(
            text(
                """
                INSERT INTO posts (id, user_id, position, data, created_at)
                SELECT md5('phase8-post-row-' || value)::uuid,
                       :user_id,
                       value,
                       jsonb_build_object(
                         'id', 'post-' || value,
                         'text', 'Post topic ' || (value % 25) ||
                                 ' tenant launch sentinel' || value,
                         'status', 'published',
                         'revision', value,
                         'notes', jsonb_build_array(),
                         'chats', jsonb_build_array()
                       ),
                       now() - make_interval(secs => value)
                FROM generate_series(1, :count) AS value
                """
            ),
            {"user_id": BENCHMARK_USER_ID, "count": objects_per_kind},
        )
        await conn.execute(
            text(
                """
                INSERT INTO note_embeddings (
                  id, user_id, tenant_key, scope, node_type, note_id, file_id,
                  post_id, chunk_index, model_key, dim, content_hash, chunk_text,
                  search_text, referenced_ids, object_title, object_status,
                  index_revision, keywords, embedding
                )
                SELECT gen_random_uuid(), :user_id, :tenant_key, 'global', kind || '_summary',
                       kind || '-' || value, '',
                       CASE WHEN kind = 'post' THEN kind || '-' || value ELSE NULL END,
                       0, embedding_model_key, 3, md5(kind || value || embedding_model_key),
                       initcap(kind) || ' source body sentinel' || value,
                       initcap(kind) || ' summary topic' || (value % 25) ||
                         ' tenant launch sentinel' || value,
                       '[]'::jsonb,
                       initcap(kind) || ' topic ' || (value % 25) || ' object ' || value,
                       CASE WHEN kind = 'post' THEN 'published' ELSE 'active' END,
                       value,
                       jsonb_build_array('topic' || (value % 25), 'sentinel' || value),
                       '[1,0,0]'
                FROM (VALUES ('note'), ('post')) AS kinds(kind)
                CROSS JOIN generate_series(1, :count) AS value
                CROSS JOIN (
                  VALUES (:model_key), ('phase8-benchmark-other:3d')
                ) AS models(embedding_model_key)
                """
            ),
            {
                "user_id": BENCHMARK_USER_ID,
                "tenant_key": TENANT_KEY,
                "model_key": MODEL_KEY,
                "count": objects_per_kind,
            },
        )
    async with engine.connect() as conn:
        await conn.execute(text("ANALYZE note_embeddings"))
        await conn.commit()


def _params(query: str) -> dict[str, Any]:
    return {
        "user_id": BENCHMARK_USER_ID,
        "tenant_key": TENANT_KEY,
        "model_key": MODEL_KEY,
        "query": query,
    }


async def _measure_queries(
    engine: AsyncEngine,
    queries: list[str],
    *,
    force_seq_scan: bool,
) -> tuple[list[float], list[list[str]]]:
    latencies: list[float] = []
    results: list[list[str]] = []
    async with engine.connect() as conn:
        if force_seq_scan:
            await conn.execute(text("SET enable_indexscan = off"))
            await conn.execute(text("SET enable_bitmapscan = off"))
        for query in queries:
            started = time.perf_counter()
            rows = (await conn.execute(FTS_SQL, _params(query))).scalars().all()
            latencies.append((time.perf_counter() - started) * 1000)
            results.append([str(item) for item in rows])
        if force_seq_scan:
            await conn.execute(text("RESET enable_indexscan"))
            await conn.execute(text("RESET enable_bitmapscan"))
    return latencies, results


async def _explain(engine: AsyncEngine, statement, params: dict[str, Any]) -> dict[str, Any]:
    compiled = statement.bindparams(
        *(bindparam(key, value=value) for key, value in params.items())
    ).compile(dialect=engine.sync_engine.dialect, compile_kwargs={"literal_binds": True})
    async with engine.connect() as conn:
        raw = (
            await conn.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")
            )
        ).scalar_one()
    payload = raw if isinstance(raw, list) else json.loads(raw)
    return dict(payload[0])


async def _timed_fts(engine: AsyncEngine, query: str) -> float:
    started = time.perf_counter()
    async with engine.connect() as conn:
        await conn.execute(FTS_SQL, _params(query))
    return (time.perf_counter() - started) * 1000


async def _timed_batch_page(engine: AsyncEngine, after_id: uuid.UUID | None) -> float:
    started = time.perf_counter()
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "SELECT id FROM global_notes WHERE user_id = :user_id "
                "AND (CAST(:after_id AS uuid) IS NULL OR id > CAST(:after_id AS uuid)) "
                "ORDER BY id LIMIT 100"
            ),
            {"user_id": BENCHMARK_USER_ID, "after_id": after_id},
        )
    return (time.perf_counter() - started) * 1000


async def _load_mix(engine: AsyncEngine, queries: list[str]) -> dict[str, Any]:
    interactive_slots = asyncio.Semaphore(8)
    batch_slots = asyncio.Semaphore(1)

    async def interactive(query: str) -> float:
        async with interactive_slots:
            return await _timed_fts(engine, query)

    async def batch(after_id: uuid.UUID) -> float:
        async with batch_slots:
            return await _timed_batch_page(engine, after_id)

    await asyncio.gather(*(interactive(query) for query in queries[:8]))
    interactive_only = await asyncio.gather(*(interactive(query) for query in queries * 2))
    batch_ids = [uuid.UUID(int=index + 1) for index in range(20)]
    mixed = await asyncio.gather(
        *(interactive(query) for query in queries * 2),
        *(batch(value) for value in batch_ids),
    )
    interactive_mixed = list(mixed[: len(queries) * 2])
    batch_mixed = list(mixed[len(queries) * 2 :])
    baseline_p95 = _percentile(list(interactive_only), 0.95)
    mixed_p95 = _percentile(interactive_mixed, 0.95)
    return {
        "mix": {"interactive": 80, "batch": 20},
        "interactive_only_p95_ms": round(baseline_p95, 3),
        "interactive_mixed_p95_ms": round(mixed_p95, 3),
        "batch_page_p95_ms": round(_percentile(batch_mixed, 0.95), 3),
        "interactive_p95_inflation": round(mixed_p95 / baseline_p95, 3)
        if baseline_p95
        else 0.0,
        "errors": 0,
    }


async def build_report(
    *,
    database_url: str,
    objects_per_kind: int,
    keep_corpus: bool,
) -> dict[str, Any]:
    if _database_name(database_url) in {"tg", "postgres"}:
        raise RuntimeError("phase-8 benchmark refuses a non-test database")
    engine = create_async_engine(database_url, pool_size=12, max_overflow=12)
    queries = [f"sentinel{((index * 23) % objects_per_kind) + 1}" for index in range(40)]
    expected = [
        {
            f"note-{((index * 23) % objects_per_kind) + 1}",
            f"post-{((index * 23) % objects_per_kind) + 1}",
        }
        for index in range(40)
    ]
    try:
        await _prepare_corpus(engine, objects_per_kind)
        baseline_latency, baseline_rows = await _measure_queries(
            engine, queries, force_seq_scan=True
        )
        indexed_latency, indexed_rows = await _measure_queries(
            engine, queries, force_seq_scan=False
        )
        baseline_recall = statistics.mean(
            len(set(rows) & wanted) / len(wanted)
            for rows, wanted in zip(baseline_rows, expected)
        )
        indexed_recall = statistics.mean(
            len(set(rows) & wanted) / len(wanted)
            for rows, wanted in zip(indexed_rows, expected)
        )
        fts_plan = await _explain(engine, FTS_SQL, _params(queries[0]))
        metadata_plan = await _explain(
            engine,
            METADATA_SQL,
            {
                "user_id": BENCHMARK_USER_ID,
                "tenant_key": TENANT_KEY,
                "model_key": MODEL_KEY,
                "min_revision": max(1, int(objects_per_kind * 0.9)),
            },
        )
        fts_indexes = sorted(_plan_indexes(fts_plan.get("Plan")))
        metadata_indexes = sorted(_plan_indexes(metadata_plan.get("Plan")))
        load = await _load_mix(engine, queries)
        limits = limits_for_profile("topical_answer")
        baseline_p95 = _percentile(baseline_latency, 0.95)
        indexed_p95 = _percentile(indexed_latency, 0.95)
        return {
            "schema": "workspace.agent-phase8-report/v1",
            "corpus": {
                "notes": objects_per_kind,
                "posts": objects_per_kind,
                "tenant_key": TENANT_KEY,
            },
            "quality": {
                "baseline_recall_at_5": baseline_recall,
                "phase8_recall_at_5": indexed_recall,
                "delta": indexed_recall - baseline_recall,
            },
            "latency": {
                "baseline_seq_scan_p50_ms": round(statistics.median(baseline_latency), 3),
                "baseline_seq_scan_p95_ms": round(baseline_p95, 3),
                "phase8_indexed_p50_ms": round(statistics.median(indexed_latency), 3),
                "phase8_indexed_p95_ms": round(indexed_p95, 3),
                "p95_reduction": round((baseline_p95 - indexed_p95) / baseline_p95, 4)
                if baseline_p95
                else 0.0,
                "db_p95_limit_ms": limits.db_p95_ms,
            },
            "plans": {
                "fts_indexes": fts_indexes,
                "metadata_indexes": metadata_indexes,
            },
            "load": load,
            "hnsw": {
                "added": False,
                "reason": (
                    "mixed-dimension embeddings remain TEXT; lexical/metadata "
                    "plans meet the DB SLO"
                ),
            },
        }
    finally:
        if not keep_corpus:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": BENCHMARK_USER_ID},
                )
        await engine.dispose()


def check_report(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    corpus = report["corpus"]
    quality = report["quality"]
    latency = report["latency"]
    plans = report["plans"]
    load = report["load"]
    if corpus["notes"] < 1000 or corpus["posts"] < 1000:
        issues.append("benchmark corpus is below 1000 objects per kind")
    if quality["phase8_recall_at_5"] < quality["baseline_recall_at_5"]:
        issues.append("retrieval recall regressed")
    if quality["phase8_recall_at_5"] < 0.95:
        issues.append("retrieval recall is below 0.95")
    if "ix_note_embeddings_discovery_fts" not in plans["fts_indexes"]:
        issues.append("FTS plan did not use the GIN index")
    if "ix_note_embeddings_retrieval_metadata" not in plans["metadata_indexes"]:
        issues.append("metadata plan did not use the expected index")
    if latency["phase8_indexed_p95_ms"] > latency["db_p95_limit_ms"]:
        issues.append("indexed query p95 exceeds the profile DB SLO")
    if load["interactive_mixed_p95_ms"] > latency["db_p95_limit_ms"]:
        issues.append("mixed-load interactive p95 exceeds the DB SLO")
    if report["hnsw"]["added"]:
        issues.append("HNSW was added without a separate recall/plan proof")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument("--objects-per-kind", type=int, default=1000)
    parser.add_argument("--keep-corpus", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(
        build_report(
            database_url=args.database_url,
            objects_per_kind=max(1, args.objects_per_kind),
            keep_corpus=args.keep_corpus,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    issues = check_report(report)
    if args.check and issues:
        raise SystemExit("; ".join(issues))


if __name__ == "__main__":
    main()
