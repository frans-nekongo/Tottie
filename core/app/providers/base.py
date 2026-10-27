"""ModelProvider contract. Meta is primary; local is the fallback. See resolve.py."""
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ProviderError(RuntimeError):
    """The provider call failed (network, auth, bad shape, empty content)."""


class NoProviderAvailable(RuntimeError):
    """Auto mode found no healthy provider."""


class ModelProvider:
    name: str = "base"

    async def healthy(self) -> bool:
        raise NotImplementedError

    async def complete(
        self, messages: list[dict], *, max_tokens: int = 1024, json_object: bool = False
    ) -> Completion:
        raise NotImplementedError

    async def close(self) -> None:
        pass
