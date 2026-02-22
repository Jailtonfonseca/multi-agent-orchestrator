from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import redis
import json
import uuid
import asyncio
import time
from typing import List, Optional, Any
from celery.result import AsyncResult
from worker import create_team_and_execute

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis Connection (for pub/sub logs)
redis_client = redis.Redis(host='redis', port=6379, db=0)

class TaskRequest(BaseModel):
    task: str
    api_key: str
    model: str
    provider: str = "openrouter" # Default
    system_message: Optional[str] = None

class ChatReply(BaseModel):
    session_id: str
    message: str

class Session(BaseModel):
    id: str
    task: str
    model: str
    created_at: float
    status: str

@app.post("/api/start-task")
async def start_task(request: TaskRequest):
    """
    Starts a new AutoGen task execution in a background worker.
    Returns a session_id to subscribe for logs.
    """
    session_id = str(uuid.uuid4())

    # Trigger Celery Task
    task_result = create_team_and_execute.delay(
        session_id=session_id,
        task=request.task,
        api_key=request.api_key,
        model=request.model,
        provider=request.provider,
        system_message=request.system_message
    )

    return {"session_id": session_id, "task_id": task_result.id}

@app.post("/api/reply")
async def send_reply(reply: ChatReply):
    """
    Sends a user reply to the waiting AutoGen session via Redis.
    """
    # Publish the user's input to the specific input channel for this session
    channel = f"input_{reply.session_id}"
    redis_client.publish(channel, reply.message)

    # Also log it for history (as a log type)
    log_entry = json.dumps({
        "type": "log",
        "content": f"\nUser: {reply.message}\n",
        "timestamp": time.time()
    })
    redis_client.rpush(f"logs:{reply.session_id}", log_entry)

    return {"status": "sent"}

@app.get("/api/sessions", response_model=List[Session])
async def get_sessions():
    """
    Retrieves a list of all past sessions.
    """
    session_ids = redis_client.lrange("all_sessions", 0, -1)
    sessions = []

    if not session_ids:
        return []

    for sid in session_ids:
        try:
            sid_str = sid.decode('utf-8')
            data = redis_client.hgetall(f"session:{sid_str}")
            if data:
                # Decode bytes to strings
                decoded = {k.decode('utf-8'): v.decode('utf-8') for k, v in data.items()}
                sessions.append({
                    "id": decoded.get("id"),
                    "task": decoded.get("task"),
                    "model": decoded.get("model"),
                    "created_at": float(decoded.get("created_at", 0)),
                    "status": decoded.get("status")
                })
        except Exception as e:
            # Skip corrupted entries
            continue

    return sessions

@app.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: str):
    """
    Retrieves full log history for a session.
    """
    logs = redis_client.lrange(f"logs:{session_id}", 0, -1)
    parsed_logs = []
    for log in logs:
        try:
            parsed_logs.append(json.loads(log.decode('utf-8')))
        except:
            # If plain text was somehow pushed
            parsed_logs.append({"type": "log", "content": log.decode('utf-8')})
    return parsed_logs

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pubsub = redis_client.pubsub()
    pubsub.subscribe(session_id)

    try:
        while True:
            # Check for messages with a small timeout to allow checking for disconnects
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)

            if message:
                try:
                    if isinstance(message['data'], bytes):
                        data_str = message['data'].decode('utf-8')
                        await websocket.send_text(data_str)
                except Exception as e:
                    print(f"Error sending message: {e}")
                    break

            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        # print(f"Client disconnected: {session_id}") # Common, don't spam
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            pubsub.unsubscribe(session_id)
            # await websocket.close()
        except:
            pass

@app.get("/health")
def health_check():
    return {"status": "ok"}
