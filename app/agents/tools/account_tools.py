"""
Account-specific lookup tools for the Helix Specialist Agents.
Uses mock data structures to simulate internal database lookups.
"""
import uuid
from datetime import datetime, timedelta

# Mock database mapping user IDs to their account metadata.
# This represents internal account/billing state.
MOCK_ACCOUNTS = {
    "u1": {
        "plan_tier": "pro",
        "concurrent_builds_used": 2,
        "concurrent_builds_limit": 10,
        "storage_used_gb": 45.2,
        "storage_limit_gb": 100.0
    },
    "u2": {
        "plan_tier": "free",
        "concurrent_builds_used": 1,
        "concurrent_builds_limit": 1,
        "storage_used_gb": 0.5,
        "storage_limit_gb": 5.0
    }
}

async def get_recent_builds(user_id: str, limit: int = 5) -> list[dict]:
    """
    Simulates a database query for a user's recent build history.
    
    Args:
        user_id: The ID of the user whose builds are being requested.
        limit: Maximum number of builds to return (default 5).
        
    Returns:
        A list of dictionaries containing build status, ID, and timestamps.
    """
    # Deterministic mock status generation based on the user_id hash
    # (Ensures a consistent experience for specific test IDs)
    status = "failed" if hash(user_id) % 2 == 0 else "passed"
    
    builds = [
        {
            "build_id": f"b-{uuid.uuid4().hex[:8]}",
            "pipeline": "main-ci",
            "status": status if i == 0 else "passed",
            "branch": "feat/api-v2",
            "started_at": (datetime.utcnow() - timedelta(hours=i)).isoformat(),
            "duration_seconds": 120 + (i * 10)
        }
        for i in range(limit)
    ]
    return builds

async def get_account_status(user_id: str) -> dict:
    """
    Simulates a query to the billing/account management service.
    
    Returns:
        Usage statistics, current plan tier, and resource limits.
    """
    # Lookup in mock dictionary, defaulting to 'unknown' if the user_id is not in MOCK_ACCOUNTS
    account = MOCK_ACCOUNTS.get(user_id, {
        "plan_tier": "unknown",
        "concurrent_builds_used": 0,
        "concurrent_builds_limit": 0,
        "storage_used_gb": 0.0,
        "storage_limit_gb": 0.0
    })
    return {"user_id": user_id, **account}
