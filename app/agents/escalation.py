"""
Escalation Specialist Agent.
Responsible for creating support tickets when specialists cannot resolve an issue.
"""
from google.adk.agents import LlmAgent
from app.agents.tools.ticket_tools import create_ticket
from app.settings import settings

escalation_agent = LlmAgent(
    name="escalation",
    model=settings.adk_model,
    instruction="""
    You are the Helix Escalation Specialist.
    If the Knowledge Agent or Account Agent cannot resolve a user's issue, or if the user explicitly asks to "open a ticket" or "talk to a human", you handle it.
    
    Rules:
    1. Use `create_ticket` to open a formal support ticket.
    2. The `user_id` is provided in the conversation context (System Message).
    3. Ask for a brief summary of the issue if it's not clear from the history.
    4. Provide the ticket ID back to the user once created.
    5. Be empathetic and professional.
    """,
    tools=[create_ticket]
)
