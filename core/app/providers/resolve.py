"""Provider selection. TOTTIE_PROVIDER=auto|meta|local — read fresh from a new
Settings() on EVERY call, so flipping the variable (.env edit or export) switches
the brain with no restart. Assumes server cwd=core/ (Makefile, orch, tests).

- auto: meta if healthy, else local if healthy, else NoProviderAvailable.
- meta / local: pinned, no fallback, fail loud (explicit choice).
Health probes are cached 120s; a provider can still fail mid-call, in which
case the Scribe's raw fallback (not a second provider) catches it.
"""
import time

from ..config import Settings
from .base import ModelProvider, NoProviderAvailable, ProviderError
from .local import LocalProvider
from .meta import MetaProvider

_HEALTH_TTL = 120.0
_cache: dict[str, tuple[bool, float]] = {}


async def _healthy(provider: ModelProvider) -> bool:
    hit = _cache.get(provider.name)
    if hit is not None and time.time() - hit[1] < _HEALTH_TTL:
        return hit[0]
    try:
        ok = await provider.healthy()
    except Exception:
        ok = False
    _cache[provider.name] = (ok, time.time())
    return ok


def _build(settings: Settings, which: str) -> ModelProvider:
    if which == "meta":
        return MetaProvider(
            settings.meta_base_url, settings.meta_api_key, settings.meta_model
        )
    return LocalProvider(settings.local_llm_url, settings.local_llm_model)


async def resolve_provider() -> ModelProvider:
    settings = Settings()  # fresh every call: hot-switch without restart
    mode = (settings.provider or "auto").strip().lower()
    if mode not in ("auto", "meta", "local"):
        raise ProviderError(f"TOTTIE_PROVIDER={mode!r}: want auto|meta|local")
    if mode == "auto":
        meta = _build(settings, "meta")
        if await _healthy(meta):
            return meta
        await meta.close()
        local = _build(settings, "local")
        if await _healthy(local):
            return local
        await local.close()
        raise NoProviderAvailable("neither meta nor local is healthy")
    return _build(settings, mode)
