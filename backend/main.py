from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import redis
import json
import uuid
import asyncio
from typing import List
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

class ChatReply(BaseModel):
    session_id: str
    message: str

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
        model=request.model
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
    return {"status": "sent"}

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
        print(f"Client disconnected: {session_id}")
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
