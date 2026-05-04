"""
POST /v1/sessions — create a session.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    user_id: str
    plan_tier: str = "free"


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str


from sqlalchemy import select
from app.db.models import Session, User
from app.srop.state import SessionState

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    """
    Create a new session. Upsert the user if not seen before.
    Initialize SessionState and persist to DB.
    """
    # 1. Upsert User
    stmt = select(User).where(User.user_id == body.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(user_id=body.user_id, plan_tier=body.plan_tier)
        db.add(user)
    else:
        user.plan_tier = body.plan_tier # Update if changed
    
    # 2. Create Session
    session_id = str(uuid.uuid4())
    initial_state = SessionState(user_id=body.user_id, plan_tier=body.plan_tier) # type: ignore
    
    new_session = Session(
        session_id=session_id,
        user_id=body.user_id,
        state=initial_state.to_db_dict()
    )
    db.add(new_session)
    await db.commit()

    return CreateSessionResponse(
        session_id=session_id,
        user_id=body.user_id
    )
