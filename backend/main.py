from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional
import json
import uuid
import asyncio
import time
import os
import redis
import redis.asyncio as aioredis

from database import create_db_and_tables, get_session
from models import Session as DBSession, Log
from worker import create_team_and_execute, app as celery_app

app = FastAPI()

# Init DB on startup
@app.on_event("startup")
def on_startup():
    time.sleep(3)
    try:
        create_db_and_tables()
    except Exception as e:
        print(f"DB Init Error: {e}")

# CORS
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.Redis(host='redis', port=6379, db=0)
aioredis_client = aioredis.Redis(host='redis', port=6379, db=0)

# --- Pydantic Models ---
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

# --- API Routes ---

@app.post("/api/start-task")
def start_task(
    request: TaskRequest,
    session: Session = Depends(get_session)
):
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

    task_result = create_team_and_execute.delay(
        session_id=session_id,
        task=request.task,
        api_key=request.api_key,
        model=request.model,
        provider=request.provider,
        system_message=request.system_message,
        tavily_key=request.tavily_key
    )

    return {"session_id": session_id, "task_id": task_result.id}

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
    # Return all sessions, sorted by date
    all_sessions = session.exec(select(DBSession).order_by(DBSession.created_at.desc())).all()
    return all_sessions

@app.get("/api/sessions/{session_id}/logs")
def get_session_logs(session_id: str, session: Session = Depends(get_session)):
    db_sess = session.get(DBSession, session_id)
    if not db_sess:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = session.exec(select(Log).where(Log.session_id == session_id).order_by(Log.timestamp)).all()
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
                    if isinstance(message['data'], bytes):
                        data_str = message['data'].decode('utf-8')
                        await websocket.send_text(data_str)
                except Exception as e:
                    break

            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket Loop Error: {e}")
    finally:
        try:
            await pubsub.unsubscribe(session_id)
        except:
            pass

@app.get("/health")
def health_check():
    return {"status": "ok"}
