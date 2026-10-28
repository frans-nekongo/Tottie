"""ModelProvider contract. Meta is primary; local is the fallback. See resolve.py."""
import logging
from dataclasses import dataclass

log = logging.getLogger("tottie.provider")


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    resampled: bool = False


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


async def complete_resilient(provider: "ModelProvider", messages: list[dict], *,
                             max_tokens: int, json_object: bool = False,
                             retries: int = 1) -> Completion:
    """Complete with resampling on reasoning spirals. A finish=length with
    empty content means the model's reasoning ate the budget, not that the
    input is bad — R1 proved the identical retry then succeeds. Only the
    surviving attempt's tokens are countable (the error carries no usage)."""
    last: ProviderError | None = None
    for attempt in range(retries + 1):
        try:
            raw = await provider.complete(
                messages, max_tokens=max_tokens, json_object=json_object)
            raw.resampled = attempt > 0
            return raw
        except ProviderError as e:
            if "finish=length" not in str(e):
                raise
            last = e
            log.info("length-finish; resampling once")
    assert last is not None
    raise last
