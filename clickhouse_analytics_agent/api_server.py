"""
FastAPI server for ClickHouse Analytics Agent.
Endpoints:
  GET  /                              health check
  GET  /health                        health check (for monitoring)
  GET  /api/info                      service info
  POST /api/session/new               create a new conversation session
  GET  /api/session/{session_id}      get session metadata
  POST /api/analyze                   submit query → returns job_id immediately
  GET  /api/job/{job_id}              poll job status / get result
  GET  /api/chat-stats                database statistics
Architecture change: async job queue.
  - POST /api/analyze starts the agent in background, returns job_id instantly.
  - GET  /api/job/{job_id} returns status: "pending" | "running" | "done" | "error"
  - Results are kept in memory for 2 hours (JOB_TTL_SECONDS).
  - Client reconnecting after disconnect can still fetch the result.
"""
import asyncio
import decimal as _decimal
import json
import math as _math
import uuid
from datetime import date as _date, datetime, timezone
_datetime = datetime  # alias for _serialize_value
from typing import Optional, Literal
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
load_dotenv()
from config import ALLOWED_MODELS, HOST, MODEL, PORT, SERVER_URL
# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ClickHouse Analytics Agent API",
    description=(
        "AI-powered advertising analytics agent. "
        "Queries ClickHouse, analyzes data with Python, returns charts & tables."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ─── Job store ────────────────────────────────────────────────────────────────
# job_id → JobRecord dict
# Хранится в памяти; при рестарте сервера задачи теряются (это приемлемо).
JOB_TTL_SECONDS = 7200  # 2 часа
JobStatus = Literal["pending", "running", "done", "error"]
_jobs: dict[str, dict] = {}
def _new_job(session_id: str, query: str, model: Optional[str] = None) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "session_id": session_id,
        "query": query,
        "model": model,   # None → default model
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "finished_at": None,
        "result": None,   # AnalyzeResponse dict when done
        "error": None,
    }
    return job_id
def _set_running(job_id: str) -> None:
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
def _set_done(job_id: str, result: dict) -> None:
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
    _jobs[job_id]["result"] = result
def _set_error(job_id: str, error: str) -> None:
    _jobs[job_id]["status"] = "error"
    _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
    _jobs[job_id]["error"] = error
# ─── Request / Response models ────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    model: Optional[str] = None  # None → default model from config
class SubmitResponse(BaseModel):
    """Returned immediately after POST /api/analyze."""
    job_id: str
    session_id: str
    status: str   # always "pending"
    message: str
class JobStatusResponse(BaseModel):
    """Returned by GET /api/job/{job_id}."""
    job_id: str
    session_id: str
    status: JobStatus
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    # Present only when status == "done"
    success: Optional[bool] = None
    text_output: Optional[str] = None
    plots: Optional[list[str]] = None
    tool_calls: Optional[list[dict]] = None
    error: Optional[str] = None
# ─── Background worker ────────────────────────────────────────────────────────
async def _run_agent_job(job_id: str) -> None:
    """Run the agent in a thread pool and store the result in _jobs."""
    job = _jobs.get(job_id)
    if not job:
        return
    _set_running(job_id)
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        from agent import get_agent
        agent = get_agent(job.get("model"))
        result = await asyncio.to_thread(
            agent.analyze,
            user_query=job["query"],
            session_id=job["session_id"],
        )
        _set_done(job_id, result)

        # ── Passive observability logging ──────────────────────────────────
        # Agent is already done and result is stored. Logger runs in a
        # daemon thread — any failure is silently swallowed, never affects agent.
        try:
            import threading as _threading
            from chat_logger import get_logger
            from config import DB_PATH
            logger = get_logger(DB_PATH)

            msgs = result.get("_messages", [])
            if msgs:
                _threading.Thread(
                    target=logger.log_turn,
                    args=(job["session_id"], msgs, started_at),
                    daemon=False,
                ).start()

            # Log router result (which skills Haiku selected for this turn)
            active_skills = result.get("_active_skills", [])
            from langchain_core.messages import HumanMessage as _HM
            turn_index = sum(1 for m in msgs if isinstance(m, _HM))
            _threading.Thread(
                target=logger.log_router,
                args=(job["session_id"], turn_index, active_skills,
                      job.get("query", ""), started_at),
                daemon=False,
            ).start()
        except Exception as log_exc:
            print(f"[ChatLogger] init error (non-fatal): {log_exc}")

    except Exception as exc:
        _set_error(job_id, str(exc))
        print(f"[job:{job_id}] ERROR: {exc}")
# ─── Cleanup loop ─────────────────────────────────────────────────────────────
async def _cleanup_loop() -> None:
    """Remove expired jobs and parquet files every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        now = datetime.now(timezone.utc).timestamp()
        # Clean expired jobs
        expired = [
            jid for jid, j in list(_jobs.items())
            if j["status"] in ("done", "error")
            and j["finished_at"]
            and (now - datetime.fromisoformat(j["finished_at"]).timestamp()) > JOB_TTL_SECONDS
        ]
        for jid in expired:
            del _jobs[jid]
        if expired:
            print(f"[cleanup] Removed {len(expired)} expired job(s)")
        # Clean parquet files
        try:
            from agent import get_agent
            n = await asyncio.to_thread(get_agent().cleanup_temp_files)
            if n:
                print(f"[cleanup] Removed {n} expired parquet file(s)")
        except Exception as exc:
            print(f"[cleanup] Parquet cleanup error: {exc}")
# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    from agent import get_agent
    get_agent()  # warm up: connect to ClickHouse
    asyncio.create_task(_cleanup_loop())
    print(f"✅ ClickHouse Analytics Agent API v2 started | {SERVER_URL}")
# ─── Health / Info ─────────────────────────────────────────────────────────────
@app.get("/", summary="Health check")
async def root():
    return {"status": "online", "service": "ClickHouse Analytics Agent", "version": "2.0.0"}
@app.get("/health", summary="Health check for uptime monitors")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
@app.get("/api/info", summary="Service features")
async def info():
    return {
        "service": "ClickHouse Analytics Agent",
        "version": "2.0.0",
        "architecture": "async job queue",
        "endpoints": {
            "submit": "POST /api/analyze",
            "poll":   "GET  /api/job/{job_id}",
        },
    }
@app.get("/api/models", summary="List available LLM models")
async def list_models():
    """
    Returns all models the user can choose from.
    Pass the `id` value in the `model` field of POST /api/analyze
    or POST /api/segment/chat.
    """
    return {
        "default": MODEL,
        "models": [
            {"id": model_id, "provider": provider}
            for model_id, provider in ALLOWED_MODELS.items()
        ],
    }
# ─── Session endpoints ─────────────────────────────────────────────────────────
@app.post("/api/session/new", summary="Create a new conversation session")
async def new_session():
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": "New session created",
    }
@app.get("/api/session/{session_id}", summary="Get session metadata")
async def get_session(session_id: str):
    # Count pending/running jobs for this session
    active = [j for j in _jobs.values() if j["session_id"] == session_id and j["status"] in ("pending", "running")]
    return {
        "session_id": session_id,
        "active_jobs": len(active),
    }
# ─── Main: submit query ────────────────────────────────────────────────────────
@app.post("/api/analyze", response_model=SubmitResponse, summary="Submit an analytics query")
async def analyze(req: AnalyzeRequest):
    """
    Submit a query to the agent.
    Returns job_id immediately — agent runs in background.
    Poll GET /api/job/{job_id} to get the result.

    Optional `model` field selects the LLM. See GET /api/models for allowed values.
    """
    if req.model and req.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{req.model}'. Allowed: {list(ALLOWED_MODELS.keys())}",
        )
    session_id = req.session_id or str(uuid.uuid4())
    job_id = _new_job(session_id=session_id, query=req.query, model=req.model)
    # Fire and forget
    asyncio.create_task(_run_agent_job(job_id))
    return SubmitResponse(
        job_id=job_id,
        session_id=session_id,
        status="pending",
        message="Query accepted. Poll GET /api/job/{job_id} for result.",
    )
# ─── Poll job status ───────────────────────────────────────────────────────────
@app.get("/api/job/{job_id}", response_model=JobStatusResponse, summary="Poll job status / get result")
async def get_job(job_id: str):
    """
    Poll the status of a submitted job.
    status: "pending" | "running" | "done" | "error"
    When status == "done", text_output, plots, tool_calls are populated.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found (may have expired)")
    resp = JobStatusResponse(
        job_id=job["job_id"],
        session_id=job["session_id"],
        status=job["status"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        finished_at=job["finished_at"],
        error=job["error"],
    )
    if job["status"] == "done" and job["result"]:
        r = job["result"]
        resp.success = r.get("success", True)
        resp.text_output = r.get("text_output", "")
        resp.plots = r.get("plots", [])
        resp.tool_calls = r.get("tool_calls", [])
        resp.error = r.get("error")
    return resp
# ─── Stats ────────────────────────────────────────────────────────────────────
@app.get("/api/chat-stats", summary="Database statistics")
async def chat_stats():
    total = len(_jobs)
    by_status = {}
    for j in _jobs.values():
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1
    return {"total_jobs_in_memory": total, "by_status": by_status}
# ─── Observability / Debug endpoints ─────────────────────────────────────────
# These endpoints are for developer use only (agent optimization analysis).
# They are NOT intended for the end-user frontend.

@app.get("/debug/sessions", tags=["debug"], summary="List all logged sessions")
async def debug_sessions():
    """
    List all sessions with aggregated stats:
    turns, total tool calls, estimated token usage, first/last activity.
    """
    try:
        from chat_logger import get_logger
        from config import DB_PATH
        return {"sessions": get_logger(DB_PATH).get_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/session/{session_id}", tags=["debug"], summary="Full session log with tool calls")
async def debug_session_logs(session_id: str):
    """
    Full chronological log of a session grouped by turn.

    Each turn contains events in order:
      human       → user question
      ai_thinking → agent reasoning before tool use (if any)
      tool_call   → tool invocation with full args (SQL, Python code, etc.)
      tool_result → full tool response (row_count, data stats, analysis output)
      ai_answer   → final agent response shown to user

    Useful for: reviewing what SQL the agent wrote, how many iterations it took,
    whether it used the right tables, whether tool results were large/expensive.
    """
    try:
        from chat_logger import get_logger
        from config import DB_PATH
        logs = get_logger(DB_PATH).get_session_logs(session_id)
        if not logs:
            raise HTTPException(status_code=404, detail="Session not found or not yet logged")

        # Group by turn_index, parse JSON content for readability
        turns: dict[int, list] = {}
        for row in logs:
            if row.get("content"):
                try:
                    row["content"] = json.loads(row["content"])
                except Exception:
                    pass  # leave as plain string if not JSON
            turns.setdefault(row["turn_index"], []).append(row)

        return {
            "session_id": session_id,
            "total_turns": len(turns),
            "turns": [
                {"turn_index": idx, "events": events}
                for idx, events in sorted(turns.items())
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/session/{session_id}/turn/{turn_index}", tags=["debug"], summary="Log for one specific turn")
async def debug_turn_logs(session_id: str, turn_index: int):
    """
    Detailed event log for a single turn within a session.
    Useful for deep-diving into one specific question the user asked.
    """
    try:
        from chat_logger import get_logger
        from config import DB_PATH
        events = get_logger(DB_PATH).get_turn(session_id, turn_index)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"Turn {turn_index} not found for session {session_id}"
            )
        # Parse JSON content fields
        for ev in events:
            if ev.get("content"):
                try:
                    ev["content"] = json.loads(ev["content"])
                except Exception:
                    pass
        return {"session_id": session_id, "turn_index": turn_index, "events": events}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/stats", tags=["debug"], summary="Aggregate optimization stats")
async def debug_stats():
    """
    Aggregate statistics across all logged sessions.

    Key metrics for optimization analysis:
      - list_tables_calls: should be ~0 (schema is in system prompt)
      - avg_ch_result_tokens: if high → agent fetching too much data
      - tool_calls_total / human_turns: avg tool calls per user question
    """
    try:
        from chat_logger import get_logger
        from config import DB_PATH
        return get_logger(DB_PATH).get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Segment Builder endpoints ────────────────────────────────────────────────

class SegmentChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None  # None → default model from config


class SegmentChatResponse(BaseModel):
    success: bool
    session_id: str
    text_output: str
    segment_saved: bool
    error: Optional[str] = None


@app.post(
    "/api/segment/chat",
    response_model=SegmentChatResponse,
    tags=["segmentation"],
    summary="One turn in a segmentation dialogue",
)
async def segment_chat(
    req: SegmentChatRequest,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """
    Диалог с агентом-сегментатором (synchronous — ответ возвращается сразу).

    Сохраняй `session_id` между вызовами чтобы держать контекст диалога.
    Если `session_id` не передан — создаётся новая сессия.
    Флаг `segment_saved: true` означает что сегмент был сохранён в этом ходу.

    Заголовок `X-User-Id` (опционально): изолирует сегменты по пользователю.
    Без заголовка — сегменты попадают в общее пространство "__shared__".
    """
    if req.model and req.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{req.model}'. Allowed: {list(ALLOWED_MODELS.keys())}",
        )
    from segment_agent import get_segment_agent
    from segment_store import _SHARED_OWNER
    owner = x_user_id or _SHARED_OWNER
    session_id = req.session_id or str(uuid.uuid4())
    agent = get_segment_agent(req.model)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, agent.chat, req.message, session_id, owner)
    return SegmentChatResponse(
        success=result["success"],
        session_id=session_id,
        text_output=result.get("text_output", ""),
        segment_saved=result.get("segment_saved", False),
        error=result.get("error"),
    )


@app.get(
    "/api/segment/chat/{session_id}/history",
    tags=["segmentation"],
    summary="Get segmentation dialogue history",
)
async def get_segment_chat_history(session_id: str):
    """История диалога сессии сегментации в формате [{role, content}]."""
    from segment_agent import get_segment_agent
    agent = get_segment_agent()
    loop = asyncio.get_event_loop()
    history = await loop.run_in_executor(None, agent.get_session_history, session_id)
    return {"session_id": session_id, "history": history}


@app.get(
    "/api/segments",
    tags=["segmentation"],
    summary="List all saved segments",
)
async def list_segments(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """Список сегментов текущего пользователя (X-User-Id), отсортированных по дате обновления."""
    from segment_store import _SHARED_OWNER, get_segment_store
    owner = x_user_id or _SHARED_OWNER
    store = get_segment_store()
    loop = asyncio.get_event_loop()
    segments = await loop.run_in_executor(None, store.list_all, owner)
    return {"segments": segments}


@app.get(
    "/api/segments/{segment_id}",
    tags=["segmentation"],
    summary="Get segment by ID",
)
async def get_segment(
    segment_id: str,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """Получить сегмент по ID. Возвращает 404 если сегмент не найден или принадлежит другому пользователю."""
    from segment_store import _SHARED_OWNER, get_segment_store
    owner = x_user_id or _SHARED_OWNER
    store = get_segment_store()
    loop = asyncio.get_event_loop()
    seg = await loop.run_in_executor(None, store.get_by_id, segment_id, owner)
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")
    return seg


@app.delete(
    "/api/segments/{segment_id}",
    tags=["segmentation"],
    summary="Delete segment by ID",
)
async def delete_segment(
    segment_id: str,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    """Удалить сегмент. Возвращает 404 если сегмент не найден или принадлежит другому пользователю."""
    from segment_store import _SHARED_OWNER, get_segment_store
    owner = x_user_id or _SHARED_OWNER
    store = get_segment_store()
    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(None, store.delete, segment_id, owner)
    if not deleted:
        raise HTTPException(status_code=404, detail="Segment not found")
    return {"success": True}


# ─── Tables: named ClickHouse queries for frontend ────────────────────────────

def _serialize_value(v):
    """Конвертирует любое значение из ClickHouse в JSON-совместимый тип."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (_datetime, _date)):
        return v.isoformat()
    if isinstance(v, _decimal.Decimal):
        f = float(v)
        return None if _math.isnan(f) or _math.isinf(f) else round(f, 2)
    try:
        import numpy as _np
        if isinstance(v, _np.integer):
            return int(v)
        if isinstance(v, _np.floating):
            return None if _np.isnan(v) else round(float(v), 2)
    except ImportError:
        pass
    if isinstance(v, float):
        return None if (_math.isnan(v) or _math.isinf(v)) else round(v, 2)
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple)):
        return [_serialize_value(i) for i in v]
    if isinstance(v, dict):
        return {str(k): _serialize_value(val) for k, val in v.items()}
    return str(v)


_ALLOWED_ZONE_STATUSES = {"red", "green", "yellow"}


@app.get("/api/tables", tags=["tables"], summary="Список доступных именованных запросов")
async def list_table_queries():
    """Возвращает все доступные query_name с описаниями и списком колонок для сортировки."""
    from queries import QUERIES
    return {
        "queries": [
            {
                "name": name,
                "description": q["description"],
                "sortable_columns": q["sortable_columns"],
                "filterable_zone_status": q.get("filterable_zone_status", False),
            }
            for name, q in QUERIES.items()
        ]
    }


@app.get("/api/tables/{query_name}", tags=["tables"], summary="Выполнить именованный запрос")
async def get_table_data(
    query_name: str,
    sort_by: Optional[str] = None,
    sort_dir: str = "desc",
    limit: int = 50,
    zone_status: Optional[str] = None,
):
    """
    Выполняет именованный SQL-запрос и возвращает табличные данные.
    Параметры: sort_by, sort_dir (asc/desc), limit (1-1000), zone_status (red/green/yellow).
    """
    from queries import QUERIES
    import pandas as _pd

    if query_name not in QUERIES:
        raise HTTPException(status_code=404, detail=f"Query '{query_name}' not found")

    query = QUERIES[query_name]
    sql = query["sql"].strip()

    if zone_status is not None:
        if not query.get("filterable_zone_status"):
            raise HTTPException(
                status_code=400,
                detail=f"Query '{query_name}' does not support zone_status filter",
            )
        if zone_status not in _ALLOWED_ZONE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid zone_status '{zone_status}'. Allowed: {sorted(_ALLOWED_ZONE_STATUSES)}",
            )
        sql += f"\nAND zone_status = '{zone_status}'"

    # Count query uses filtered SQL without ORDER BY / LIMIT
    count_sql = f"SELECT count() FROM ({sql}) AS _subq LIMIT 1"

    if sort_by is not None:
        if sort_by not in query["sortable_columns"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot sort by '{sort_by}'. Allowed: {query['sortable_columns']}",
            )
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
        sql += f"\nORDER BY {sort_by} {direction}"

    limit = max(1, min(limit, 1000))
    sql += f"\nLIMIT {limit}"

    try:
        from tools import _ch_lock, _get_ch_client
        ch = _get_ch_client()
        with _ch_lock:
            result = await asyncio.to_thread(ch.execute_query, sql)
        with _ch_lock:
            count_result = await asyncio.to_thread(ch.execute_query, count_sql)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Query failed"))

    try:
        df = _pd.read_parquet(result["parquet_path"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read result: {exc}")

    total_count: Optional[int] = None
    if count_result.get("success"):
        try:
            count_df = _pd.read_parquet(count_result["parquet_path"])
            total_count = int(count_df.iloc[0, 0])
        except Exception:
            pass

    columns = df.columns.tolist()
    rows = [
        [_serialize_value(cell) for cell in row]
        for row in df.itertuples(index=False, name=None)
    ]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "total_count": total_count,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("api_server:app", host=HOST, port=PORT, log_level="info")
