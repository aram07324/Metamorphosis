from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank.")
        return value.strip()


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Title cannot be blank.")
        return value.strip() if value is not None else None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    turn_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class ChatTurnResponse(BaseModel):
    id: str
    status: Literal["streaming", "completed", "failed", "cancelled"]
    assistant_message: MessageResponse | None = None


class ContextInfo(BaseModel):
    estimated_input_tokens: int
    input_budget_tokens: int
    truncated_messages: int
    strategy: str


class ChatProviderStatus(BaseModel):
    provider: str
    model: str
    configured: bool
    available: bool
