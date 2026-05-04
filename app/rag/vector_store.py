"""
Vector Store implementation using ChromaDB for semantic search and retrieval.
Includes LLM-as-judge reranking (Extension E4).
"""
import hashlib
import uuid
import re
from typing import Any, Optional

import chromadb
import google.generativeai as genai
from pydantic import BaseModel

from app.settings import settings

# Global configuration for embeddings using the project-wide settings
genai.configure(api_key=settings.google_api_key)

class DocChunk(BaseModel):
    """
    Schema for a retrieved document segment.
    - chunk_id: Unique deterministic hash.
    - content: The raw text snippet.
    - metadata: Source info (filename, headers).
    - score: Relevance confidence (0 to 1).
    """
    chunk_id: str
    content: str
    metadata: dict[str, Any]
    score: float = 0.0

class VectorStore:
    """
    A high-level abstraction for interacting with ChromaDB.
    Handles embedding generation, persistent storage, and multi-stage retrieval.
    """
    def __init__(self):
        """Initializes the persistent ChromaDB client and creates/gets the 'helix_docs' collection."""
        # Persistent storage ensures vector data survives process restarts
        self.client = chromadb.PersistentClient(path="./chroma_db")
        # hnsw:space: cosine similarity is ideal for semantic search
        self.collection = self.client.get_or_create_collection(
            name="helix_docs",
            metadata={"hnsw:space": "cosine"}
        )

    def _make_chunk_id(self, file_path: str, chunk_index: int) -> str:
        """
        Generates a stable, unique ID for a chunk.
        Uses SHA-256 on the file path and index to ensure idempotency during ingestion.
        """
        raw = f"{file_path}::{chunk_index}"
        return "chunk_" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def embed_texts(self, texts: list[str], task_type: str = "retrieval_document") -> list[list[float]]:
        """
        Calls the Google Gemini Embedding API to turn text into vectors.
        - task_type: 'retrieval_document' for storage, 'retrieval_query' for searching.
        """
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=texts,
            task_type=task_type,
        )
        return result["embedding"]

    async def upsert_chunks(self, file_path: str, chunks: list[str], metadata: dict[str, Any]):
        """
        Processes and saves a batch of chunks to the vector database.
        1. Generates deterministic IDs.
        2. Generates embeddings for all chunks in a single batch.
        3. Stores IDs, Embeddings, and Metadata in ChromaDB.
        """
        ids = [self._make_chunk_id(file_path, i) for i in range(len(chunks))]
        embeddings = await self.embed_texts(chunks)
        
        # Enrich metadata with the source file path
        metadatas = []
        for i in range(len(chunks)):
            m = metadata.copy()
            m["source"] = file_path
            metadatas.append(m)

        # Upsert ensures that re-running ingestion updates existing records instead of duplicating
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas
        )

    async def search(self, query: str, k: int = 5, use_reranker: bool = True) -> list[DocChunk]:
        """
        The primary retrieval method.
        1. Performs semantic search against ChromaDB.
        2. If use_reranker is True, performs a second pass using an LLM to refine accuracy.
        """
        # Step 1: Query Embedding
        query_embedding = await self.embed_texts([query], task_type="retrieval_query")
        
        # Step 2: Semantic Retrieval
        # We retrieve 2x candidates if we plan to rerank them
        n_initial = k * 2 if use_reranker else k
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_initial
        )

        # Step 3: Format initial results
        chunks = []
        if results["ids"]:
            for i in range(len(results["ids"][0])):
                chunks.append(DocChunk(
                    chunk_id=results["ids"][0][i],
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i],
                    score=round(1 - results["distances"][0][i], 4)
                ))
        
        initial_results = sorted(chunks, key=lambda x: x.score, reverse=True)
        
        # If no results or reranking disabled, return the top k
        if not use_reranker or not initial_results:
            return initial_results[:k]

        # Step 4: Extension E4 - LLM-as-judge Reranking
        return await self._rerank(query, initial_results, k)

    async def _rerank(self, query: str, chunks: list[DocChunk], k: int) -> list[DocChunk]:
        """
        Uses an LLM to re-evaluate retrieved chunks based on their semantic relevance to the query.
        This fixes common semantic drift issues where vector similarity alone is insufficient.
        """
        if len(chunks) <= 1:
            return chunks

        # Prepare the context for the model
        context = "\n".join([f"ID: {c.chunk_id}\nContent: {c.content[:200]}..." for c in chunks])
        prompt = f"""
        Given the user query: "{query}"
        And the following retrieved document chunks:
        {context}

        Rank the Chunk IDs by their relevance to answering the query. 
        Return ONLY a comma-separated list of IDs, from most relevant to least relevant.
        """
        
        try:
            # Use a fast model (Gemini Flash) to keep latency low
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = await model.generate_content_async(prompt)
            # Parse the model's output to find the ranked IDs
            ranked_ids = [rid.strip() for rid in response.text.split(",") if "chunk_" in rid]
            
            # Map back to the original objects
            chunk_map = {c.chunk_id: c for c in chunks}
            reranked = []
            for rid in ranked_ids:
                if rid in chunk_map:
                    reranked.append(chunk_map[rid])
            
            # Safe Fallback: if the model missed any chunks, add them to the end
            for c in chunks:
                if c not in reranked:
                    reranked.append(c)
            
            return reranked[:k]
        except Exception:
            # If reranking fails (timeout, safety filters), fall back to original semantic order
            return chunks[:k]

# Global singleton instance
vector_store = VectorStore()
