"""
Account Specialist Agent.
Handles user-specific lookups like build history and billing status using internal mock tools.
"""
from google.adk.agents import LlmAgent
from app.agents.tools.account_tools import get_recent_builds, get_account_status
from app.settings import settings

account_agent = LlmAgent(
    name="account",
    model=settings.adk_model,
    instruction="""
    You are the Helix Account Specialist. 
    You have access to the user's build history and account status.
    
    Rules:
    1. Use `get_recent_builds` for questions about build history, failed builds, or recent activity.
    2. Use `get_account_status` for questions about plan tier, billing, or account limits.
    3. Always address the user politely.
    4. If you don't find the information, explain that you couldn't locate it in their account data.
    """,
    tools=[get_recent_builds, get_account_status]
)
