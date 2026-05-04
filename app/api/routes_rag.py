from fastapi import APIRouter, BackgroundTasks, UploadFile, File
from app.rag.ingest import ingest_directory, chunk_markdown, extract_metadata
from app.rag.vector_store import vector_store
from pathlib import Path
import os
import shutil

router = APIRouter(tags=["RAG"])

@router.post("/ingest")
async def trigger_ingest(background_tasks: BackgroundTasks):
    """
    Triggers a full ingestion of the docs/ directory in the background.
    """
    docs_path = Path("docs")
    background_tasks.add_task(ingest_directory, docs_path, 512, 64)
    return {"status": "started", "message": "Full ingestion started in background."}

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Accepts a .md file, saves it to docs/, and ingests it immediately.
    """
    if not file.filename.endswith(".md"):
        return {"error": "Only .md files are supported."}
    
    docs_path = Path("docs")
    docs_path.mkdir(exist_ok=True)
    
    file_path = docs_path / file.filename
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Ingest this specific file immediately
    text = file_path.read_text(encoding="utf-8")
    metadata = extract_metadata(file_path, text)
    chunks = chunk_markdown(text, 512, 64)
    
    if chunks:
        await vector_store.upsert_chunks(str(file_path), chunks, metadata)
    
    return {"status": "success", "filename": file.filename, "chunks": len(chunks)}
