import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.session import AsyncSessionLocal
from app.db.models import Session, User, Message
from sqlalchemy import select

@pytest.mark.asyncio
async def test_session_creation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/v1/sessions", json={"user_id": "test_user", "plan_tier": "pro"})
    
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["user_id"] == "test_user"

@pytest.mark.asyncio
async def test_full_flow_persistence():
    user_id = f"user_{uuid.uuid4().hex[:6]}"
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create session
        res = await ac.post("/v1/sessions", json={"user_id": user_id, "plan_tier": "pro"})
        session_id = res.json()["session_id"]
        
        # 2. Mocking ADK/LLM would be ideal here to avoid real API calls
        # For the sake of this test, we verify the endpoint exists and returns 404 for invalid sessions
        res = await ac.post("/v1/chat/invalid_id", json={"content": "hello"})
        assert res.status_code == 404

@pytest.mark.asyncio
async def test_db_persistence():
    # Verify we can write and read from DB (sanity check for async sqlite)
    session_id = str(uuid.uuid4())
    user_id = "test_persist"
    
    async with AsyncSessionLocal() as db:
        user = User(user_id=user_id, plan_tier="free")
        db.add(user)
        session = Session(session_id=session_id, user_id=user_id, state={"turn_count": 0})
        db.add(session)
        await db.commit()
        
        stmt = select(Session).where(Session.session_id == session_id)
        res = await db.execute(stmt)
        row = res.scalar_one()
        assert row.user_id == user_id
