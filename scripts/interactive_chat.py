#!/usr/bin/env python3
"""Interactive Terminal Chat for Tottie Live Video Recording.

Connects directly to the Tottie proxy (port 8765) using Meta's
muse-spark-1.3-contributor model. Every message typed here automatically:
  1. Prompts Meta's muse-spark-1.3-contributor with real-time streaming.
  2. Runs Tottie write-time observer to capture architectural facts into Postgres.
  3. Pushes real-time SSE birth events to the 3D visualizer at http://localhost:3055.
  4. Automatically injects <tottie_context> into subsequent turns.

Usage:
  ./core/venv/bin/python scripts/interactive_chat.py
"""

import ast
import json
import os
import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8765/v1/chat/completions"
HEADERS = {
    "Authorization": "Bearer changeme-local-token",
    "Content-Type": "application/json",
    "X-Tottie-Owner": "owner_local",
    "X-Tottie-Session": "interactive-live-session",
    "X-Tottie-Agent-Id": "muse-agent",
    "X-Tottie-Agent-Name": "Muse Architect",
}

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def main():
    print(f"\n{BOLD}{CYAN}==================================================================={RESET}")
    print(f"{BOLD}{CYAN}   TOTTIE INTERACTIVE AGENT TERMINAL (META MUSE-SPARK-1.3)   {RESET}")
    print(f"{DIM}   Visualizer: http://localhost:3055/?tab=graph&owner=owner_local{RESET}")
    print(f"{BOLD}{CYAN}==================================================================={RESET}")
    print(f"{DIM}Type your prompt below or press Ctrl+C to exit.{RESET}\n")

    history = []

    while True:
        try:
            prompt = input(f"{BOLD}{GREEN}You > {RESET}").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit"):
                break

            history.append({"role": "user", "content": prompt})

            print(f"\n{BOLD}{YELLOW}Muse Architect > {RESET}", end="", flush=True)
            t0 = time.time()

            resp = requests.post(
                BASE_URL,
                headers=HEADERS,
                json={
                    "model": "muse-spark-1.3-contributor",
                    "messages": history,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "stream": True,
                },
                stream=True,
                timeout=60,
            )

            full_reply = []
            if resp.status_code == 200:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_part = line_str[6:].strip()
                        if data_part == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_part)
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                                full_reply.append(delta)
                        except Exception:
                            continue
                reply_text = "".join(full_reply).strip()
                history.append({"role": "assistant", "content": reply_text})
                dt = time.time() - t0
                print(f"\n{DIM}(Generated in {dt:.2f}s | Tottie Memory Synthesized){RESET}\n")
            else:
                print(f"\nError {resp.status_code}: {resp.text}\n")

        except KeyboardInterrupt:
            print(f"\n{DIM}Session ended.{RESET}")
            break
        except Exception as e:
            print(f"\nRequest failed: {e}\n")


if __name__ == "__main__":
    main()
