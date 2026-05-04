"""
Support ticketing tools for the Helix Escalation Specialist.
Handles formal ticket creation in the shared SQLite database.
"""
import uuid
from app.db.session import AsyncSessionLocal
from app.db.models import Ticket

async def create_ticket(user_id: str, summary: str, priority: str = "medium") -> str:
    """
    Creates a formal support ticket in the 'tickets' table.
    Ensures that user issues can be tracked by human support staff.
    
    Args:
        user_id: The ID of the user requesting help.
        summary: A brief description of the issue.
        priority: 'low', 'medium', or 'high'.
        
    Returns:
        The newly generated Ticket ID (e.g., TICK-8F2A1B).
    """
    # Generate a readable, unique ticket identifier
    ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"
    
    # Use a fresh standalone DB session to ensure the ticket is saved
    # even if the main pipeline transaction is still pending.
    async with AsyncSessionLocal() as db:
        new_ticket = Ticket(
            ticket_id=ticket_id,
            user_id=user_id,
            summary=summary,
            priority=priority
        )
        db.add(new_ticket)
        await db.commit()
    
    return ticket_id
