from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

# User model removed

class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)
    # user_id removed
    task: str
    model: str
    status: str
    created_at: float

    logs: List["Log"] = Relationship(back_populates="session")

class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id")
    type: str # 'log', 'status', 'error'
    content: str
    timestamp: float

    session: Optional[Session] = Relationship(back_populates="logs")
