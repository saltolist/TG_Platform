"""Evidence-driven research subgraph (LangGraph + bounded ReAct)."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.services.agent.research.evidence import EvidenceRecord, records_from_agent_state
from app.services.agent.research.pack import build_evidence_pack
from app.services.agent.research.plan import (
    merge_plan,
    open_items,
    parse_plan,
    render_plan_for_planner,
)
from app.services.agent.research.search_ledger import (
    cached_outcome,
    finish_intent,
    prepare_intent,
    render_search_ledger_for_planner,
)
from app.services.agent.research.result import ResearchResult
from app.services.agent.research.trust import UNTRUSTED_SYSTEM_NOTE, wrap_untrusted_block
from app.services.agent.research.verifier import verify_evidence
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.state import AgentGraphState
from app.services.agent.runtime.turn_contract import (
    covered_source_ids,
    evidence_matches_source,
    missing_required_sources,
    render_turn_contract,
)
from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_dialog_ledger import (
    TurnSnapshot,
    format_ledger_for_planner,
    seed_hydrated_attachments_from_ledger,
)
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_tools import (
    AgentState,
    ToolOutcome,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_global_notes,
    tool_list_note_attachments,
    tool_list_post_media,
    tool_list_post_notes,
    tool_list_posts,
    tool_open_note,
    tool_open_post,
    tool_search_object_chunks,
    tool_search_nodes,
)
from app.services.ai.reply_pipeline_log import trace_step

logger = logging.getLogger(__name__)

# Error codes that mean "you called this too early, do X first" — recoverable
# precondition guidance, not a failed lookup. Burning a step on these lets a
# single mis-ordered call (ListPostNotes before OpenPost) eat into the budget
# the run needs to actually reach the evidence, so we refund the step. `not_found`
# is deliberately absent: a genuinely missing post/note is a real (if empty)
# result, and refunding it would let a planner fishing for bad ids loop for free.
REFUNDABLE_TOOL_ERRORS = frozenset({"post_not_open", "note_not_found"})
# Hard ceiling on refunds per run: without it a planner stuck repeating the same
# broken call would get an unbounded free ride and never terminate.
MAX_STEP_REFUNDS = 3
# Hard ceiling on finish-gate bounces: a planner that keeps calling
# FinishRetrieval while plan items stay open is sent back this many times, then
# allowed through (the step budget is the ultimate backstop). Prevents a plan the
# model refuses to close from wedging the run (persistent-plan).
MAX_PLAN_REPAIRS = 2
# Finish-gate for the semantic prefetch (agent note-prefetch): a FinishRetrieval
# is bounced this many times while a *relevant* prefetch hit (a note/post surfaced
# by the seed SearchNodes) was never opened into citable evidence. One bounce is
# usually enough to nudge the planner to OpenNote; the cap stops a planner that
# refuses to open (e.g. genuinely irrelevant hit) from wedging the run.
MAX_PREFETCH_REPAIRS = 1
# Similarity floor for treating a prefetch hit as "should have been opened".
# Retrieval already filters at min_similarity=0.38; this higher gate keeps the
# guard from bouncing a legitimate finish over a marginal, tangential hit.
PREFETCH_GUARD_MIN_SIMILARITY = 0.45
# Only notes/posts are cheap to open blind (OpenNote/OpenPost by id). Attachment/
# media hits need a parent context to hydrate, so they don't drive the guard.
_PREFETCH_GUARD_TYPES = frozenset(
    {"note_chunk", "post_text", "note_summary", "post_summary"}
)


def unopened_prefetch_hits(
    hits: list[dict[str, Any]],
    records: dict[str, "EvidenceRecord"],
) -> list[dict[str, Any]]:
    """Prefetch hits (notes/posts, above the guard similarity) whose id never
    made it into an evidence record — i.e. surfaced as a candidate but never
    opened. Evidence is keyed by citation path (/note/global/<id>/, /post/<id>/)
    and a hit ref is <type>:<id>, so an id absent from every key means unopened."""
    keys = " ".join(records.keys())
    out: list[dict[str, Any]] = []
    for h in hits:
        if str(h.get("node_type") or "") not in _PREFETCH_GUARD_TYPES:
            continue
        if float(h.get("similarity") or 0.0) < PREFETCH_GUARD_MIN_SIMILARITY:
            continue
        ref = str(h.get("ref") or "")
        hit_id = ref.split(":", 1)[1].strip() if ":" in ref else ref.strip()
        if hit_id and hit_id not in keys:
            out.append(h)
    return out


READ_TOOLS = frozenset(
    {
        "SearchNodes",
        "SearchObjectChunks",
        "OpenPost",
        "OpenNote",
        "ListPosts",
        "ListPostNotes",
        "ListGlobalNotes",
        "ListNoteAttachments",
        "ListPostMedia",
        "HydrateAttachment",
        "GetPostAnalytics",
    }
)

AGENT_SYSTEM = (
    """Ты research-агент workspace. Собери факты read-tools и заверши через FinishRetrieval.

Доступные tools (JSON):
- SearchNodes {query, node_types?, k?} — семантический поиск: top-k узлов, похожих на запрос, а НЕ полный список. Показывает, что похоже, но не гарантирует, что нашлось всё релевантное — отсутствие чего-то среди результатов не значит, что этого нет. То же относится к автоматическому префетчу «[seed] SearchNodes …»: это разведка первого уровня (что дешёвый поиск успел найти по формулировке запроса) — она ориентирует, но НЕ задаёт границ задачи и не заменяет полную картину workspace. node_types (если задан) — только из набора: "note_chunk" (текст заметок), "post_text" (текст постов), "attachment_text" (текст документов-вложений), "media_meta" (имена медиа). Не придумывай другие значения; если сомневаешься — не передавай node_types вовсе (искать по всем).
- SearchObjectChunks {query, object_ids[], k?} — поиск contextual chunks ТОЛЬКО внутри уже выбранных object_ids; не расширяй список объектов этим tool.
- OpenPost {post_id}
- OpenNote {note_id, post_id?} — прочитать содержимое заметки; в выводе перечислены её вложения (имя+тип), поэтому для вопросов «есть ли в заметке картинки/файлы» отдельный ListNoteAttachments не нужен
- ListPosts {query?, limit?}
- ListPostNotes {post_id} — перечислить заметки поста (сначала OpenPost)
- ListGlobalNotes {} — перечислить заметки, НЕ привязанные ни к одному посту. Для вопросов про общее число/наличие заметок учитывай оба источника: заметки из ListPosts/ListPostNotes (по постам) + ListGlobalNotes (вне постов). Чтобы найти «заметку с вложениями/картинками», не открывай топикально-похожую наугад — заметки-кандидаты видны прямо в перечнях по маркерам вложений: в ListGlobalNotes/ListPostNotes у заметки стоит `files=N` (и `images=M`, если среди них картинки); в ListPosts у поста стоит `note_files=N`/`note_images=M`, если вложения есть в его заметках. Открывай (OpenNote) те, у кого маркер есть.
- ListNoteAttachments {note_id, post_id?} — файлы, приложенные к заметке (ref вида attachment:<id>)
- ListPostMedia {post_id} — медиа, приложенные напрямую к посту (ref вида file:<id>); сначала OpenPost. Голосовые/видео/кружочки/стикеры видны только по имени и типу — их содержимое прочитать нельзя.
- HydrateAttachment {ref, mode?, note_id?, post_id?} — прочитать вложение: mode=text для документов (PDF/DOCX/txt), mode=vision для изображений. Для ref вида attachment:<id> (вложение заметки, из ListNoteAttachments/OpenNote) укажи note_id — обязателен, вызов без него не сработает. Для ref вида file:<id> (медиа поста) укажи post_id.
- GetPostAnalytics {post_id, period?}
- FinishRetrieval {status: ready|partial, evidence_ids: string[], unresolved?: string[]}

Правила:
- Только read; никаких мутаций.
- Завершай, когда собрано достаточно для ответа.
- Блок «Контракт результата» авторитетен: target и corpus нельзя расширять или
  подменять семантически похожим объектом. Если corpus=feed_posts, заметки не
  являются источником ответа. Если corpus=exact_note, не открывай соседние заметки.
- Прошлые ответы ассистента в «Диалог» — не подтверждённые факты и не список
  обязательных действий. Не превращай прежнюю рекомендацию в план, пока её не
  поддерживает текущий контракт и доступные tools. В частности, не планируй
  «связать заметку с постами/файлами»: такого действия в workspace нет.
- Имя и тип файла (что показывает OpenNote/ListNoteAttachments) — это НЕ его содержимое. Если вопрос требует судить о том, ЧТО на изображении (подойдёт ли картинка посту, что на ней, какая из них про X) — одних имён недостаточно: открой картинку через HydrateAttachment mode=vision и суди по увиденному. Не финишируй с ответом о пригодности/содержании изображения, ни разу его не открыв — это догадка по имени файла. (Голосовые/видео/кружки/стикеры прочитать нельзя — по ним честно скажи, что содержимое недоступно.)
- В `evidence_ids` перечисляй ТОЛЬКО те id, что показаны в блоке «Собранный context» как `[id: …]` — дословно. Не выдумывай id и не подставляй номера постов.
- id постов и заметок (tech_id=…, note:…) — непрозрачные технические ключи для вызова инструментов (OpenPost/OpenNote/GetPostAnalytics). Это НЕ порядковый номер и НЕ позиция в серии: число внутри id (например tech_id=5) не значит «пятый пост» или «пост 5 из серии». Не сопоставляй значение id с нумерацией/порядком и не выводи из id никаких фактов о содержании.
- id для вызова Open*/GetPostAnalytics бери ТОЛЬКО из того, что реально увидел — из «Собранный context», из перечня (ListPosts/ListGlobalNotes/ListPostNotes) или из ledger/диалога. Не конструируй id сам (например из «Пост 3» или порядка) и не угадывай — вызов по выдуманному id проваливается и тратит шаг впустую. Если нужного id ещё нет на руках — сначала перечисли (ListPosts/ListGlobalNotes), затем открывай из выдачи.
- Нумерация ВНУТРИ текста заметки/поста («Пост 2», «до 6-го», «часть 3») — это авторская нумерация контента. Она не связана с tech_id постов в системе. Не отождествляй «Пост N из заметки» с постом, у которого tech_id=N.
- Если вопрос опирается на пользовательский термин или сущность («серия», «мой проект», «эта рубрика», «подборка»), значение которых НЕ определено собранным context — не придумывай трактовку и не завершай на догадке. Значение нужно установить по workspace, прежде чем отвечать. Блок «[seed] SearchNodes …» в «Ход агента» — это разведка первого уровня: подходящего кандидата среди хитов может и не быть (дешёвый поиск мог его не зацепить), а отсутствие в выдаче НЕ значит отсутствие в workspace. Если среди хитов есть кандидат, явно определяющий термин по названию/превью — открой его (OpenNote/OpenPost). Если явно подходящего нет — НЕ открывай ближайший наугад и не финишируй на нём: ищи целенаправленно (SearchNodes с уточнённым запросом) или перечисляй (ListPosts/ListGlobalNotes) и открывай из выдачи.

Диалог и Dialog evidence ledger — это история, а не рамка, сужающая поиск. Определяй охват по тому, ссылается ли вопрос на конкретные объекты прошлых ходов:
- Вопрос ссылается на конкретный объект («эта заметка», «неё», «из них», «в этом посте», «покороче») — работай с сущностями из ledger/диалога, не ищи заново через SearchNodes (используй OpenNote/OpenPost по id, если он уже известен из ledger). «Этот/этому пост(у)», «в этом посте» указывают на пост, о котором шла речь в предыдущей реплике (target_post_id из ledger), а НЕ на пост-хозяина заметки, которую ты открыл. Если заметка привязана к посту A, но в прошлом ходе обсуждался пост B — «этот пост» = B: открой именно его (OpenPost по id из ledger) и суди относительно него. Привязка заметки к своему посту не делает тот пост референтом «этого поста».
- Вопрос вводит новый критерий без явной привязки к обсуждавшимся объектам («а сколько с изображениями?», «какие из них длинные?», «а другие есть?») — это про ВСЮ категорию (все заметки/все посты), а не только про те несколько, что уже обсуждались. Ledger подсказывает тему, но не сужает область поиска: собери полный список (ListGlobalNotes/ListPosts/ListPostNotes), а не только уже открытые записи.
Пример ошибки, которую нужно избегать: пользователь спросил «сколько заметок про систему», агент открыл 2 заметки; на следующий вопрос «а сколько с изображениями?» агент проверил вложения только у этих двух и ответил «0» — хотя вопрос был про все заметки, а с изображениями была заметка, которую ещё не открывали.

Перед выбором tool сначала думай, потом решай. Верни один JSON СТРОГО в этом порядке ключей:
{
  "observations": ["что уже известно из «Ход агента» и «Собранный context», дословно/по смыслу — не выдумывай"],
  "reasoning": "почему этого недостаточно и что нужно сделать дальше",
  "answer_requires": "что должно быть верно, чтобы ОТВЕТ на вопрос был полным и не ошибочным — выведи из САМОЙ формулировки вопроса, а не из того, что показала разведка",
  "gap": "чего из answer_requires ещё нет на руках",
  "plan": [{"id": "1", "text": "подзадача", "status": "open|done|dropped", "reason": "для dropped", "evidence_id": "для done"}],
  "tool": "...",
  "args": {...}
}
`observations` — только то, что реально видно в «Ход агента» или «Собранный context» этого запроса. Если это первый шаг и обоих блоков нет — можно вернуть пустой список observations, но не придумывать наблюдения.

`answer_requires` — сформулируй ДО того, как смотреть на разведку («Ход агента», seed-хиты, инвентарь). Спроси себя: при каком условии мой ответ будет полным и его нельзя будет назвать ошибочным? Ответ выводится из вопроса, а не из того, что подвернулось под руку. Примеры: «порекомендуй тему поста» → ответ ошибочен, если тема уже покрыта существующим постом ⇒ answer_requires = «знать все уже написанные посты, чтобы не предложить дубль». «сократи эту заметку» → зависит только от самой заметки ⇒ answer_requires = «содержимое этой заметки». `gap` считай ОТНОСИТЕЛЬНО answer_requires: если ответ требует полной картины (все посты/все заметки), а разведка дала лишь пару кандидатов — этого НЕ достаточно, полноту собери сам. НО полнота ≠ «открыть всё подряд». Различай ШИРИНУ и ГЛУБИНУ:
— ШИРИНА (какие записи вообще есть и о чём они) берётся ДЁШЕВО перечнем: ListPosts/ListGlobalNotes дают по КАЖДОЙ записи заголовок+превью (+число заметок). Этого достаточно, чтобы судить «какие темы уже покрыты / что вообще есть», НЕ открывая каждую.
— ГЛУБИНА (полный текст записи) нужна только для тех записей, от содержимого которых реально зависит ответ. Открывай (OpenPost/OpenNote) ТОЧЕЧНО — те, что перечень или RAG показал релевантными, а не подряд.
Пример: «порекомендуй тему поста» → перечисли посты (ListPosts) ради тем + открой 1–2 самых близких кандидата, чтобы исключить дубль; открывать все посты подряд — это не «полнота», а трата шагов на нерелевантное. Если можешь обосновать ответ по перечню + точечным открытиям — не открывай остальное.

`plan` — твой план работы, который живёт весь ран и переносится между шагами (см. блок «План» во входе, если он есть):
- На ПЕРВОМ шаге разбей задачу на подзадачи от answer_requires, а не «на всякий случай». Формулируй по ширине/глубине: сначала дешёвая ширина, потом точечная глубина. Например для «порекомендуй тему»: «перечислить посты (ListPosts) — увидеть покрытые темы», «открыть 1–2 близких кандидата — исключить дубль», «проверить заметки вне постов (ListGlobalNotes)», «сформировать идею». Не ставь пунктом «открыть все посты/заметки», если ответ не требует полного текста каждого. Дай каждой подзадаче короткий стабильный `id`.
- На КАЖДОМ шаге возвращай ПОЛНЫЙ план со статусами. Можно добавлять новые пункты и менять статусы. НО пункт нельзя просто удалить: он уходит из работы только явным переходом.
- `status:"done"` требует `evidence_id` — id из блока «Собранный context», который реально закрывает пункт. Без валидного evidence_id пункт останется open.
- `status:"dropped"` требует `reason` (почему пункт больше не нужен — например «ListGlobalNotes вернул пусто»). Без причины пункт останется open.
- FinishRetrieval НЕ сработает, пока есть хоть один пункт со `status:"open"`. Если считаешь, что пора завершать, но пункт ещё open — либо выполни его (вызови нужный tool), либо закрой явно (done/dropped). Нельзя «забыть» о намеченном пункте.
- Если задача по ходу изменилась — не бросай старые пункты молча, помечай их dropped с причиной (например «superseded: пользователь спрашивал про структуру, а не идею») и добавляй новые.

OUTPUT LANGUAGE RULES (performance optimization — do not skip):
Write the values of these JSON fields in English:
  observations (each list item), reasoning, answer_requires, gap, plan[].text, plan[].reason
This reduces output token count ~3x and speeds up each planning step significantly.
Exception — the following MUST stay in the user's language (Russian):
  all values inside `args` (especially SearchNodes `query`) — must match the knowledge base language
  and embedding space. tool names are fixed identifiers, do not translate them.

"""
    + UNTRUSTED_SYSTEM_NOTE
    + "\n"
)


@dataclass(frozen=True)
class ToolAction:
    # Field order mirrors the decision schema (agent-runtime-sprints §3.1):
    # thought fields before the tool that acts on them, so any code reading
    # this dataclass positionally sees "why" before "what". Defaulted so
    # internal call sites that build a FinishRetrieval/fallback action
    # without a planner thought (no-LLM path, invalid-JSON fallback) don't
    # need to fabricate one.
    tool: str
    args: dict[str, Any]
    observations: tuple[str, ...] = ()
    reasoning: str = ""
    # Success condition derived from the QUESTION before looking at recon
    # (workspace-inventory §): what must be true for the answer to be complete
    # and not wrong. `gap` is then measured against THIS, not against what the
    # seed prefetch happened to surface — that reframing is the whole fix for
    # the planner anchoring its scope to cheap-RAG hits (chat 38e115df).
    answer_requires: str = ""
    gap: str = ""
    # Full plan the planner re-emits this step (persistent-plan). None means the
    # model said nothing about the plan → carry the previous plan unchanged;
    # merge_plan enforces the no-silent-drop invariant on whatever is present.
    plan: list[dict[str, Any]] | None = None


def parse_tool_action(raw: str) -> ToolAction | None:
    payload = extract_json_object(raw or "")
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if not tool:
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    raw_observations = payload.get("observations")
    observations = (
        tuple(str(item) for item in raw_observations)
        if isinstance(raw_observations, list)
        else ()
    )
    return ToolAction(
        observations=observations,
        reasoning=str(payload.get("reasoning") or ""),
        answer_requires=str(payload.get("answer_requires") or ""),
        gap=str(payload.get("gap") or ""),
        tool=tool,
        args=args,
        plan=parse_plan(payload.get("plan")),
    )


def validate_observations(
    observations: tuple[str, ...],
    *,
    transcript: list[str],
    records: dict[str, EvidenceRecord],
) -> list[str]:
    """Flag observations that don't ground in anything the planner actually saw.

    Anti-cosmetic check (agent-runtime-sprints §3.2): the thought must be
    derived from real transcript/tool output, not invented after the fact to
    justify a tool choice. An empty list is never flagged — the first step,
    before any transcript/evidence exists, legitimately has nothing to observe.
    Matching is substring-based on transcript lines and record titles/ids —
    intentionally loose (the model paraphrases), not a hallucination detector.
    """
    if not observations:
        return []
    # Drop empty/whitespace haystacks: "" is a substring of every string, so a
    # single blank line would make the `hay in needle` arm match everything and
    # silently disable the check. Transcript lines are f-string built and never
    # blank today, but this keeps the guard robust if that changes.
    haystacks = [stripped for line in transcript if (stripped := line.strip().lower())]
    for rec_id, rec in records.items():
        if rec_id.strip():
            haystacks.append(rec_id.strip().lower())
        if rec.citation_title.strip():
            haystacks.append(rec.citation_title.strip().lower())
    fabricated: list[str] = []
    for obs in observations:
        needle = obs.strip().lower()
        if not needle:
            continue
        if not any(needle in hay or hay in needle for hay in haystacks):
            fabricated.append(obs)
    return fabricated


def render_agent_context(state: AgentState) -> str:
    lines: list[str] = []
    for cite, plain in state.context_blocks[-12:]:
        title = getattr(cite, "title", "") or getattr(cite, "path", "")
        lines.append(f"### {title}\n{(plain or '')[:1200]}")
    return "\n\n".join(lines) if lines else "(контекст пуст)"


def _build_messages(
    *,
    user_text: str,
    transcript: list[str],
    hints: list[str],
    dialog_context: str,
    ledger_text: str,
    l1_summary: str,
    turn_contract: dict[str, Any] | None = None,
    plan_text: str = "",
    search_ledger_text: str = "",
) -> list[dict[str, str]]:
    parts = [f"Вопрос:\n{user_text.strip()}"]
    if turn_contract:
        parts.append(
            "Контракт результата (авторитетен; не расширяй target/corpus и не "
            "подменяй критерии соседней темой):\n"
            + render_turn_contract(turn_contract)
        )
    if dialog_context.strip():
        parts.append(f"Диалог:\n{dialog_context.strip()}")
    if ledger_text.strip():
        parts.append(ledger_text.strip())
    if l1_summary.strip():
        parts.append(l1_summary.strip())
    if plan_text.strip():
        parts.append(plan_text.strip())
    if search_ledger_text.strip():
        parts.append(search_ledger_text.strip())
    if hints:
        parts.append("Подсказки: " + "; ".join(hints))
    if transcript:
        parts.append("Ход агента:\n" + "\n".join(transcript[-12:]))
    parts.append("Текущий собранный контекст:\n" + "(см. transcript)")
    return [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


async def _execute_tool(state: AgentState, action: ToolAction) -> ToolOutcome:
    tool = action.tool
    args = action.args
    if tool == "SearchNodes":
        return await tool_search_nodes(
            state,
            query=str(args.get("query") or ""),
            node_types=args.get("node_types"),
            k=args.get("k"),
            expected_revisions=args.get("_expected_revisions"),
            object_statuses=frozenset(args.get("_object_statuses") or ()),
        )
    if tool == "SearchObjectChunks":
        raw_ids = args.get("object_ids") or []
        return await tool_search_object_chunks(
            state,
            query=str(args.get("query") or ""),
            object_ids=[str(item) for item in raw_ids] if isinstance(raw_ids, list) else [],
            k=args.get("k"),
            expected_revisions=args.get("_expected_revisions"),
            object_statuses=frozenset(args.get("_object_statuses") or ()),
        )
    if tool == "OpenPost":
        return await tool_open_post(state, post_id=str(args.get("post_id") or ""))
    if tool == "OpenNote":
        return await tool_open_note(
            state,
            note_id=str(args.get("note_id") or ""),
            post_id=args.get("post_id"),
        )
    if tool == "ListPosts":
        # Expose only the documented query/limit surface — no hidden status arg
        # that the planner was never told about (agent-runtime-sprints §1.4).
        return await tool_list_posts(
            state,
            status=str(args.get("status") or "all") or None,
            query=str(args.get("query") or "") or None,
            limit=int(args.get("limit") or 8),
        )
    if tool == "ListPostNotes":
        post_id = str(args.get("post_id") or "")
        outcome = tool_list_post_notes(state, post_id=post_id)
        if outcome.error == "post_not_open" and post_id:
            opened = await tool_open_post(state, post_id=post_id)
            if not opened.error:
                listed = tool_list_post_notes(state, post_id=post_id)
                return ToolOutcome(
                    summary=f"{opened.summary} {listed.summary}",
                    error=listed.error,
                )
        return outcome
    if tool == "ListGlobalNotes":
        return await tool_list_global_notes(state)
    if tool == "ListNoteAttachments":
        return await tool_list_note_attachments(
            state,
            note_id=str(args.get("note_id") or ""),
            post_id=args.get("post_id"),
        )
    if tool == "ListPostMedia":
        return tool_list_post_media(state, post_id=str(args.get("post_id") or ""))
    if tool == "HydrateAttachment":
        return await tool_hydrate_attachment(
            state,
            ref=str(args.get("ref") or ""),
            mode=str(args.get("mode") or "text"),
            # attachment:-refs (note files) require note_id to resolve; file:-refs
            # (post media) require post_id. Forward both — tool_hydrate_attachment
            # picks whichever the ref kind needs. note_id was previously dropped
            # here, so every planner call with a valid note_id still failed with
            # missing_note_id (chat 63dfb9e4: 5 straight HydrateAttachment retries,
            # each burning a step, none ever able to succeed).
            note_id=args.get("note_id"),
            post_id=args.get("post_id"),
        )
    if tool == "GetPostAnalytics":
        return await tool_get_post_analytics(
            state,
            post_id=str(args.get("post_id") or ""),
            period=str(args.get("period") or "7d"),
        )
    return ToolOutcome(summary=f"Неизвестный tool: {tool}", error="unknown_tool")


async def _execute_ledgered_tool(
    agent_state: AgentState,
    action: ToolAction,
    *,
    ledger: list[dict[str, Any]],
    contract: dict[str, Any] | None,
) -> tuple[ToolOutcome, list[dict[str, Any]], dict[str, Any], bool]:
    """Execute a read action once per canonical intent and return cache metadata."""
    preparation = prepare_intent(
        ledger,
        tool=action.tool,
        args=action.args,
        contract=contract,
        evidence_gap=action.gap,
    )
    entry = preparation.entry
    if not preparation.execute:
        summary, error, hits = cached_outcome(entry)
        return ToolOutcome(summary=summary, error=error, hits=hits), preparation.ledger, entry, True

    effective_action = action
    source_id = str(entry.get("source_requirement_id") or "")
    for source in (contract or {}).get("source_requirements") or ():
        if str(source.get("source_id") or "") != source_id:
            continue
        freshness = dict(source.get("freshness") or {})
        statuses = frozenset(
            str(item).strip().lower()
            for item in (source.get("scope") or {}).get("statuses") or ()
            if str(item).strip()
        )
        target_ids = [str(item) for item in (source.get("scope") or {}).get("target_ids") or ()]
        if freshness.get("mode") == "exact_revision" and freshness.get("revision") and target_ids:
            effective_action = ToolAction(
                tool=action.tool,
                args={
                    **action.args,
                    "_expected_revisions": {
                        object_id: int(freshness["revision"]) for object_id in target_ids
                    },
                    "_object_statuses": sorted(statuses),
                },
                observations=action.observations,
                reasoning=action.reasoning,
                answer_requires=action.answer_requires,
                gap=action.gap,
                plan=action.plan,
            )
        elif statuses:
            effective_action = ToolAction(
                tool=action.tool,
                args={**action.args, "_object_statuses": sorted(statuses)},
                observations=action.observations,
                reasoning=action.reasoning,
                answer_requires=action.answer_requires,
                gap=action.gap,
                plan=action.plan,
            )
        break
    outcome = await _execute_tool(agent_state, effective_action)
    records = records_from_agent_state(agent_state)
    updated = finish_intent(
        preparation.ledger,
        intent_key=str(entry.get("intent_key") or ""),
        summary=outcome.summary,
        error=outcome.error,
        hits=outcome.hits,
        record_ids=list(records),
    )
    final_entry = next(
        item for item in reversed(updated) if item.get("intent_key") == entry.get("intent_key")
    )
    return outcome, updated, final_entry, False


# ---------------------------------------------------------------------------
# Module-level research nodes (agent-runtime-sprints §1.0 single-graph).
#
# Lifted out of run_research_graph's closures so the SAME nodes power both the
# legacy run_research_graph entrypoint and the unified workspace graph. Each
# node reads the RuntimeContext + planner inputs from config["configurable"]
# instead of capturing them, so there is one graph, one checkpointer, one state.
# ---------------------------------------------------------------------------


def _planner_inputs(config: RunnableConfig) -> dict[str, Any]:
    conf = (config or {}).get("configurable", {}) if config else {}
    return {
        "dialog_context": str(conf.get("dialog_context") or ""),
        "dialog_ledger": tuple(conf.get("dialog_ledger") or ()),
        "l1_results": conf.get("l1_results"),
        "seed_ref": conf.get("seed_ref"),
        "seed_post_id": conf.get("seed_post_id"),
        "turn_contract": dict(conf.get("turn_contract") or {}),
    }


def _format_evidence_for_planner(records: dict[str, EvidenceRecord]) -> str:
    """List collected evidence with its natural id so the planner cites real keys.

    FinishRetrieval.evidence_ids must reference these ids verbatim; surfacing
    them here is what closes the empty-pack loop (agent-runtime-sprints §1.2).
    """
    if not records:
        return "(контекст пуст)"
    blocks: list[str] = []
    for rec_id, rec in records.items():
        title = rec.citation_title or rec_id
        body = (rec.content or "").strip()[:1200] or "(пусто)"
        # rec.content is user-controlled (post/note/attachment text): fence it as
        # untrusted so an injected instruction can't steer the planner (§6). The
        # natural id stays visible outside the body so FinishRetrieval can still
        # cite it verbatim (agent-runtime-sprints §1.2).
        fenced = wrap_untrusted_block(identifier=rec_id, title=title, body=body)
        blocks.append(f"[id: {rec_id}] {title}\n{fenced}")
    return "\n\n".join(blocks)


def _l1_summary(l1_results: list[dict[str, Any]] | None) -> str:
    if not l1_results:
        return ""
    previews = [
        f"- {item.get('node_type')}:{item.get('note_id')} sim={item.get('similarity', 0):.2f}"
        for item in l1_results[:6]
    ]
    return "L1 hits:\n" + "\n".join(previews)


def _contract_evidence_ids(
    contract: dict[str, Any],
    records: dict[str, EvidenceRecord],
) -> list[str]:
    """Keep only evidence from the corpus fixed by the turn contract."""
    target_contract = dict(contract.get("target_contract") or {})
    if target_contract:
        source_requirements = list(contract.get("source_requirements") or [])
        allowed: list[str] = []
        for record_id, record in records.items():
            record_payload = record.to_dict()
            if any(
                evidence_matches_source(source, evidence_id=record_id, record=record_payload)
                for source in source_requirements
            ):
                allowed.append(record_id)
        return allowed
    corpus = str(contract.get("corpus") or "workspace")
    if corpus == "feed_posts":
        return [
            record_id
            for record_id, record in records.items()
            if record.kind == "post_text" or record_id.startswith("/posts/")
        ]
    if corpus == "exact_note":
        target = dict(contract.get("target") or {})
        note_id = str(target.get("id") or "")
        if not note_id:
            return []
        return [
            record_id
            for record_id in records
            if f"/note/global/{note_id}/" in record_id
            or f"/note/post/" in record_id and f"/{note_id}/" in record_id
        ]
    return list(records)


def _contract_fast_finish_ids(
    contract: dict[str, Any],
    records: dict[str, EvidenceRecord],
) -> list[str]:
    ids = _contract_evidence_ids(contract, records)
    target_contract = dict(contract.get("target_contract") or {})
    if contract.get("execution_mode") == "fast" and target_contract:
        selected = {evidence_id: records[evidence_id].to_dict() for evidence_id in ids}
        covered = covered_source_ids(contract, selected)
        if not missing_required_sources(contract, covered):
            return ids
        return []
    corpus = str(contract.get("corpus") or "workspace")
    if corpus == "exact_note" and ids:
        return ids
    if corpus == "feed_posts" and any(records[eid].kind == "post_text" for eid in ids):
        return ids
    return []


async def _workspace_inventory(session, user_id) -> str:
    """Minimal landscape snapshot for the planner's first step (workspace-inventory §).

    NOT citable evidence — a transcript line, not a context block: the planner
    still has to ListPosts/OpenPost to ground anything. Its only job is to make
    the existence of posts/notes impossible to miss, so a recommend/"what's
    missing" question can't silently answer off the seed hits alone while whole
    categories sit unseen (chat 38e115df: recommended an already-drafted post
    because the seed matched only plan-notes and posts were never looked at).
    Counts only — no titles/previews — so it can't be mistaken for the content
    itself and tempt an answer without opening the real records.
    """
    from sqlalchemy import func, select

    from app.db.models import GlobalNote, Post

    posts = (await session.scalars(select(Post).where(Post.user_id == user_id))).all()
    by_status: dict[str, int] = {}
    local_notes = 0
    for row in posts:
        data = row.data if isinstance(row.data, dict) else {}
        status = str(data.get("status") or "draft").strip().lower()
        if status == "deleted":
            continue
        by_status[status] = by_status.get(status, 0) + 1
        # Notes attached to a post (data["notes"]) — the "по постам" source the
        # prompt (§ ListGlobalNotes) counts alongside global notes. Skipped for
        # deleted posts by the continue above: a note dies with its post, so it
        # must not inflate the landscape the planner reasons about.
        local_notes += len(data.get("notes") or [])
    total_posts = sum(by_status.values())
    global_notes = (
        await session.scalar(
            select(func.count()).select_from(GlobalNote).where(GlobalNote.user_id == user_id)
        )
    ) or 0
    total_notes = local_notes + global_notes
    if not total_posts and not total_notes:
        return ""
    status_str = ", ".join(f"{k}:{v}" for k, v in sorted(by_status.items())) or "—"
    return (
        f"[workspace] База знаний (инвентарь, не содержимое): "
        f"посты — {total_posts} ({status_str}); "
        f"заметки — {total_notes} (по постам: {local_notes}, глобальные: {global_notes}). "
        f"Это разведка нулевого уровня: чтобы использовать что-то — перечисли "
        f"(ListPosts/ListPostNotes/ListGlobalNotes) и открой нужное; "
        f"инвентарь не цитируемое evidence."
    )


async def research_seed_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    inp = _planner_inputs(config)
    seed_ref = inp["seed_ref"]
    seed_post_id = inp["seed_post_id"]
    contract = dict(inp.get("turn_contract") or state.get("turn_contract") or {})
    contract_target = dict(contract.get("target") or {})
    user_text = str(state.get("user_text") or "")
    transcript = list(state.get("research_transcript") or [])
    search_ledger = list(state.get("search_ledger") or [])
    async with ctx.session_factory() as session:
        agent_state = ctx.bind_agent_state(session)

        async def seed_action(action: ToolAction) -> ToolOutcome:
            nonlocal search_ledger
            outcome, search_ledger, _entry, _cached = await _execute_ledgered_tool(
                agent_state,
                action,
                ledger=search_ledger,
                contract=contract,
            )
            return outcome
        # Best-effort: the inventory is a decorative transcript line, not citable
        # evidence (see _workspace_inventory docstring). A DB error building it
        # must not abort the whole research run — degrade to no inventory.
        try:
            inventory = await _workspace_inventory(session, ctx.user_id)
        except Exception:
            inventory = ""
        if inventory:
            transcript.append(inventory)
        normalized_targets = list((contract.get("target_contract") or {}).get("targets") or [])
        for target in normalized_targets:
            target_id = str(target.get("id") or "").strip()
            if not target_id:
                continue
            if target.get("kind") == "note":
                outcome = await seed_action(
                    ToolAction(
                        tool="OpenNote",
                        args={
                            "note_id": target_id,
                            "post_id": str(target.get("parent_post_id") or "") or None,
                        },
                    )
                )
                transcript.append(f"[contract] OpenNote {target_id}: {outcome.summary}")
            elif target.get("kind") == "post":
                outcome = await seed_action(
                    ToolAction(tool="OpenPost", args={"post_id": target_id})
                )
                transcript.append(f"[contract] OpenPost {target_id}: {outcome.summary}")
        if (
            contract_target.get("kind") in {"recent_note", "ledger_note"}
            and contract_target.get("id")
            and not normalized_targets
        ):
            note_id = str(contract_target["id"])
            outcome = await seed_action(ToolAction(tool="OpenNote", args={"note_id": note_id}))
            transcript.append(
                f"[contract] authoritative recent note {note_id}: {outcome.summary}"
            )
        if contract.get("corpus") == "feed_posts":
            listing = await seed_action(
                ToolAction(tool="ListPosts", args={"status": "published", "limit": 8})
            )
            transcript.append(f"[contract] feed corpus: {listing.summary}")
            style_only = bool((contract.get("output") or {}).get("match_reference_style"))
            opened = 0
            for item in agent_state.catalog_posts:
                if str(item.get("status") or "") != "published":
                    continue
                text_value = str(item.get("text") or "").strip()
                if style_only and len(text_value) < 120:
                    continue
                outcome = await seed_action(
                    ToolAction(tool="OpenPost", args={"post_id": str(item.get("id") or "")})
                )
                transcript.append(f"[contract] feed OpenPost: {outcome.summary}")
                opened += 1
                if opened >= (4 if style_only else 8):
                    break
        if seed_ref and str(seed_ref).startswith("note:"):
            note_id = str(seed_ref)[len("note:") :].strip()
            outcome = await seed_action(
                ToolAction(tool="OpenNote", args={"note_id": note_id, "post_id": seed_post_id})
            )
            transcript.append(f"[seed] OpenNote: {outcome.summary}")
        if ctx.scope == "post":
            post_id = (
                str(seed_post_id or "").strip()
                or str((ctx.post_data or {}).get("id") or "").strip()
            )
            if post_id:
                outcome = await seed_action(ToolAction(tool="OpenPost", args={"post_id": post_id}))
                transcript.append(f"[seed] OpenPost: {outcome.summary}")
                agent_state.resolved_target_post_id = post_id
        seeded = seed_hydrated_attachments_from_ledger(
            agent_state,
            user_text=user_text,
            ledger=inp["dialog_ledger"],
        )
        if seeded:
            transcript.append(f"[seed] ledger attachments: {', '.join(seeded)}")
        # Semantic prefetch: surface relevant notes/posts as candidates BEFORE
        # the planner's first step, so it can't close the run on a guessed
        # meaning of a workspace term (e.g. "серия") without ever discovering
        # the note that defines it. Discovery-only — tool_search_nodes doesn't
        # write context_blocks, so hits are NOT citable evidence yet; the
        # planner must still OpenNote/OpenPost to ground them (agent note-prefetch).
        prefetch_hits: list[dict[str, Any]] = []
        search_query = str(state.get("search_query") or "").strip() or user_text
        if contract.get("corpus") in {"exact_note", "feed_posts"}:
            search_query = ""
        if search_query and inp.get("l1_results"):
            # retrieve_rag_for_reply already ran the canonical hybrid/vector
            # policy. Reuse those candidates instead of embedding/searching a
            # second time before the planner starts.
            for item in list(inp.get("l1_results") or ())[:8]:
                node_type = str(item.get("node_type") or "")
                object_id = str(item.get("note_id") or item.get("file_id") or "")
                prefix = (
                    "note" if node_type == "note_chunk"
                    else "post" if node_type == "post_text"
                    else "file"
                )
                if object_id:
                    prefetch_hits.append(
                        {
                            "ref": f"{prefix}:{object_id}",
                            "label": f"{prefix}:{object_id}",
                            "similarity": float(item.get("similarity") or 0.0),
                            "node_type": node_type,
                        }
                    )
            prefetch_action = ToolAction(tool="SearchNodes", args={"query": search_query})
            preparation = prepare_intent(
                search_ledger,
                tool=prefetch_action.tool,
                args=prefetch_action.args,
                contract=contract,
            )
            if preparation.execute:
                search_ledger = finish_intent(
                    preparation.ledger,
                    intent_key=str(preparation.entry.get("intent_key") or ""),
                    summary="[cache] L1/hybrid retrieval reused",
                    error=None,
                    hits=prefetch_hits,
                )
            transcript.append(f"[seed] reused L1/hybrid SearchNodes {search_query!r}")
        elif search_query:
            search_outcome = await seed_action(
                ToolAction(tool="SearchNodes", args={"query": search_query})
            )
            if search_outcome.hits:
                prefetch_hits = [dict(h) for h in search_outcome.hits]
                transcript.append(f"[seed] SearchNodes {search_query!r}:\n{search_outcome.summary}")
        records = records_from_agent_state(agent_state)
        await session.commit()
    return {
        **state,
        "research_transcript": transcript,
        "prefetch_hits": prefetch_hits,
        "search_ledger": search_ledger,
        "evidence_records": {key: rec.to_dict() for key, rec in records.items()},
        "step_count": 0,
        "repair_count": 0,
        "status": "running",
    }


async def research_planner_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    from app.services.agent.runtime.budget import call_llm_with_deadline

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    inp = _planner_inputs(config)
    spec = ctx.reasoner_spec
    model = ctx.reasoner_model
    api_key = ctx.reasoner_api_key
    max_steps = int(state.get("max_steps") or 4)
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    # None only in the reasoner-less branch (deterministic FinishRetrieval, never
    # an unparsed emission); the unparsed-output hint below keys off `parsed is
    # None` so it must exist for both branches.
    parsed: ToolAction | None = None
    contract = dict(inp.get("turn_contract") or state.get("turn_contract") or {})
    fast_finish_ids = _contract_fast_finish_ids(contract, records)
    if fast_finish_ids:
        action = ToolAction(
            tool="FinishRetrieval",
            args={"status": "ready", "evidence_ids": fast_finish_ids},
            answer_requires="; ".join(str(item) for item in contract.get("success_criteria") or []),
            plan=[],
        )
    elif spec is None or not model or not api_key:
        action = ToolAction(
            tool="FinishRetrieval",
            args={
                "status": "partial" if records else "ready",
                "evidence_ids": list(records),
                "unresolved": ["no_reasoner_llm"],
            },
        )
    else:
        ledger_text = (
            format_ledger_for_planner(inp["dialog_ledger"]) if inp["dialog_ledger"] else ""
        )
        messages = _build_messages(
            user_text=str(state.get("user_text") or ""),
            transcript=list(state.get("research_transcript") or []),
            hints=list(state.get("research_hints") or []),
            dialog_context=inp["dialog_context"],
            ledger_text=ledger_text,
            l1_summary=_l1_summary(inp["l1_results"]),
            turn_contract=inp["turn_contract"],
            plan_text=render_plan_for_planner(list(state.get("plan") or [])),
            search_ledger_text=render_search_ledger_for_planner(
                list(state.get("search_ledger") or [])
            ),
        )
        evidence_text = _format_evidence_for_planner(records)
        messages[-1]["content"] += "\n\nСобранный context:\n" + evidence_text
        raw = await call_llm_with_deadline(
            ctx,
            phase="research.planner",
            messages=messages,
            spec=spec,
            model=model,
            api_key=api_key,
            temperature=0.1,
            # 700 truncated the JSON mid-object once the re-emitted plan grew
            # (Cyrillic ≈2 tokens/char): the tail was cut, parse_tool_action
            # returned None → Invalid → a wasted round-trip that repeated until
            # the step budget drained. A full planner turn here is ~1k tokens;
            # 1500 leaves headroom so the object closes (agent-invalid-loop).
            max_tokens=1500,
        )
        parsed = parse_tool_action(raw)
        action = parsed or ToolAction(tool="Invalid", args={})
    validator_source = False
    if action.tool == "FinishRetrieval" and state.get("finish_retrieval_attempted"):
        # The first FinishRetrieval is a planner proposal. If its validator
        # rejects it, a later planner finish is converted into an internal
        # event; it is validated without another FinishRetrieval tool call.
        validator_source = True
        action = ToolAction(
            tool="ValidatorEvent",
            args={**action.args, "validator_source": "finish_repair"},
            observations=action.observations,
            reasoning=action.reasoning,
            answer_requires=action.answer_requires,
            gap=action.gap,
            plan=action.plan,
        )
    steps = int(state.get("step_count") or 0) + 1
    trace_step("7. rag.L2.langgraph", [f"step={steps}/{max_steps}", f"tool={action.tool}"])
    fabricated = validate_observations(
        action.observations,
        transcript=list(state.get("research_transcript") or []),
        records=records,
    )
    hints = list(state.get("research_hints") or [])
    # Parse failure (no JSON / no tool key) yields Invalid. Without a corrective
    # hint the planner re-runs on the same context and fails identically, looping
    # until the budget drains. One explicit "return strict JSON" hint lets a
    # single bad emission self-correct next step (agent-invalid-loop).
    if parsed is None and action.tool == "Invalid":
        hints.append(
            "repair: unparsed_output — предыдущий ответ не распарсился как JSON "
            "(вероятно оборван). Верни РОВНО один компактный JSON-объект по схеме, "
            "без markdown-обёртки и пояснений; сократи observations/reasoning, "
            "если ответ длинный."
        )
    if fabricated:
        hints.append(f"repair: cosmetic_observations:{'; '.join(fabricated)}")
    # Merge the re-emitted plan onto the persisted one, enforcing the
    # no-silent-drop invariant. Any refused transition (done without evidence,
    # drop without reason, silent omission) comes back as a repair hint so the
    # planner sees it next step (persistent-plan).
    merged_plan, plan_hints = merge_plan(
        list(state.get("plan") or []),
        action.plan,
        evidence_ids=frozenset(records),
    )
    for hint in plan_hints:
        hints.append(f"repair: {hint}")
    step_record: dict[str, Any] = {
        "step": steps,
        "observations": list(action.observations),
        "reasoning": action.reasoning,
        "answer_requires": action.answer_requires,
        "gap": action.gap,
        "tool": action.tool,
        "args": action.args,
        "plan": merged_plan,
    }
    if fabricated:
        step_record["repair_hint"] = f"cosmetic_observations:{'; '.join(fabricated)}"
    if validator_source:
        step_record["validator_source"] = "finish_repair"
    return {
        **state,
        "step_count": steps,
        "plan": merged_plan,
        "tool_action": {
            "tool": action.tool,
            "args": action.args,
            "observations": list(action.observations),
            "reasoning": action.reasoning,
            "gap": action.gap,
        },
        "research_hints": hints,
        "planner_steps": [*(state.get("planner_steps") or []), step_record],
    }


async def research_tool_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    raw_action = state.get("tool_action") or {}
    action = ToolAction(
        tool=str(raw_action.get("tool") or ""),
        args=dict(raw_action.get("args") or {}),
        gap=str(raw_action.get("gap") or ""),
    )
    transcript = list(state.get("research_transcript") or [])
    existing_records = dict(state.get("evidence_records") or {})
    contract = dict(
        state.get("turn_contract")
        or ((config or {}).get("configurable", {}) or {}).get("turn_contract")
        or {}
    )
    search_ledger = list(state.get("search_ledger") or [])
    async with ctx.session_factory() as session:
        agent_state = ctx.bind_agent_state(session)
        outcome, search_ledger, ledger_entry, cached = await _execute_ledgered_tool(
            agent_state,
            action,
            ledger=search_ledger,
            contract=contract,
        )
        records = records_from_agent_state(agent_state)
        await session.commit()
    step = int(state.get("step_count", 0) or 0)
    signature = str(ledger_entry.get("signature") or json.dumps(
        {"tool": action.tool, "args": action.args},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    previous_outcomes = list(state.get("tool_outcomes") or [])
    repeated = any(
        str(item.get("signature") or "") == signature
        for item in previous_outcomes[-3:]
    )
    new_record_ids = sorted(set(records) - set(existing_records))
    made_progress = not cached and bool(new_record_ids or outcome.hits)
    no_progress_count = 0 if made_progress else int(state.get("no_progress_count") or 0) + 1
    # Refund the step consumed by the planner when the tool only returned
    # recoverable precondition guidance (e.g. "сначала OpenPost"), capped at
    # MAX_STEP_REFUNDS so a repeating broken call can't loop for free. The
    # planner still gets its retry; it just doesn't pay for the mis-ordered call.
    refunds = int(state.get("step_refunds") or 0)
    if (
        outcome.error in REFUNDABLE_TOOL_ERRORS
        and refunds < MAX_STEP_REFUNDS
        and step > 0
        and not repeated
    ):
        step -= 1
        refunds += 1
        transcript.append(f"  refund: step not charged ({outcome.error})")
    transcript.append(f"step {step}: {action.tool} → {outcome.summary}")
    if outcome.error:
        transcript.append(f"  error={outcome.error}")
    # Structured, first-class record of what the tool returned — emitted as a
    # `tool_result` event by the executor (Спринт 5). record_ids lists the
    # citation paths this tool call added to evidence, so the log ties a tool
    # outcome to the evidence it produced.
    outcome_record = {
        "step": step,
        "tool": action.tool,
        "args": action.args,
        "summary": outcome.summary[:500],
        "error": outcome.error,
        "record_ids": sorted(str(key) for key in records),
        "new_record_ids": new_record_ids,
        "signature": signature,
        "intent_key": ledger_entry.get("intent_key"),
        "source_requirement_id": ledger_entry.get("source_requirement_id"),
        "intent_state": ledger_entry.get("state"),
        "exhausted_reason": ledger_entry.get("exhausted_reason"),
        "cached": cached,
        "no_progress_count": no_progress_count,
    }
    return {
        **state,
        "step_count": step,
        "step_refunds": refunds,
        "no_progress_count": no_progress_count,
        "research_transcript": transcript,
        "tool_outcomes": [*(state.get("tool_outcomes") or []), outcome_record],
        "search_ledger": search_ledger,
        "evidence_records": {
            **existing_records,
            **{key: rec.to_dict() for key, rec in records.items()},
        },
    }


async def research_verify_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    # Do NOT auto-fill evidence_ids with every record — an empty list is a
    # verification failure that triggers repair, not a licence to "cite
    # everything" (agent-runtime-sprints §1.3). The model must choose its cites.
    tool_name = str((state.get("tool_action") or {}).get("tool") or "")
    candidate = dict((state.get("tool_action") or {}).get("args") or {})
    validator_event = tool_name == "ValidatorEvent"
    if tool_name == "FinishRetrieval" and not state.get("finish_retrieval_attempted"):
        state = {**state, "finish_retrieval_attempted": True}
    # Budget-exhaustion salvage: verify is reachable two ways — the planner chose
    # FinishRetrieval, or the step budget ran out mid-exploration (route_* forces
    # verify). In the latter case `candidate` is the last read-tool's args (e.g.
    # {post_id: ...}) with no evidence_ids, so the pack would be empty and the
    # answer a false "нет данных" — even though listing tools already recorded
    # citable facts. When we land here on anything other than an explicit
    # FinishRetrieval, synthesize a `partial` finish over the non-empty records
    # collected so far. This is NOT "cite everything" (§1.3): it fires only when
    # the planner never got its turn to finish, salvaging gathered evidence
    # instead of discarding it.
    if tool_name not in {"FinishRetrieval", "ValidatorEvent"} and records:
        salvaged_ids = [rid for rid, rec in records.items() if rec.content.strip()]
        if salvaged_ids:
            candidate = {
                "status": "partial",
                "evidence_ids": salvaged_ids,
                "unresolved": [
                    "no_progress_guard"
                    if int(state.get("no_progress_count") or 0) >= 2
                    else "step_budget_exhausted"
                ],
            }
    # Finish-gate (persistent-plan): an explicit FinishRetrieval is refused while
    # plan items are still `open` — the planner must act on them or close them
    # (done/dropped) first. Only fires with budget remaining and under the repair
    # cap; budget exhaustion routes here with tool != FinishRetrieval and is
    # salvaged above, so a starved run still terminates. This is where a dropped
    # intent ("проверить global notes") is forced back into an action.
    still_open = open_items(list(state.get("plan") or []))
    plan_repairs = int(state.get("plan_repair_count") or 0)
    budget_exhausted = int(state.get("step_count") or 0) >= int(state.get("max_steps") or 4)
    if (
        tool_name == "FinishRetrieval"
        and still_open
        and not budget_exhausted
        and plan_repairs < MAX_PLAN_REPAIRS
    ):
        pending = "; ".join(str(it.get("text")) for it in still_open)
        return {
            **state,
            "plan_repair_count": plan_repairs + 1,
            "research_hints": [
                *(state.get("research_hints") or []),
                f"repair: unfinished_plan_items — закрой или выполни: {pending}",
            ],
            "verification_ok": False,
        }
    # Prefetch finish-gate (agent note-prefetch): refuse an explicit finish while
    # the seed surfaced a relevant note/post that was never opened into evidence —
    # the "guessed the meaning of a workspace term instead of reading the note
    # that defines it" failure. Bounded by MAX_PREFETCH_REPAIRS and skipped on
    # budget exhaustion, so a planner that legitimately shouldn't open the hit
    # still terminates.
    prefetch_repairs = int(state.get("prefetch_repair_count") or 0)
    if (
        tool_name == "FinishRetrieval"
        and not budget_exhausted
        and prefetch_repairs < MAX_PREFETCH_REPAIRS
    ):
        missed = unopened_prefetch_hits(list(state.get("prefetch_hits") or []), records)
        if missed:
            names = "; ".join(str(h.get("label")) for h in missed)
            return {
                **state,
                "prefetch_repair_count": prefetch_repairs + 1,
                "research_hints": [
                    *(state.get("research_hints") or []),
                    "repair: unopened_prefetch — открой релевантный кандидат из поиска "
                    f"через OpenNote/OpenPost прежде чем завершать: {names}",
                ],
                "verification_ok": False,
            }
    if validator_event:
        # Validator events are terminal for control flow, but they must still
        # disclose obligations that the first finish tried to skip.
        validator_gaps: list[str] = []
        if still_open:
            validator_gaps.append(
                "unfinished_plan_items:" + ", ".join(str(item.get("text")) for item in still_open)
            )
        missed = unopened_prefetch_hits(list(state.get("prefetch_hits") or []), records)
        if missed:
            validator_gaps.append(
                "unopened_prefetch:" + ", ".join(str(item.get("label")) for item in missed)
            )
        if validator_gaps:
            candidate = {
                **candidate,
                "status": "partial",
                "unresolved": [*(candidate.get("unresolved") or []), *validator_gaps],
            }
    # Fuzzy-repair truncated UUID paths (chat 9f3d5fdf): the planner sometimes
    # drops the last 4–8 chars of a UUID segment when constructing evidence_ids
    # in FinishRetrieval — e.g. "…3db81d/attachment/…" instead of the full
    # "…3db81d9b4a7f/attachment/…". The tool summary now includes the canonical
    # "[id: ...]" path so the planner can copy it verbatim; this repair is a
    # defensive backstop for when it still truncates.
    # Repair: replace each evidence_id that doesn't resolve to a real record with
    # the longest real-record path that starts with a prefix of the bad id
    # (up to the first truncation point).
    raw_ids: list[str] = list(candidate.get("evidence_ids") or [])
    if raw_ids and records:
        repaired: list[str] = []
        changed = False
        for eid in raw_ids:
            if eid in records:
                repaired.append(eid)
                continue
            # Find the longest real record key that has a common prefix with eid.
            best: str | None = None
            best_len = 0
            for real_key in records:
                # Check if eid is a truncated prefix of real_key, or vice-versa.
                shorter, longer = (eid, real_key) if len(eid) <= len(real_key) else (real_key, eid)
                common = 0
                for a, b in zip(shorter, longer):
                    if a == b:
                        common += 1
                    else:
                        break
                # Require at least 20 chars of common prefix (enough to confirm
                # same note/file, not just coincidentally similar paths).
                if common >= 20 and common > best_len:
                    best = real_key
                    best_len = common
            if best is not None:
                repaired.append(best)
                changed = True
            else:
                repaired.append(eid)
        if changed:
            candidate = {**candidate, "evidence_ids": repaired}

    contract = dict(
        state.get("turn_contract")
        or ((config or {}).get("configurable", {}) or {}).get("turn_contract")
        or {}
    )
    if contract.get("target_contract") or contract.get("corpus") in {"feed_posts", "exact_note"}:
        allowed_ids = set(_contract_evidence_ids(contract, records))
        candidate = {
            **candidate,
            "evidence_ids": [
                str(eid)
                for eid in (candidate.get("evidence_ids") or [])
                if str(eid) in allowed_ids
            ],
        }

    candidate_records = {
        str(eid): records[str(eid)].to_dict()
        for eid in (candidate.get("evidence_ids") or [])
        if str(eid) in records
    }
    required_gaps = missing_required_sources(
        contract,
        covered_source_ids(contract, candidate_records),
    )
    if required_gaps and tool_name == "FinishRetrieval":
        gap_text = ", ".join(required_gaps)
        if int(state.get("repair_count") or 0) < 1 and not budget_exhausted:
            return {
                **state,
                "repair_count": int(state.get("repair_count") or 0) + 1,
                "research_hints": [
                    *(state.get("research_hints") or []),
                    f"repair: required_source_gap — собери evidence для: {gap_text}",
                ],
                "verification_ok": False,
            }
        candidate = {
            **candidate,
            "status": "partial",
            "unresolved": [*(candidate.get("unresolved") or []), f"required_source_gap:{gap_text}"],
        }
    elif required_gaps and validator_event:
        gap_text = ", ".join(required_gaps)
        candidate = {
            **candidate,
            "status": "partial",
            "unresolved": [
                *(candidate.get("unresolved") or []),
                f"required_source_gap:{gap_text}",
            ],
        }

    verdict = verify_evidence(
        finish=candidate,
        records=records,
        repair_count=int(state.get("repair_count") or 0),
    )
    if validator_event and not verdict.ok:
        # A second planner finish is an internal validator event, never another
        # FinishRetrieval repair loop. Preserve grounded records and expose the
        # exact validator errors to the answer as unresolved gaps.
        fallback_ids = [rid for rid, rec in records.items() if rec.content.strip()]
        candidate = {
            "status": "partial",
            "evidence_ids": fallback_ids,
            "unresolved": [
                *(candidate.get("unresolved") or []),
                *[str(error) for error in verdict.errors],
                "validator_event_exhausted",
            ],
        }
        return {
            **state,
            "finish_retrieval": candidate,
            "verification_ok": True,
            "validator_events": [
                *(state.get("validator_events") or []),
                {"kind": "finish_repair", "errors": list(verdict.errors)},
            ],
        }
    if verdict.ok or not verdict.repair_allowed:
        result = {**state, "finish_retrieval": candidate, "verification_ok": True}
        if validator_event:
            result["validator_events"] = [
                *(state.get("validator_events") or []),
                {"kind": "finish_repair", "errors": []},
            ]
        return result
    return {
        **state,
        "repair_count": int(state.get("repair_count") or 0) + 1,
        "research_hints": [
            *(state.get("research_hints") or []),
            f"repair: {', '.join(verdict.errors)}",
        ],
        "verification_ok": False,
    }


async def research_pack_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    # Honour the verified finish literally — no "cite everything" fallback.
    # An empty selection yields an empty pack, which the answer guard turns
    # into an honest refusal rather than ungrounded text (agent-runtime-sprints §1.3).
    finish = dict(state.get("finish_retrieval") or {})
    evidence_ids = [str(item) for item in (finish.get("evidence_ids") or [])]
    contract = dict(
        state.get("turn_contract")
        or ((config or {}).get("configurable", {}) or {}).get("turn_contract")
        or {}
    )
    if contract.get("target_contract") or contract.get("corpus") in {"feed_posts", "exact_note"}:
        allowed_ids = set(_contract_evidence_ids(contract, records))
        evidence_ids = [eid for eid in evidence_ids if eid in allowed_ids]
    unresolved_items = [str(item) for item in (finish.get("unresolved") or [])]
    packed, cites = build_evidence_pack(
        records=records,
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
    )
    return {
        **state,
        "rag_context": packed,
        "evidence_ids": evidence_ids,
        "evidence_titles": [cite.title for cite in cites],
        "unresolved": unresolved_items,
        "stopped_reason": str(finish.get("status") or "ready"),
        "status": "completed",
    }


def route_research_plan(state: AgentGraphState) -> Literal["planner", "tool", "verify"]:
    action = state.get("tool_action") or {}
    tool = str(action.get("tool") or "")
    if tool in {"FinishRetrieval", "ValidatorEvent"}:
        return "verify"
    # Hard-stop on step budget still routes through verify, never straight to
    # pack — the collected evidence must clear the gate before it can ground an
    # answer (agent-runtime-sprints §1.3).
    if int(state.get("step_count") or 0) >= int(state.get("max_steps") or 4):
        return "verify"
    return "tool" if tool in READ_TOOLS else "planner"


def route_research_after_tool(state: AgentGraphState) -> Literal["planner", "verify"]:
    return (
        "verify"
        if (
            int(state.get("step_count") or 0) >= int(state.get("max_steps") or 4)
            or int(state.get("no_progress_count") or 0) >= 2
        )
        else "planner"
    )


def route_research_verify(state: AgentGraphState) -> Literal["planner", "pack"]:
    return "pack" if state.get("verification_ok") else "planner"


def build_research_graph() -> StateGraph:
    """Assemble the research loop from the shared module-level nodes.

    Single source of truth: the same nodes power both this standalone graph
    (legacy run_research_graph / contract tests) and the unified workspace
    graph (agent-runtime-sprints §1.0), so behaviour cannot drift between the two paths.
    """
    graph = StateGraph(AgentGraphState)
    graph.add_node("seed", research_seed_node)
    graph.add_node("planner", research_planner_node)
    graph.add_node("tool", research_tool_node)
    graph.add_node("verify", research_verify_node)
    graph.add_node("pack", research_pack_node)
    graph.set_entry_point("seed")
    graph.add_edge("seed", "planner")
    graph.add_conditional_edges("planner", route_research_plan)
    graph.add_conditional_edges("tool", route_research_after_tool)
    graph.add_conditional_edges("verify", route_research_verify)
    graph.add_edge("pack", END)
    return graph


async def run_research_graph(
    ctx: RuntimeContext,
    *,
    user_text: str,
    seed_ref: str | None = None,
    seed_post_id: str | None = None,
    hints: list[str] | None = None,
    dialog_context: str = "",
    dialog_ledger: tuple[TurnSnapshot, ...] = (),
    l1_results: list[dict[str, Any]] | None = None,
    max_steps: int = 4,
    spec: ProviderSpec | None = None,
    model: str = "",
    api_key: str = "",
    checkpoint_id: str | None = None,
) -> ResearchResult:
    """Run the durable, bounded evidence research state machine."""
    from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready, get_checkpointer

    research_hints = list(hints or [])

    graph = build_research_graph()
    await ensure_checkpointer_ready()
    compiled = graph.compile(checkpointer=get_checkpointer())
    config = {
        "configurable": {
            "thread_id": str(ctx.user_id),
            "checkpoint_ns": f"research:{checkpoint_id or uuid.uuid4()}",
            "runtime_context": ctx,
            "dialog_context": dialog_context,
            "dialog_ledger": dialog_ledger,
            "l1_results": l1_results,
            "seed_ref": seed_ref,
            "seed_post_id": seed_post_id,
            "turn_contract": dict(ctx.turn_contract or {}),
        }
    }
    initial: AgentGraphState = {
        "user_text": user_text,
        "scope": ctx.scope,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "repair_count": 0,
        "step_count": 0,
        "max_steps": max_steps,
        "no_progress_count": 0,
        "research_transcript": [],
        "research_hints": research_hints,
        "turn_contract": dict(ctx.turn_contract or {}),
        "search_ledger": [],
        "finish_retrieval_attempted": False,
        "validator_events": [],
    }
    final_state = initial
    async for value in compiled.astream(initial, config, stream_mode="values"):
        final_state = value
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (final_state.get("evidence_records") or {}).items()
    }
    evidence_ids = list(final_state.get("evidence_ids") or [])
    unresolved_items = list(final_state.get("unresolved") or [])
    rag_context, cites = build_evidence_pack(
        records=records,
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
    )
    return ResearchResult(
        rag_context=rag_context,
        cites=cites,
        stopped_reason=str(final_state.get("stopped_reason") or "ready"),
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
        step_count=int(final_state.get("step_count") or 0),
    )


def build_research_subgraph() -> StateGraph:
    """Build a serializable pack-only graph for isolated contract tests."""

    async def bootstrap(state: AgentGraphState) -> AgentGraphState:
        return {**state, "status": "running", "step_count": 0}

    async def pack_node(state: AgentGraphState) -> AgentGraphState:
        records = {
            k: EvidenceRecord.from_dict(v)
            for k, v in (state.get("evidence_records") or {}).items()
        }
        ids = state.get("evidence_ids") or list(records.keys())
        ctx, _cites = build_evidence_pack(records=records, evidence_ids=ids)
        return {**state, "rag_context": ctx, "status": "completed"}

    graph = StateGraph(AgentGraphState)
    graph.add_node("bootstrap", bootstrap)
    graph.add_node("pack", pack_node)
    graph.set_entry_point("bootstrap")
    graph.add_edge("bootstrap", "pack")
    graph.add_edge("pack", END)
    return graph
