from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    is_active: bool = Field(default=True)

    sessions: List["Session"] = Relationship(back_populates="user")

class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    task: str
    model: str
    status: str
    created_at: float

    user: Optional[User] = Relationship(back_populates="sessions")
    logs: List["Log"] = Relationship(back_populates="session")

class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id")
    type: str # 'log', 'status', 'error'
    content: str
    timestamp: float

    session: Optional[Session] = Relationship(back_populates="logs")
