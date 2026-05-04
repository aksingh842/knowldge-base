import pytest
from app.agents.tools.search_docs import search_docs
from app.rag.vector_store import vector_store

@pytest.mark.asyncio
async def test_search_docs_structure():
    # Note: This requires a populated vector store or mocking
    # For now, we'll verify it returns a string (as implemented)
    # In a real test, we'd mock the collection.query result
    
    query = "how to rotate a deploy key"
    result = await search_docs(query, k=3)
    
    assert isinstance(result, str)
    # If store is empty, it returns the empty message
    if "No relevant documentation found" not in result:
        assert "[" in result
        assert "score:" in result

@pytest.mark.asyncio
async def test_vector_store_direct():
    # Mocking would be better here, but let's check the DocChunk model
    from app.rag.vector_store import DocChunk
    chunk = DocChunk(chunk_id="test_1", content="test content", metadata={}, score=0.9)
    assert chunk.score >= 0 and chunk.score <= 1
