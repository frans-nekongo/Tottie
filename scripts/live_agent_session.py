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
    "X-Tottie-Session": "live-video-session",
    "X-Tottie-Agent-Id": "antigravity-live",
    "X-Tottie-Agent-Name": "Antigravity Assistant",
}

TURNS = [
    {
        "title": "Turn 1: Learning a New Architectural Fact",
        "prompt": "Key architecture decision: For Project Apex, our core cache layer is Redis Enterprise cluster on port 6380, and the lead architect is Elena Rostova.",
        "wait_after": 15,
    },
    {
        "title": "Turn 2: Superseding Outdated Knowledge (Live Reconcile)",
        "prompt": "Correction on Project Apex: We migrated away from Redis due to licensing. Project Apex now strictly uses Dragonfly on port 6379.",
        "wait_after": 15,
    },
    {
        "title": "Turn 3: Associative Recall (Context Card Grounding)",
        "prompt": "Can you remind me what cache Project Apex uses and who is the lead architect?",
        "wait_after": 5,
    },
]


def main():
    print("===================================================================")
    print("   TOTTIE LIVE MEMORY DEMONSTRATION (FILMING PREPARATION)")
    print("   Visualizer URL: http://localhost:3055/?tab=graph&owner=owner_local")
    print("===================================================================")
    print("\nStarting in 5 seconds — align your screen capture now!")
    for sec in range(5, 0, -1):
        print(f"  Recording in {sec}...", end="\r", flush=True)
        time.sleep(1)
    print("  >>> LIVE DEMONSTRATION STARTED <<<                 \n")
    sys.stdout.flush()

    for i, turn in enumerate(TURNS, 1):
        print(f"[{time.strftime('%X')}] --------------------------------------------------")
        print(f"[{time.strftime('%X')}] {turn['title']}")
        print(f"[{time.strftime('%X')}] User Prompt: {turn['prompt']}")
        print(f"[{time.strftime('%X')}] --------------------------------------------------")
        sys.stdout.flush()
        t0 = time.time()
        try:
            resp = requests.post(
                BASE_URL,
                headers=HEADERS,
                json={
                    "model": "muse-spark-1.3-contributor",
                    "messages": [{"role": "user", "content": turn["prompt"]}],
                    "max_tokens": 4096,
                    "temperature": 0.2,
                },
                timeout=60,
            )
            dt = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                ans = data["choices"][0]["message"]["content"].strip()
                print(f"[{time.strftime('%X')}] Tottie-Grounded Assistant ({dt:.2f}s):\n{ans}\n")
            else:
                print(f"[{time.strftime('%X')}] Error {resp.status_code}: {resp.text}\n")
        except Exception as e:
            print(f"[{time.strftime('%X')}] Request failed: {e}\n")
        sys.stdout.flush()

        if turn["wait_after"] > 0:
            print(f"[{time.strftime('%X')}] [Visualizer Camera] Watching 3D canvas for {turn['wait_after']}s (birth, camera swooping, and graph pulse)...")
            sys.stdout.flush()
            time.sleep(turn["wait_after"])

    print("\n===================================================================")
    print("   LIVE DEMONSTRATION COMPLETE — READY FOR SUBMISSION VIDEO")
    print("===================================================================")


if __name__ == "__main__":
    main()
