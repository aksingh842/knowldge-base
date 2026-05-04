import asyncio
import httpx
import sys
import os

# Add parent dir to path to import app settings if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://localhost:8000"
TEST_SESSION = "eval-session-123"

TEST_CASES = [
    {
        "query": "How do I rotate a deploy key?",
        "expected_agent": "knowledge"
    },
    {
        "query": "Show me my last 3 failed builds",
        "expected_agent": "account"
    },
    {
        "query": "I need to talk to a human, open a ticket",
        "expected_agent": "escalation"
    },
    {
        "query": "Hi, how are you?",
        "expected_agent": "smalltalk"
    },
    {
        "query": "Write me a poem about robots",
        "expected_agent": "smalltalk" # Should be refused by guardrails
    }
]

async def run_eval():
    print(f"🚀 Starting Eval Harness against {BASE_URL}...")
    
    # 1. Ensure user and session exist
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create user
        await client.post(f"{BASE_URL}/v1/setup/user", json={"user_id": "eval-user", "plan_tier": "pro"})
        # Create session
        await client.post(f"{BASE_URL}/v1/setup/session", json={"session_id": TEST_SESSION, "user_id": "eval-user"})

        correct = 0
        total = len(TEST_CASES)

        for i, case in enumerate(TEST_CASES):
            print(f"[{i+1}/{total}] Query: {case['query']}")
            
            # Note: We don't pass API key here, assuming server has it in .env or we pass it via header if needed.
            # But for eval, let's assume the server is configured.
            response = await client.post(
                f"{BASE_URL}/v1/chat/{TEST_SESSION}",
                json={"content": case["query"]}
            )
            
            if response.status_code != 200:
                print(f"  ❌ Error: {response.status_code} - {response.text}")
                continue
            
            data = response.json()
            actual_agent = data.get("routed_to")
            
            if actual_agent == case["expected_agent"]:
                print(f"  ✅ Correct: Routed to {actual_agent}")
                correct += 1
            else:
                print(f"  ❌ Incorrect: Expected {case['expected_agent']}, got {actual_agent}")

        accuracy = (correct / total) * 100
        print("\n" + "="*30)
        print(f"📊 FINAL ACCURACY: {accuracy:.1f}% ({correct}/{total})")
        print("="*30)

if __name__ == "__main__":
    asyncio.run(run_eval())
