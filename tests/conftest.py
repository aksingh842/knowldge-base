"""
Test fixtures.

Key fixtures:
- `client`: async test client with in-memory SQLite DB
- `mock_adk`: patches the ADK root agent so tests don't hit the real LLM
- `seeded_db`: DB with a test user and session pre-created
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.session import get_db
from app.main import app


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db):
    """Async test client with DB overridden to in-memory SQLite."""
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_adk(monkeypatch):
    """
    Patch the ADK pipeline so tests don't call the real LLM.
    """
    from app.srop.pipeline import PipelineResult

    async def mock_run(session_id, user_message, db):
        if "rotate" in user_message.lower():
            return PipelineResult(
                content="To rotate a deploy key, navigate to Settings...",
                routed_to="knowledge",
                trace_id="test-trace-001",
            )
        elif "plan" in user_message.lower():
            # In a real scenario, we'd check the DB for the plan_tier
            return PipelineResult(
                content="Your plan tier is Pro.",
                routed_to="account",
                trace_id="test-trace-002",
            )
        return PipelineResult(
            content="Hello!",
            routed_to="smalltalk",
            trace_id="test-trace-003",
        )

    monkeypatch.setattr("app.srop.pipeline.run", mock_run)
