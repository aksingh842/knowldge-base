"""
FastAPI routes for the chat interface.
Implements Extension E1 (Idempotency) and E3 (Streaming).
"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db
from app.db.models import IdempotencyKey
from app.srop import pipeline
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["Chat"])

class ChatRequest(BaseModel):
    """Schema for a chat turn request."""
    content: str
    api_key: Optional[str] = None # Dynamic key injection

class ChatResponse(BaseModel):
    """Schema for a standard synchronous chat reply."""
    reply: str
    routed_to: str
    trace_id: str

@router.post("/chat/{session_id}")
async def chat(
    session_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    accept: str | None = Header(None, alias="Accept"),
):
    """
    Primary endpoint for conversation turns.
    
    Logic:
    1. Check for Idempotency-Key (E1): Return cached result if key exists for this session.
    2. Check for SSE Accept header (E3): Return an EventSourceResponse for streaming.
    3. Default: Run synchronous pipeline and return a standard JSON response.
    """
    
    # 1. IDEMPOTENCY CHECK (Extension E1)
    # We only cache non-streaming responses to ensure database consistency.
    if idempotency_key and accept != "text/event-stream":
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.key == idempotency_key,
            IdempotencyKey.session_id == session_id
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            # Re-serialize the cached response
            return ChatResponse(**existing.response_json)

    # 2. STREAMING RESPONSE (Extension E3)
    # Triggered if 'Accept: text/event-stream' is provided in headers.
    if accept == "text/event-stream":
        return EventSourceResponse(
            pipeline.run_stream(session_id, body.content, db, api_key=body.api_key)
        )

    # 3. REGULAR RESPONSE
    # Execute the core pipeline and capture the result.
    result_data = await pipeline.run(session_id, body.content, db, api_key=body.api_key)
    response = ChatResponse(
        reply=result_data.content, 
        routed_to=result_data.routed_to, 
        trace_id=result_data.trace_id
    )

    # Cache the result if an idempotency key was provided
    if idempotency_key:
        db.add(IdempotencyKey(
            key=idempotency_key,
            session_id=session_id,
            response_json=response.model_dump()
        ))
        await db.commit()

    return response
