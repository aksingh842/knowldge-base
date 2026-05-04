"""
Core pipeline for the Stateful RAG Orchestration Pipeline (SROP).
Handles session re-hydration, agent execution, state persistence, and trace logging.
"""
import asyncio
import re
import time
import uuid
import os
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from google.adk.runners import InMemoryRunner
from google.adk.events import Event
from google.genai.types import Content, Part
import google.generativeai as genai

from app.db.models import Session, Message, AgentTrace, User
from app.srop.state import SessionState
from app.settings import settings
from app.api.errors import SessionNotFoundError, UpstreamTimeoutError

@dataclass
class PipelineResult:
    """
    Data class to structure the output of a pipeline execution.
    - content: The text reply from the assistant.
    - routed_to: The ID of the agent that handled the turn.
    - trace_id: A unique ID for tracking the request through logs/DB.
    """
    content: str
    routed_to: str
    trace_id: str

def redact_pii(text: str) -> str:
    """
    Scans a string for Personally Identifiable Information (PII) and masks it.
    Currently handles:
    - Email addresses (e.g., user@example.com -> [EMAIL_REDACTED])
    - Phone numbers (various international formats -> [PHONE_REDACTED])
    
    This ensures compliance with Extension E5 (Guardrails/Privacy).
    """
    # Define regex patterns for sensitive data
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    phone_pattern = r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}'
    
    # Perform substitutions
    text = re.sub(email_pattern, "[EMAIL_REDACTED]", text)
    text = re.sub(phone_pattern, "[PHONE_REDACTED]", text)
    return text

# Central lock ensures that concurrent requests don't corrupt the GOOGLE_API_KEY environment variable
llm_lock = asyncio.Lock()

async def run(session_id: str, user_message: str, db: AsyncSession, api_key: str | None = None) -> PipelineResult:
    """
    Main entry point for a standard synchronous chat turn.
    
    Args:
        session_id: The unique ID of the conversation.
        user_message: The raw text input from the user.
        db: An active SQLAlchemy async session.
        api_key: Optional Google API Key provided dynamically by the user (Extension E8).
        
    Returns:
        A PipelineResult containing the reply and trace metadata.
    """
    # 1. FETCH CONTEXT: Load the session and associated user data from the database.
    stmt = select(Session).where(Session.session_id == session_id)
    result = await db.execute(stmt)
    session_row = result.scalar_one_or_none()
    if not session_row:
        # Raise a custom error if the session doesn't exist (handled by FastAPI handler)
        raise SessionNotFoundError(f"Session {session_id} not found")

    # Fetch the user to get their plan tier (pro/free)
    stmt = select(User).where(User.user_id == session_row.user_id)
    result = await db.execute(stmt)
    user_row = result.scalar_one_or_none()

    # 2. STATE RE-HYDRATION: Query the DB for all past messages to rebuild the context window.
    # This is a HARD REQUIREMENT: memory must survive a server restart.
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    result = await db.execute(stmt)
    history_rows = result.scalars().all()

    # 3. CONVERT TO ADK FORMAT: Turn DB rows into ADK 'Event' objects for the runner.
    events = []
    for m in history_rows:
        events.append(Event(
            content=Content(role="model" if m.role == "assistant" else "user", parts=[Part(text=m.content)]),
            author=m.role
        ))

    # 4. INJECT CONTEXT: Pass user-specific metadata (tier, turn count) into the root agent.
    state = SessionState.from_db_dict(session_row.state)
    context_str = f"\n\nUSER CONTEXT:\n- user_id: {session_row.user_id}\n- plan_tier: {user_row.plan_tier if user_row else 'free'}\n- turn_count: {state.turn_count}"
    
    # 5. AGENT INITIALIZATION: Get a fresh orchestrator instance.
    from app.agents.orchestrator import get_root_agent
    async with llm_lock:
        # Temporary environment variable swap for this specific initialization
        original_key = os.environ.get("GOOGLE_API_KEY")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
        try:
            # Instantiate the root agent (and its sub-agents)
            current_root_agent = get_root_agent(api_key=api_key)
            # InMemoryRunner provides the execution loop for the agent graph
            runner = InMemoryRunner(agent=current_root_agent, app_name="helix_srop")
        finally:
            # Restore the original server key to prevent leaking user keys to other threads
            if api_key:
                if original_key:
                    os.environ["GOOGLE_API_KEY"] = original_key
                    genai.configure(api_key=original_key)
                else:
                    if "GOOGLE_API_KEY" in os.environ: del os.environ["GOOGLE_API_KEY"]

    # Re-hydrate the runner's session service with the DB history
    adk_session = await runner.session_service.create_session(app_name="helix_srop", user_id=session_row.user_id, session_id=session_id)
    for e in events: await runner.session_service.append_event(adk_session, e)

    # Initialize tracking variables for the turn
    trace_id = str(uuid.uuid4())
    tool_calls, retrieved_chunk_ids = [], []
    routed_to, final_content = "smalltalk", ""
    start_time = time.time()

    async def run_orchestrator():
        """Handles the asynchronous event stream from the ADK runner."""
        nonlocal routed_to, final_content
        async with llm_lock:
            # Re-apply the dynamic API key for the actual LLM call
            original_key = os.environ.get("GOOGLE_API_KEY")
            if api_key:
                os.environ["GOOGLE_API_KEY"] = api_key
                genai.configure(api_key=api_key)
            try:
                # Iterate over the events generated by the Root Orchestrator
                async for event in runner.run_async(
                    user_id=session_row.user_id, session_id=session_id,
                    new_message=Content(role="user", parts=[Part(text=user_message + context_str)])
                ):
                    # Capture tool calls (e.g., when orchestrator calls Knowledge Specialist)
                    for call in event.get_function_calls():
                        tool_calls.append({"tool_name": call.name, "args": call.args, "result": None})
                        if call.name in ["knowledge", "account", "escalation"]: routed_to = call.name
                    
                    # Capture tool responses and extract RAG citations (Pattern 4)
                    for resp in event.get_function_responses():
                        if tool_calls: tool_calls[-1]["result"] = resp.response
                        res_val = resp.response
                        if isinstance(res_val, dict): res_val = str(res_val.get("result", ""))
                        if isinstance(res_val, str): retrieved_chunk_ids.extend(re.findall(r'\[(chunk_[a-f0-9]+)\]', res_val))

                    # Identify the final response text
                    if event.is_final_response():
                        if routed_to == "smalltalk": routed_to = event.author or "smalltalk"
                        if event.content and event.content.parts:
                            final_content = event.content.parts[0].text
                            # Final scan for citations in the generated text
                            retrieved_chunk_ids.extend(re.findall(r'\[(chunk_[a-f0-9]+)\]', final_content))
            finally:
                # Cleanup environment variables
                if api_key:
                    if original_key:
                        os.environ["GOOGLE_API_KEY"] = original_key
                        genai.configure(api_key=original_key)
                    else:
                        if "GOOGLE_API_KEY" in os.environ: del os.environ["GOOGLE_API_KEY"]

    # Wrap the orchestration in a timeout (from settings) to prevent hung requests
    try:
        await asyncio.wait_for(run_orchestrator(), timeout=settings.llm_timeout_seconds)
    except asyncio.TimeoutError:
        raise UpstreamTimeoutError(f"LLM timed out after {settings.llm_timeout_seconds}s")

    # 6. PERSISTENCE: Save the new state and turn results to the database.
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Store the user's message (Redacted for PII)
    db.add(Message(message_id=str(uuid.uuid4()), session_id=session_id, role="user", content=redact_pii(user_message)))
    
    # Store the assistant's reply (Redacted for PII)
    db.add(Message(message_id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=redact_pii(final_content), trace_id=trace_id))
    
    # Save the trace metadata for observability/evaluations
    db.add(AgentTrace(trace_id=trace_id, session_id=session_id, routed_to=routed_to, tool_calls=tool_calls, retrieved_chunk_ids=list(set(retrieved_chunk_ids)), latency_ms=latency_ms))
    
    # Update turn count and last agent in the session state
    state.turn_count += 1
    state.last_agent = routed_to # type: ignore
    session_row.state = state.to_db_dict()
    await db.commit()

    return PipelineResult(content=final_content, routed_to=routed_to, trace_id=trace_id)

async def run_stream(session_id: str, user_message: str, db: AsyncSession, api_key: str | None = None):
    """
    Streaming version of the pipeline. Yields SSE events instead of a single result.
    
    Yields:
        JSON objects containing partial text chunks or final completion metadata.
    """
    # 1. LOAD CONTEXT (Identical to run())
    stmt = select(Session).where(Session.session_id == session_id)
    result = await db.execute(stmt)
    session_row = result.scalar_one_or_none()
    if not session_row: raise SessionNotFoundError(f"Session {session_id} not found")

    stmt = select(User).where(User.user_id == session_row.user_id)
    result = await db.execute(stmt)
    user_row = result.scalar_one_or_none()

    # 2. RE-HYDRATE HISTORY
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    result = await db.execute(stmt)
    history_rows = result.scalars().all()

    events = []
    for m in history_rows:
        events.append(Event(content=Content(role="model" if m.role == "assistant" else "user", parts=[Part(text=m.content)]), author=m.role))

    # 3. PREPARE AGENT
    state = SessionState.from_db_dict(session_row.state)
    context_str = f"\n\nUSER CONTEXT:\n- user_id: {session_row.user_id}\n- plan_tier: {user_row.plan_tier if user_row else 'free'}\n- turn_count: {state.turn_count}"
    
    from app.agents.orchestrator import get_root_agent
    async with llm_lock:
        original_key = os.environ.get("GOOGLE_API_KEY")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
        try:
            current_root_agent = get_root_agent(api_key=api_key)
            runner = InMemoryRunner(agent=current_root_agent, app_name="helix_srop")
        finally:
            if api_key:
                if original_key:
                    os.environ["GOOGLE_API_KEY"] = original_key
                    genai.configure(api_key=original_key)
                else:
                    if "GOOGLE_API_KEY" in os.environ: del os.environ["GOOGLE_API_KEY"]

    # 4. INITIALIZE SESSION
    adk_session = await runner.session_service.create_session(app_name="helix_srop", user_id=session_row.user_id, session_id=session_id)
    for e in events: await runner.session_service.append_event(adk_session, e)

    trace_id = str(uuid.uuid4())
    tool_calls, retrieved_chunk_ids = [], []
    routed_to, final_content = "smalltalk", ""
    start_time = time.time()

    async with llm_lock:
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            genai.configure(api_key=api_key)
        try:
            # 5. STREAMING EXECUTION
            async for event in runner.run_async(
                user_id=session_row.user_id, session_id=session_id,
                new_message=Content(role="user", parts=[Part(text=user_message + context_str)])
            ):
                # Yield text chunks to the client as they are generated
                if event.content and event.content.parts:
                    chunk = event.content.parts[0].text
                    if chunk and not event.is_final_response():
                        yield {"event": "message", "data": {"text": chunk, "trace_id": trace_id}}
                        final_content += chunk

                # Monitor for tool calls and responses in the background
                for call in event.get_function_calls():
                    tool_calls.append({"tool_name": call.name, "args": call.args, "result": None})
                    if call.name in ["knowledge", "account", "escalation"]: routed_to = call.name
                
                for resp in event.get_function_responses():
                    if tool_calls: tool_calls[-1]["result"] = resp.response
                    res_val = str(resp.response.get("result", "")) if isinstance(resp.response, dict) else str(resp.response)
                    retrieved_chunk_ids.extend(re.findall(r'\[(chunk_[a-f0-9]+)\]', res_val))

                # Handle the final event to capture the remaining text and metadata
                if event.is_final_response():
                    if routed_to == "smalltalk": routed_to = event.author or "smalltalk"
                    if event.content and event.content.parts:
                        full_txt = event.content.parts[0].text
                        rem_txt = full_txt[len(final_content):] if full_txt.startswith(final_content) else full_txt
                        yield {"event": "message", "data": {"text": rem_txt, "trace_id": trace_id}}
                        final_content = full_txt
                    retrieved_chunk_ids.extend(re.findall(r'\[(chunk_[a-f0-9]+)\]', final_content))
        finally:
            # Restore environment variables
            if api_key:
                if original_key:
                    os.environ["GOOGLE_API_KEY"] = original_key
                    genai.configure(api_key=original_key)
                else:
                    if "GOOGLE_API_KEY" in os.environ: del os.environ["GOOGLE_API_KEY"]

    # 6. POST-STREAM PERSISTENCE (Masking PII before saving)
    latency_ms = int((time.time() - start_time) * 1000)
    db.add(Message(message_id=str(uuid.uuid4()), session_id=session_id, role="user", content=redact_pii(user_message)))
    db.add(Message(message_id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=redact_pii(final_content), trace_id=trace_id))
    db.add(AgentTrace(trace_id=trace_id, session_id=session_id, routed_to=routed_to, tool_calls=tool_calls, retrieved_chunk_ids=list(set(retrieved_chunk_ids)), latency_ms=latency_ms))
    state.turn_count += 1
    state.last_agent = routed_to # type: ignore
    session_row.state = state.to_db_dict()
    await db.commit()

    # Emit the final 'done' event with routing details
    yield {"event": "done", "data": {"trace_id": trace_id, "routed_to": routed_to}}
