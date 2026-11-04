"""Tests for the transparent OpenAI-compatible proxy (/v1/chat/completions)."""
import json
import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_proxy_models_endpoint(client):
    r = await client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "tottie-memory-proxy" in ids


@pytest.mark.asyncio
async def test_proxy_chat_completions_non_streaming(client):
    payload = {
        "messages": [
            {"role": "system", "content": "You are a concise test assistant."},
            {"role": "user", "content": "Say hello."},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "stream": False,
    }
    r = await client.post("/v1/chat/completions", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert "choices" in body and len(body["choices"]) > 0
    choice = body["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert len(choice["message"]["content"]) > 0
    assert "usage" in body


@pytest.mark.asyncio
async def test_proxy_chat_completions_streaming(client):
    payload = {
        "messages": [
            {"role": "user", "content": "Say 'ok'."},
        ],
        "stream": True,
    }
    r = await client.post("/v1/chat/completions", json=payload)
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    text = r.text
    assert "data: " in text
    assert "[DONE]" in text


@pytest.mark.asyncio
async def test_proxy_auto_pairing_and_headers(client):
    auth_headers = {"Authorization": "Bearer test-token"}
    # Verify agent is auto-paired and custom headers work
    payload = {
        "messages": [
            {"role": "user", "content": "Remember: Project Pegasus uses Rust."},
        ],
        "stream": False,
    }
    headers = {
        "X-Tottie-Owner": "owner_local",
        "X-Tottie-Agent": "test_agent_proxy",
        "X-Tottie-Session": "proxy-test-sess",
    }
    r = await client.post("/v1/chat/completions", json=payload, headers=headers)
    assert r.status_code == 200

    # Check agent presence is marked connected
    agents_res = await client.get("/agents?owner=owner_local", headers=auth_headers)
    assert agents_res.status_code == 200
    agents_list = agents_res.json().get("agents", [])
    matching = [a for a in agents_list if a["id"] == "test_agent_proxy"]
    assert len(matching) == 1
    assert matching[0]["connected"] is True
