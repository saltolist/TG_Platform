"""Post-fix re-measure of productive vs wasted planner steps. Read-only bar runs."""

import asyncio
import sys

from sqlalchemy import select

from app.db.models import AgentEvent, AgentRun, GlobalChat, User
from app.db.session import async_session_factory


def classify(evs):
    steps = []
    pending = None
    prev = 0
    for e in evs:
        p = e.payload if e.payload else {}
        if e.event_type == "planner_step":
            pending = {"tool": p.get("tool"), "err": None, "grew": False}
            continue
        if e.event_type == "tool_result":
            if pending is None:
                continue
            cnt = len(p.get("record_ids") or [])
            pending["err"] = p.get("error")
            pending["grew"] = cnt > prev
            prev = cnt
            steps.append(pending)
            pending = None
    if pending is not None:
        steps.append(pending)
    return steps


def label(s):
    if s["tool"] == "Invalid":
        return "WASTE:invalid"
    if s["tool"] == "FinishRetrieval":
        return "finish"
    if s["err"]:
        return f"WASTE:error({s['err']})"
    if s["grew"]:
        return "productive"
    return "WASTE:no-new-evidence"


async def one_run(chat_id: str, user_text: str, i: int) -> dict:
    from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
    from app.services.agent.runtime.executor import execute_agent_run
    from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run

    await ensure_checkpointer_ready()
    async with async_session_factory() as session:
        gc = await session.scalar(select(GlobalChat).where(GlobalChat.id == chat_id))
        user = await session.scalar(select(User).where(User.id == gc.user_id))

        run, _ = await start_run(
            session, user=user,
            thread_id=f"pf{i}-{chat_id[:8]}",
            scope="global",
            chat_id=chat_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, user_text)
        await execute_agent_run(
            session, run=run, user=user, user_text=user_text, runtime_context=ctx
        )

        final = await session.scalar(select(AgentRun).where(AgentRun.id == run.id))
        snap = final.snapshot or {}
        evs = list(await session.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence.asc())
        ))

    steps = classify(evs)
    labels = [label(s) for s in steps]
    waste = sum(1 for x in labels if x.startswith("WASTE"))
    prod  = sum(1 for x in labels if x == "productive")
    nf    = sum(1 for x in labels if "not_found" in x)

    print(
        f"RUN {i}: status={final.status}"
        f" stopped={snap.get('stopped_reason')}"
        f" steps={len(steps)} productive={prod} wasted={waste}"
        f" not_found={nf}",
        flush=True,
    )
    for j, x in enumerate(labels):
        print(f"    {j + 1}. {steps[j]['tool']:16} -> {x}", flush=True)

    return {"waste": waste, "prod": prod, "nf": nf,
            "partial": snap.get("stopped_reason") == "partial"}


async def main(chat_id: str, user_text: str, n: int) -> None:
    agg = []
    for i in range(1, n + 1):
        try:
            agg.append(await one_run(chat_id, user_text, i))
        except Exception as e:
            print(f"RUN {i} FAILED: {e}", flush=True)

    if agg:
        tw = sum(r["waste"] for r in agg)
        tp = sum(r["prod"] for r in agg)
        tnf = sum(r["nf"] for r in agg)
        rate = 100 * tw / (tw + tp) if (tw + tp) else 0
        partial = sum(r["partial"] for r in agg)
        print(
            f"\nTOTAL over {n} runs:"
            f" productive={tp} wasted={tw}"
            f" waste_rate={rate:.0f}%"
            f" not_found={tnf}"
            f" partial_runs={partial}/{n}",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3])))
