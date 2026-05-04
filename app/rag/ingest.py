"""
RAG Ingestion CLI.
Handles reading, chunking, and embedding markdown documentation into ChromaDB.
"""
import argparse
import asyncio
import re
from pathlib import Path
import yaml
from app.rag.vector_store import vector_store

def chunk_markdown(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """
    Split markdown text into overlapping chunks based on sentence boundaries.
    
    Args:
        text: Raw markdown content.
        chunk_size: Maximum characters per chunk.
        overlap: Target overlap between adjacent chunks to maintain context.
        
    Returns:
        A list of text snippets ready for embedding.
    """
    # Remove frontmatter if present to avoid indexing metadata as searchable text
    if text.startswith("---"):
        _, text = extract_metadata_and_body(text)
    
    # Split by sentence boundaries to preserve semantic meaning
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current, current_len = [], [], 0
    
    for sentence in sentences:
        # If adding the next sentence exceeds the size, close the current chunk
        if current_len + len(sentence) > chunk_size and current:
            chunks.append(" ".join(current))
            # Basic overlap: keep the last 1-2 sentences for the next chunk
            current = current[-2:] if len(current) > 2 else current[-1:]
            current_len = sum(len(s) for s in current)
        current.append(sentence)
        current_len += len(sentence)
        
    # Append the final remaining piece
    if current:
        chunks.append(" ".join(current))
    return chunks

def extract_metadata_and_body(text: str) -> tuple[dict, str]:
    """
    Parses YAML frontmatter from the top of a markdown file.
    
    Returns:
        A tuple of (metadata_dict, body_text).
    """
    match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not match:
        return {}, text
    try:
        metadata = yaml.safe_load(match.group(1))
    except Exception:
        # Fallback if YAML is malformed
        metadata = {}
    body = text[match.end():]
    return metadata, body

def extract_metadata(file_path: Path, text: str) -> dict:
    """
    Processes frontmatter into a format compatible with ChromaDB.
    ChromaDB metadata must be primitive types (str, int, float, bool).
    """
    meta, _ = extract_metadata_and_body(text)
    processed = {}
    for k, v in meta.items():
        if isinstance(v, list):
            # Flatten lists into comma-separated strings
            processed[k] = ", ".join(map(str, v))
        elif isinstance(v, (str, int, float, bool)):
            processed[k] = v
        else:
            processed[k] = str(v)
    return processed

async def ingest_directory(docs_path: Path, chunk_size: int, chunk_overlap: int) -> None:
    """
    Recursively scans a directory for markdown files and ingests them.
    """
    md_files = list(docs_path.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files in {docs_path}")

    for file_path in md_files:
        text = file_path.read_text(encoding="utf-8")
        metadata = extract_metadata(file_path, text)
        chunks = chunk_markdown(text, chunk_size, chunk_overlap)
        print(f"  {file_path.name}: {len(chunks)} chunks")
        
        # Batch upsert for efficiency
        if chunks:
            await vector_store.upsert_chunks(str(file_path), chunks, metadata)

    print("Ingest complete.")

def main() -> None:
    """CLI Entry point for documentation ingestion."""
    parser = argparse.ArgumentParser(description="Ingest docs into the vector store")
    parser.add_argument("--path", type=Path, required=True, help="Directory containing .md files")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=64)
    args = parser.parse_args()

    # Run the async ingestion loop
    asyncio.run(ingest_directory(args.path, args.chunk_size, args.chunk_overlap))

if __name__ == "__main__":
    main()
