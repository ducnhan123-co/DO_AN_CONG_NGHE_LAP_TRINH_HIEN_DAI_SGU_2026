"""Schema request của Library API (View)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    num_pages: Optional[int] = Field(default=None, ge=0, le=100000)
    parser: Optional[str] = Field(default=None, max_length=40)


class RenameIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class SessionIn(BaseModel):
    title: str = Field(default="", max_length=120)


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    citations: Optional[list[int]] = Field(default=None, max_length=50)
    model: Optional[str] = Field(default=None, max_length=100)
    elapsed_s: Optional[float] = None


class MessagesIn(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=4)


class SnapshotIn(BaseModel):
    source: Literal["fast", "mineru"] = "fast"