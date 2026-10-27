"""Meta Model API provider (primary). OpenAI-compatible Chat Completions.

Verified 2026-10-27: reasoning model — max_tokens yields null content, so we
send max_completion_tokens; temperature 0 accepted; health via GET /models.
"""
import httpx

from .base import Completion, ModelProvider, ProviderError


class MetaProvider(ModelProvider):
    name = "meta"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base = (base_url or "").rstrip("/")
        self._key = api_key or ""
        self._model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(90.0))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    async def healthy(self) -> bool:
        if not self._key or not self._base:
            return False
        try:
            r = await self._client.get(f"{self._base}/models", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def complete(
        self, messages: list[dict], *, max_tokens: int = 1024, json_object: bool = False
    ) -> Completion:
        body: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "max_completion_tokens": max_tokens,
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}
        try:
            r = await self._client.post(
                f"{self._base}/chat/completions", json=body, headers=self._headers()
            )
        except Exception as e:
            raise ProviderError(f"meta unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"meta {r.status_code}: {r.text[:300]}")
        try:
            choice = r.json()["choices"][0]
            text = choice["message"].get("content") or ""
            finish = choice.get("finish_reason", "?")
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"meta: bad response shape: {e}") from e
        if not text.strip():
            hint = (
                " (reasoning ate the whole budget; raise max_tokens)"
                if finish == "length"
                else ""
            )
            raise ProviderError(f"meta: empty content (finish={finish}){hint}")
        usage = r.json().get("usage", {}) or {}
        return Completion(
            text=text,
            model=self._model,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    async def close(self) -> None:
        await self._client.aclose()
