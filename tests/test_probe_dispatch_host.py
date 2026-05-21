"""Unit tests for probe_dispatch_host — direct tests with mocked httpx."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_gtd.services.dispatch_router import probe_dispatch_host

_PATCH_PATH = "agent_gtd.services.dispatch_router.httpx.AsyncClient"


def _mock_ctx(
    get_return: object = None,
    get_side_effect: object = None,
) -> MagicMock:
    """Return an async-context-manager mock for httpx.AsyncClient."""
    mock_client = AsyncMock()
    if get_side_effect is not None:
        mock_client.get.side_effect = get_side_effect
    else:
        mock_client.get.return_value = get_return
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _resp(
    status_code: int = 200,
    json_data: object = None,
    raise_json: bool = False,
    reason_phrase: str = "OK",
) -> MagicMock:
    """Build a minimal mock httpx Response."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.reason_phrase = reason_phrase
    if raise_json:
        r.json.side_effect = ValueError("not JSON")
    else:
        r.json.return_value = (
            json_data if json_data is not None else {"engine": "claude-code"}
        )
    return r


@pytest.mark.asyncio
async def test_probe_success() -> None:
    """probe_dispatch_host returns None on a valid host."""
    ctx = _mock_ctx(get_return=_resp())
    with patch(_PATCH_PATH, return_value=ctx):
        result = await probe_dispatch_host("http://host.local:8001", "api-key")
    assert result is None
    ctx.__aenter__.return_value.get.assert_called_once_with(
        "http://host.local:8001/info",
        headers={"Authorization": "Bearer api-key"},
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_probe_timeout() -> None:
    """probe_dispatch_host raises ValueError on timeout."""
    ctx = _mock_ctx(get_side_effect=httpx.TimeoutException("timed out"))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="Timed out after 10s"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_connect_error() -> None:
    """probe_dispatch_host raises ValueError on connection refused."""
    ctx = _mock_ctx(get_side_effect=httpx.ConnectError("refused"))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="Connection refused"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_request_error() -> None:
    """probe_dispatch_host raises ValueError on generic request error."""
    ctx = _mock_ctx(get_side_effect=httpx.RequestError("network error"))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="Request failed"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_http_non_200() -> None:
    """probe_dispatch_host raises ValueError on non-200 HTTP status."""
    ctx = _mock_ctx(get_return=_resp(status_code=401, reason_phrase="Unauthorized"))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="HTTP 401 Unauthorized"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_invalid_json() -> None:
    """probe_dispatch_host raises ValueError when response is not valid JSON."""
    ctx = _mock_ctx(get_return=_resp(raise_json=True))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="not valid JSON"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_missing_engine_key() -> None:
    """probe_dispatch_host raises ValueError when 'engine' key is absent."""
    ctx = _mock_ctx(get_return=_resp(json_data={"version": "1.0"}))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="missing required field: engine"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_non_dict_json() -> None:
    """probe_dispatch_host raises ValueError when JSON is not a dict."""
    ctx = _mock_ctx(get_return=_resp(json_data=["not", "a", "dict"]))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="missing required field: engine"),
    ):
        await probe_dispatch_host("http://host.local", "key")


@pytest.mark.asyncio
async def test_probe_custom_timeout() -> None:
    """probe_dispatch_host passes custom timeout and includes it in error message."""
    ctx = _mock_ctx(get_side_effect=httpx.TimeoutException("timed out"))
    with (
        patch(_PATCH_PATH, return_value=ctx),
        pytest.raises(ValueError, match="Timed out after 5s"),
    ):
        await probe_dispatch_host("http://host.local", "key", timeout=5.0)
