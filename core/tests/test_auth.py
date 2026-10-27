"""Auth gate, direct: valid passes, missing/wrong 401s, empty server token fails closed."""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.config import get_settings
from app.main import require_auth


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_valid_token_passes(monkeypatch):
    monkeypatch.setenv("TOTTIE_API_TOKEN", "secret")
    get_settings.cache_clear()
    assert await require_auth(_creds("secret")) == "secret"


@pytest.mark.asyncio
async def test_missing_and_wrong_rejected(monkeypatch):
    monkeypatch.setenv("TOTTIE_API_TOKEN", "secret")
    get_settings.cache_clear()
    for bad in (None, _creds(""), _creds("nope")):
        with pytest.raises(HTTPException) as e:
            await require_auth(bad)
        assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_server_token_fails_closed(monkeypatch):
    monkeypatch.setenv("TOTTIE_API_TOKEN", "")
    get_settings.cache_clear()
    for bad in (None, _creds(""), _creds("x")):
        with pytest.raises(HTTPException) as e:
            await require_auth(bad)
        assert e.value.status_code == 401
