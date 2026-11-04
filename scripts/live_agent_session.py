import ast
import json
import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8765/v1/chat/completions"
HEADERS = {
    "Authorization": "Bearer changeme-local-token",
    "Content-Type": "application/json",
    "X-Tottie-Owner": "owner_local",
    "X-Tottie-Session": "live-agent-watch",
    "X-Tottie-Agent-Id": "antigravity-live",
    "X-Tottie-Agent-Name": "Antigravity Assistant",
}

TURNS = [
    {
        "title": "Turn 1: Teaching Tottie a new architecture convention",
        "prompt": "Important architecture decision: We are building Project Nova. The core database is CockroachDB distributed cluster on AWS us-east-1, and Sarah Chen is our team lead.",
        "wait_after": 18,
    },
    {
        "title": "Turn 2: Superseding an outdated fact (Database migration)",
        "prompt": "Correction on Project Nova: We cancelled CockroachDB due to latency issues. Project Nova is now strictly using ScyllaDB Enterprise.",
        "wait_after": 18,
    },
    {
        "title": "Turn 3: Testing associative recall (Grounding the agent)",
        "prompt": "Can you remind me what database Project Nova is using and who leads the team?",
        "wait_after": 10,
    },
]


def main():
    print("=== Starting 1-Minute Live Tottie Demonstration ===")
    print("Ensure browser is open at http://localhost:3055/?tab=graph&owner=owner_local")
    sys.stdout.flush()

    for i, turn in enumerate(TURNS, 1):
        print(f"\n[{time.strftime('%X')}] --- {turn['title']} ---")
        print(f"Prompt: {turn['prompt']}")
        sys.stdout.flush()
        t0 = time.time()
        try:
            resp = requests.post(
                BASE_URL,
                headers=HEADERS,
                json={
                    "model": "muse-spark-1.3-contributor",
                    "messages": [{"role": "user", "content": turn["prompt"]}],
                    "max_tokens": 1024,
                    "temperature": 0.2,
                },
                timeout=60,
            )
            dt = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                ans = data["choices"][0]["message"]["content"].strip()
                print(f"Tottie-Grounded Assistant ({dt:.2f}s):\n{ans}")
            else:
                print(f"Error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Request failed: {e}")
        sys.stdout.flush()

        if turn["wait_after"] > 0:
            print(f"Watching screen for {turn['wait_after']}s as memory curates, births, and animates...")
            sys.stdout.flush()
            time.sleep(turn["wait_after"])

    print("\n=== 1-Minute Live Demonstration Concluded Successfully ===")


if __name__ == "__main__":
    main()
