"""Local fallback provider: Ollama native API (nkngo-qwen-coder-3b from local GGUF).

Native /api/chat is used instead of the OpenAI shim: its format:'json' mode is
documented behavior on small models. Health is GET /api/tags (cheap, no load).
"""
import httpx

from .base import Completion, ModelProvider, ProviderError


class LocalProvider(ModelProvider):
    name = "local"

    def __init__(self, base_url: str, model: str) -> None:
        self._base = (base_url or "").rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    async def healthy(self) -> bool:
        if not self._base:
            return False
        try:
            r = await self._client.get(f"{self._base}/api/tags")
            return r.status_code == 200
        except Exception:
            return False

    async def complete(
        self, messages: list[dict], *, max_tokens: int = 1024, json_object: bool = False
    ) -> Completion:
        body: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens},
        }
        if json_object:
            body["format"] = "json"
        try:
            r = await self._client.post(f"{self._base}/api/chat", json=body)
        except Exception as e:
            raise ProviderError(f"local unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"local {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
            text = (data.get("message") or {}).get("content") or ""
        except ValueError as e:
            raise ProviderError(f"local: bad response shape: {e}") from e
        if not text.strip():
            raise ProviderError("local: empty content")
        return Completion(
            text=text,
            model=self._model,
            prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
            completion_tokens=int(data.get("eval_count", 0) or 0),
        )

    async def close(self) -> None:
        await self._client.aclose()
