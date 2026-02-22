from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional
import json
import uuid
import asyncio
import time
import os
import redis

from database import create_db_and_tables, get_session
from models import User, Session as DBSession, Log
from auth import get_password_hash, verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from worker import create_team_and_execute, app as celery_app

app = FastAPI()

# Init DB on startup
@app.on_event("startup")
def on_startup():
    # Wait a bit for DB to be ready in docker-compose
    time.sleep(3)
    try:
        create_db_and_tables()
    except Exception as e:
        print(f"DB Init Error: {e}")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.Redis(host='redis', port=6379, db=0)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# --- Dependencies ---
async def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    from jose import jwt, JWTError
    from auth import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

# --- Pydantic Models ---
class UserCreate(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

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

# --- Auth Routes ---
@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, session: Session = Depends(get_session)):
    existing_user = session.exec(select(User).where(User.username == user.username)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(user.password)
    db_user = User(username=user.username, hashed_password=hashed_password)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username}

# --- API Routes ---

@app.post("/api/start-task")
async def start_task(
    request: TaskRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    session_id = str(uuid.uuid4())

    # Create DB Session Entry
    db_sess = DBSession(
        id=session_id,
        user_id=current_user.id,
        task=request.task,
        model=request.model,
        status="BUILDING_TEAM",
        created_at=time.time()
    )
    session.add(db_sess)
    session.commit()

    # Trigger Celery Task
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
async def stop_task(session_id: str, current_user: User = Depends(get_current_user)):
    # 1. Publish terminate signal to Redis (for InteractiveProxy)
    redis_client.publish(f"input_{session_id}", "TERMINATE")

    # 2. Revoke Celery task (if we stored task_id - tricky without persistence, but for now we rely on signal)
    # TODO: Store celery_task_id in DBSession to revoke properly

    return {"status": "stop_signal_sent"}

@app.post("/api/reply")
async def send_reply(reply: ChatReply, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    channel = f"input_{reply.session_id}"
    redis_client.publish(channel, reply.message)

    # Save user reply to DB
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
async def get_sessions(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Filter by user
    user_sessions = session.exec(select(DBSession).where(DBSession.user_id == current_user.id).order_by(DBSession.created_at.desc())).all()
    return user_sessions

@app.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: str, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Ensure user owns session
    db_sess = session.get(DBSession, session_id)
    if not db_sess or db_sess.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = session.exec(select(Log).where(Log.session_id == session_id).order_by(Log.timestamp)).all()
    return [{"type": l.type, "content": l.content, "timestamp": l.timestamp} for l in logs]

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    # Note: WebSockets are hard to auth via headers. Usually query param ?token=...
    await websocket.accept()
    pubsub = redis_client.pubsub()
    pubsub.subscribe(session_id)

    try:
        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
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
    finally:
        try:
            pubsub.unsubscribe(session_id)
        except:
            pass

@app.get("/health")
def health_check():
    return {"status": "ok"}
