from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional
import json
import uuid
import asyncio
import time
import os
import sys
import traceback

from database import create_db_and_tables, get_session, engine
from models import Session as DBSession, Log

# ── Redis ──────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

import redis
import redis.asyncio as aioredis

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
aioredis_client = aioredis.Redis.from_url(REDIS_URL, decode_responses=False)

# ── Celery (send-only — we never import worker.py here) ───────────────────────
try:
    from celery import Celery
    celery_app = Celery("autogen_tasks", broker=REDIS_URL, backend=REDIS_URL)
    print("[MAIN] Celery client initialized OK.")
except Exception as e:
    print(f"[MAIN] WARNING: Celery import failed: {e}")
    celery_app = None


def _wait_for_db(retries: int = 10, delay: float = 2.0):
    """Retry DB creation on startup — avoids race with Postgres."""
    for attempt in range(1, retries + 1):
        try:
            create_db_and_tables()
            print(f"DB ready after {attempt} attempt(s).")
            return
        except Exception as e:
            print(f"DB init attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError("Could not connect to the database after multiple retries.")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _wait_for_db()
    yield
    try:
        await aioredis_client.aclose()
    except Exception:
        pass


app = FastAPI(title="AutoGen Enterprise API", version="1.3.0", lifespan=lifespan)

# ── CORS — allow ALL origins for development ──────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic Models ────────────────────────────────────────────────────────────
class TaskRequest(BaseModel):
    task: str
    api_key: str
    model: str
    provider: str = "openrouter"
    system_message: Optional[str] = None
    tavily_key: Optional[str] = None


class ChatReply(BaseModel):
    session_id: str
    message: str


class SessionResponse(BaseModel):
    id: str
    task: str
    model: str
    created_at: float
    status: str


# ── API Routes ─────────────────────────────────────────────────────────────────
@app.post("/api/start-task")
def start_task(
    request: TaskRequest,
    session: Session = Depends(get_session)
):
    if celery_app is None:
        raise HTTPException(status_code=503, detail="Celery not available. Check backend logs.")

    session_id = str(uuid.uuid4())

    db_sess = DBSession(
        id=session_id,
        task=request.task,
        model=request.model,
        status="BUILDING_TEAM",
        created_at=time.time()
    )
    session.add(db_sess)
    session.commit()

    try:
        celery_app.send_task(
            "worker.create_team_and_execute",
            kwargs={
                "session_id": session_id,
                "task": request.task,
                "api_key": request.api_key,
                "model": request.model,
                "provider": request.provider,
                "system_message": request.system_message,
                "tavily_key": request.tavily_key,
            }
        )
    except Exception as e:
        # Update status so user sees the error
        db_sess.status = "ERROR"
        session.add(db_sess)
        session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {str(e)}")

    return {"session_id": session_id}


@app.post("/api/stop-task/{session_id}")
def stop_task(session_id: str):
    redis_client.publish(f"input_{session_id}", "TERMINATE")
    return {"status": "stop_signal_sent"}


@app.post("/api/reply")
def send_reply(reply: ChatReply, session: Session = Depends(get_session)):
    channel = f"input_{reply.session_id}"
    redis_client.publish(channel, reply.message)

    log = Log(
        session_id=reply.session_id,
        type="log",
        content=f"\nUser: {reply.message}\n",
        timestamp=time.time()
    )
    session.add(log)
    session.commit()

    return {"status": "sent"}


@app.get("/api/sessions", response_model=List[SessionResponse])
def get_sessions(session: Session = Depends(get_session)):
    return session.exec(
        select(DBSession).order_by(DBSession.created_at.desc())
    ).all()


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session_by_id(session_id: str, session: Session = Depends(get_session)):
    db_sess = session.get(DBSession, session_id)
    if not db_sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return db_sess


@app.get("/api/sessions/{session_id}/logs")
def get_session_logs(session_id: str, session: Session = Depends(get_session)):
    db_sess = session.get(DBSession, session_id)
    if not db_sess:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = session.exec(
        select(Log)
        .where(Log.session_id == session_id)
        .order_by(Log.timestamp)
    ).all()
    return [{"type": l.type, "content": l.content, "timestamp": l.timestamp} for l in logs]


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pubsub = aioredis_client.pubsub()
    await pubsub.subscribe(session_id)

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message:
                try:
                    data = message['data']
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                    await websocket.send_text(data)
                except Exception:
                    break

            await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error [{session_id}]: {e}")
    finally:
        try:
            await pubsub.unsubscribe(session_id)
            await pubsub.aclose()
        except Exception:
            pass


@app.get("/health")
def health_check():
    """Deep health check: tests Redis, DB and Celery connectivity."""
    health = {"status": "ok", "redis": "ok", "db": "ok", "celery": "ok", "version": "1.3.0"}

    try:
        redis_client.ping()
    except Exception as e:
        health["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"

    try:
        with Session(engine) as session:
            session.exec(select(DBSession).limit(1)).all()
    except Exception as e:
        health["db"] = f"error: {str(e)}"
        health["status"] = "degraded"

    if celery_app is None:
        health["celery"] = "error: not initialized"
        health["status"] = "degraded"

    return health


# ── Debug: print on startup ──────────────────────────────────────────────────
print(f"[MAIN] Backend starting — REDIS_URL={REDIS_URL}")
print(f"[MAIN] CORS: allow_origins=['*']")
