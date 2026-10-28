import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ChatAPIError
from app.models.chat import ChatTurn, Conversation, Message
from app.providers.base import (
    AIProvider,
    GenerationRequest,
    ProviderError,
    ProviderMessage,
)
from app.schemas.chat import (
    ChatProviderStatus,
    ContextInfo,
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    MessageListResponse,
    MessageResponse,
    SendMessageRequest,
)
from app.services.context import ContextWindow, build_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _session(request: Request) -> Session:
    return request.app.state.session_factory()


def _conversation_or_404(session: Session, conversation_id: str) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise ChatAPIError(404, "conversation_not_found", "Conversation not found.")
    return conversation


def _ensure_active(conversation: Conversation) -> None:
    if conversation.archived:
        raise ChatAPIError(
            409,
            "conversation_archived",
            "Unarchive this conversation before sending a message.",
        )


@router.get("/chat/provider", response_model=ChatProviderStatus, tags=["chat"])
def provider_status(request: Request) -> ChatProviderStatus:
    provider: AIProvider = request.app.state.ai_provider
    settings = request.app.state.settings
    configured = provider.name != "ollama" or bool(settings.ollama_model.strip())
    available = provider.is_available() if configured else False
    return ChatProviderStatus(
        provider=provider.name,
        model=provider.model_name,
        configured=configured,
        available=available,
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations"],
)
def create_conversation(
    request: Request,
    body: ConversationCreate,
) -> ConversationResponse:
    with _session(request) as session:
        conversation = Conversation(title=body.title.strip())
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return ConversationResponse.model_validate(conversation)


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    tags=["conversations"],
)
def list_conversations(
    request: Request,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ConversationListResponse:
    with _session(request) as session:
        query = select(Conversation)
        count_query = select(func.count()).select_from(Conversation)
        if not include_archived:
            query = query.where(Conversation.archived.is_(False))
            count_query = count_query.where(Conversation.archived.is_(False))
        items = session.scalars(
            query.order_by(Conversation.updated_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit)
        ).all()
        total = session.scalar(count_query) or 0
        return ConversationListResponse(
            items=[ConversationResponse.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["conversations"],
)
def get_conversation(request: Request, conversation_id: str) -> ConversationResponse:
    with _session(request) as session:
        conversation = _conversation_or_404(session, conversation_id)
        return ConversationResponse.model_validate(conversation)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["conversations"],
)
def update_conversation(
    request: Request,
    conversation_id: str,
    body: ConversationUpdate,
) -> ConversationResponse:
    if body.title is None and body.archived is None:
        raise ChatAPIError(422, "empty_update", "Provide a title or archived value.")
    with _session(request) as session:
        conversation = _conversation_or_404(session, conversation_id)
        if body.title is not None:
            conversation.title = body.title.strip()
        if body.archived is not None:
            conversation.archived = body.archived
        conversation.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(conversation)
        return ConversationResponse.model_validate(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["conversations"],
)
def delete_conversation(request: Request, conversation_id: str) -> Response:
    with _session(request) as session:
        conversation = _conversation_or_404(session, conversation_id)
        session.delete(conversation)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    tags=["conversations"],
)
def list_messages(
    request: Request,
    conversation_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    with _session(request) as session:
        _conversation_or_404(session, conversation_id)
        total = (
            session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
            or 0
        )
        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return MessageListResponse(
            items=[MessageResponse.model_validate(message) for message in messages],
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(messages) < total,
        )


def _build_context(
    session: Session,
    conversation_id: str,
    current_user_content: str | None,
    request: Request,
) -> ContextWindow:
    settings = request.app.state.settings
    previous_messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1000)
    ).all()
    history = [
        ProviderMessage(role=message.role, content=message.content)
        for message in reversed(previous_messages)
    ]
    if current_user_content is not None:
        history.append(ProviderMessage(role="user", content=current_user_content))
    try:
        return build_context(
            history=history,
            system_prompt=settings.chat_system_prompt,
            context_limit_tokens=settings.chat_context_tokens,
            reserved_output_tokens=settings.chat_reserved_output_tokens,
        )
    except ValueError as exc:
        raise ChatAPIError(422, "context_budget_exceeded", str(exc)) from exc


def _event(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _start_turn(
    request: Request,
    conversation_id: str,
    content: str,
    idempotency_key: str,
) -> tuple[ChatTurn, Message, ContextWindow | None, Message | None]:
    with _session(request) as session:
        conversation = _conversation_or_404(session, conversation_id)
        _ensure_active(conversation)
        turn = session.scalar(
            select(ChatTurn).where(
                ChatTurn.conversation_id == conversation_id,
                ChatTurn.idempotency_key == idempotency_key,
            )
        )
        if turn is not None:
            user_message = session.scalar(
                select(Message).where(
                    Message.turn_id == turn.id,
                    Message.role == "user",
                )
            )
            if user_message is None or user_message.content != content:
                raise ChatAPIError(
                    409,
                    "idempotency_key_reused",
                    "This idempotency key is already associated with another request.",
                )
            if turn.status == "streaming":
                raise ChatAPIError(
                    409,
                    "request_in_progress",
                    "A request with this idempotency key is already in progress.",
                )
            if turn.status == "completed":
                assistant = session.scalar(
                    select(Message).where(
                        Message.turn_id == turn.id,
                        Message.role == "assistant",
                    )
                )
                if assistant is None:
                    raise ChatAPIError(
                        500,
                        "completed_turn_missing_response",
                        "The saved response is unavailable.",
                    )
                return turn, user_message, None, assistant
            context = _build_context(session, conversation_id, None, request)
            turn.status = "streaming"
            turn.completed_at = None
            session.commit()
            return turn, user_message, context, None

        context = _build_context(session, conversation_id, content, request)
        turn = ChatTurn(
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            status="streaming",
        )
        session.add(turn)
        try:
            session.flush()
            user_message = Message(
                conversation_id=conversation_id,
                turn_id=turn.id,
                role="user",
                content=content,
            )
            session.add(user_message)
            if conversation.title == "New conversation":
                conversation.title = content.strip().splitlines()[0][:120] or "New conversation"
            conversation.updated_at = datetime.now(timezone.utc)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ChatAPIError(
                409,
                "request_conflict",
                "A request with this idempotency key was submitted concurrently.",
            ) from exc
        session.refresh(turn)
        session.refresh(user_message)
        return turn, user_message, context, None


def _finish_turn(
    request: Request,
    turn_id: str,
    conversation_id: str,
    content: str,
    *,
    status_value: str,
) -> Message | None:
    with _session(request) as session:
        turn = session.get(ChatTurn, turn_id)
        if turn is None:
            return None
        if status_value == "completed":
            assistant = Message(
                conversation_id=conversation_id,
                turn_id=turn_id,
                role="assistant",
                content=content,
            )
            session.add(assistant)
            turn.status = "completed"
            turn.completed_at = datetime.now(timezone.utc)
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(assistant)
            return assistant
        turn.status = status_value
        turn.completed_at = datetime.now(timezone.utc)
        session.commit()
        return None


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
    responses={
        200: {"description": "Server-Sent Events with meta, delta, done, or error events"},
        404: {"description": "Conversation not found"},
        409: {"description": "Conversation archived or request in progress"},
    },
    tags=["chat"],
)
def stream_message(
    request: Request,
    conversation_id: str,
    body: SendMessageRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StreamingResponse:
    if idempotency_key is None or IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
        raise ChatAPIError(
            422,
            "invalid_idempotency_key",
            "Provide an Idempotency-Key containing 8 to 128 safe characters.",
        )

    content = body.content.strip()
    if not content:
        raise ChatAPIError(422, "empty_message", "Message content cannot be blank.")
    turn, user_message, context, replay = _start_turn(
        request,
        conversation_id,
        content,
        idempotency_key,
    )
    provider: AIProvider = request.app.state.ai_provider
    model = provider.model_name
    max_output_tokens = request.app.state.settings.chat_reserved_output_tokens

    async def stream_events() -> AsyncIterator[str]:
        if replay is not None:
            yield _event(
                "meta",
                {
                    "turn_id": turn.id,
                    "user_message": MessageResponse.model_validate(user_message).model_dump(mode="json"),
                    "provider": provider.name,
                    "model": model,
                    "replayed": True,
                },
            )
            for index in range(0, len(replay.content), 48):
                yield _event("delta", {"delta": replay.content[index : index + 48]})
            yield _event(
                "done",
                {
                    "turn_id": turn.id,
                    "replayed": True,
                    "assistant_message": MessageResponse.model_validate(replay).model_dump(mode="json"),
                },
            )
            return

        assert context is not None
        finalized = False
        response_parts: list[str] = []
        generation_request = GenerationRequest(
            messages=context.messages,
            model=model,
            max_output_tokens=max_output_tokens,
        )
        provider_stream = provider.astream(generation_request)
        started_at = time.perf_counter()
        logger.info(
            "Chat context selected: provider=%s model=%s strategy=%s input_tokens=%d input_budget=%d truncated_messages=%d",
            provider.name,
            model,
            context.strategy,
            context.estimated_input_tokens,
            context.input_budget_tokens,
            context.truncated_messages,
        )
        try:
            yield _event(
                "meta",
                {
                    "turn_id": turn.id,
                    "user_message": MessageResponse.model_validate(user_message).model_dump(mode="json"),
                    "provider": provider.name,
                    "model": model,
                    "replayed": False,
                },
            )
            async for token in provider_stream:
                if token:
                    response_parts.append(token)
                    yield _event("delta", {"delta": token})

            response_text = "".join(response_parts)
            if not response_text:
                raise ProviderError("Provider returned an empty response.")
            assistant = _finish_turn(
                request,
                turn.id,
                conversation_id,
                response_text,
                status_value="completed",
            )
            finalized = True
            if assistant is None:
                raise ProviderError("The generated response could not be saved.")
            logger.info(
                "Chat generation completed: provider=%s model=%s input_tokens=%d output_characters=%d duration_ms=%d",
                provider.name,
                model,
                context.estimated_input_tokens,
                len(response_text),
                round((time.perf_counter() - started_at) * 1000),
            )
            context_info = ContextInfo(
                estimated_input_tokens=context.estimated_input_tokens,
                input_budget_tokens=context.input_budget_tokens,
                truncated_messages=context.truncated_messages,
                strategy=context.strategy,
            )
            yield _event(
                "done",
                {
                    "turn_id": turn.id,
                    "replayed": False,
                    "context": context_info.model_dump(),
                    "assistant_message": MessageResponse.model_validate(assistant).model_dump(mode="json"),
                },
            )
        except ProviderError as exc:
            logger.warning(
                "AI provider request failed: provider=%s code=%s duration_ms=%d",
                provider.name,
                exc.code,
                round((time.perf_counter() - started_at) * 1000),
            )
            _finish_turn(
                request,
                turn.id,
                conversation_id,
                "",
                status_value="failed",
            )
            finalized = True
            yield _event(
                "error",
                {"error": {"code": exc.code, "message": exc.public_message}, "turn_id": turn.id},
            )
        finally:
            try:
                await provider_stream.aclose()
            finally:
                if not finalized:
                    _finish_turn(
                        request,
                        turn.id,
                        conversation_id,
                        "",
                        status_value="cancelled",
                    )

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
