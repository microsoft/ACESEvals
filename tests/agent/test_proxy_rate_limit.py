"""Tests for rate-limit error detection and propagation in the model proxy.

When the upstream model API returns HTTP 429 (Too Many Requests), the proxy
should propagate the error to the CLI as a 429 response instead of masking
it as a generic 500.  This allows the CLI (e.g. Claude Code) to apply its
own retry/back-off logic rather than blocking indefinitely while the host
retries via tenacity.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from inspect_ai.agent._bridge.sandbox.proxy import (
    _is_rate_limit_error,
    _rate_limit_error_response,
    model_proxy_server,
)

# ---------------------------------------------------------------------------
# _is_rate_limit_error
# ---------------------------------------------------------------------------


class TestIsRateLimitError:
    """Verify that _is_rate_limit_error correctly detects 429 / rate-limit exceptions."""

    def test_classic_429_too_many_requests(self) -> None:
        ex = Exception(
            "Error calling method generate_anthropic: Error code: 429 - "
            "{'error': {'message': 'Too Many Requests', 'type': 'too_many_requests'}}"
        )
        assert _is_rate_limit_error(ex) is True

    def test_rate_limit_exceeded_message(self) -> None:
        ex = Exception(
            "Error calling method generate_responses: Error code: 429 - "
            "{'error': {'message': 'Rate limit exceeded', 'type': 'rate_limit_error'}}"
        )
        assert _is_rate_limit_error(ex) is True

    def test_openai_rate_limit_message(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota.', "
            "'type': 'insufficient_quota'}}"
        )
        assert _is_rate_limit_error(ex) is True

    def test_generic_500_is_not_rate_limit(self) -> None:
        ex = Exception("Internal server error")
        assert _is_rate_limit_error(ex) is False

    def test_unrelated_429_text_without_error_code(self) -> None:
        """A message that merely mentions '429' but isn't a real rate-limit."""
        ex = Exception("Received 429 bytes of data")
        assert _is_rate_limit_error(ex) is False

    def test_timeout_is_not_rate_limit(self) -> None:
        ex = TimeoutError("Connection timed out")
        assert _is_rate_limit_error(ex) is False

    def test_connection_error_not_rate_limit(self) -> None:
        ex = ConnectionError("Connection refused")
        assert _is_rate_limit_error(ex) is False

    def test_overloaded_error(self) -> None:
        ex = Exception(
            "Error code: 529 - {'error': {'message': 'Overloaded', "
            "'type': 'overloaded_error'}}"
        )
        assert _is_rate_limit_error(ex) is True

    def test_resource_exhausted_error(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Resource exhausted', "
            "'type': 'resource_exhausted'}}"
        )
        assert _is_rate_limit_error(ex) is True


# ---------------------------------------------------------------------------
# _rate_limit_error_response
# ---------------------------------------------------------------------------


class TestRateLimitErrorResponse:
    """Verify correct HTTP response shapes for different endpoint formats."""

    def test_anthropic_non_streaming(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Too Many Requests', "
            "'type': 'too_many_requests'}}"
        )
        resp = _rate_limit_error_response(ex, stream=False, endpoint="anthropic")
        assert resp["status"] == 429
        body = resp["body"]
        assert body["type"] == "error"
        assert body["error"]["type"] == "rate_limit_error"
        assert "429" in body["error"]["message"] or "rate" in body["error"]["message"].lower()

    def test_anthropic_streaming(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Too Many Requests', "
            "'type': 'too_many_requests'}}"
        )
        resp = _rate_limit_error_response(ex, stream=True, endpoint="anthropic")
        assert resp["status"] == 429
        assert "body_iter" in resp
        assert resp["chunked"] is True

    def test_openai_non_streaming(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit exceeded'}}"
        )
        resp = _rate_limit_error_response(ex, stream=False, endpoint="openai")
        assert resp["status"] == 429
        body = resp["body"]
        assert body["error"]["type"] == "rate_limit_error"

    def test_openai_streaming(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit exceeded'}}"
        )
        resp = _rate_limit_error_response(ex, stream=True, endpoint="openai")
        assert resp["status"] == 429
        assert "body_iter" in resp
        assert resp["chunked"] is True


# ---------------------------------------------------------------------------
# Anthropic streaming SSE format
# ---------------------------------------------------------------------------


class TestAnthropicStreamingRateLimitSSE:
    """When streaming=True on /v1/messages, the 429 should produce a proper SSE error event."""

    @pytest.mark.anyio
    async def test_sse_error_event_format(self) -> None:
        ex = Exception(
            "Error code: 429 - {'error': {'message': 'Too Many Requests', "
            "'type': 'too_many_requests'}}"
        )
        resp = _rate_limit_error_response(ex, stream=True, endpoint="anthropic")
        chunks: list[bytes] = []
        async for chunk in resp["body_iter"]:
            chunks.append(chunk)

        # Should have exactly one SSE event
        assert len(chunks) == 1
        sse_text = chunks[0].decode("utf-8")
        assert "event: error" in sse_text
        assert "data:" in sse_text

        # Parse the data payload
        data_line = [
            line for line in sse_text.split("\n") if line.startswith("data:")
        ][0]
        data_json = json.loads(data_line[len("data: "):])
        assert data_json["type"] == "error"
        assert data_json["error"]["type"] == "rate_limit_error"


# ---------------------------------------------------------------------------
# Integration-level: /v1/messages endpoint returns 429
# ---------------------------------------------------------------------------


class TestAnthropicEndpointReturns429:
    """Exercise the full /v1/messages handler with a rate-limit exception."""

    @pytest.mark.anyio
    async def test_non_streaming_returns_429(self) -> None:
        rate_limit_ex = Exception(
            "Error calling method generate_anthropic: Error code: 429 - "
            "{'error': {'message': 'Too Many Requests', 'type': 'too_many_requests'}}: "
            "Traceback (most recent call last)..."
        )
        mock_bridge = AsyncMock(side_effect=rate_limit_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/messages"]
        request: dict[str, object] = {
            "json": {"model": "claude-3", "messages": [], "stream": False},
        }
        resp = await handler(request)
        assert resp["status"] == 429
        body = resp["body"]
        assert body["type"] == "error"
        assert body["error"]["type"] == "rate_limit_error"

    @pytest.mark.anyio
    async def test_streaming_returns_429_sse(self) -> None:
        rate_limit_ex = Exception(
            "Error calling method generate_anthropic: Error code: 429 - "
            "{'error': {'message': 'Too Many Requests', 'type': 'too_many_requests'}}"
        )
        mock_bridge = AsyncMock(side_effect=rate_limit_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/messages"]
        request: dict[str, object] = {
            "json": {"model": "claude-3", "messages": [], "stream": True},
        }
        resp = await handler(request)
        assert resp["status"] == 429
        assert "body_iter" in resp


# ---------------------------------------------------------------------------
# Integration-level: /v1/responses endpoint returns 429
# ---------------------------------------------------------------------------


class TestResponsesEndpointReturns429:
    """Exercise the /v1/responses handler with a rate-limit exception."""

    @pytest.mark.anyio
    async def test_non_streaming_returns_429(self) -> None:
        rate_limit_ex = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit exceeded', "
            "'type': 'rate_limit_error'}}"
        )
        mock_bridge = AsyncMock(side_effect=rate_limit_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/responses"]
        request: dict[str, object] = {
            "json": {"model": "gpt-4", "input": "hello", "stream": False},
        }
        resp = await handler(request)
        assert resp["status"] == 429
        body = resp["body"]
        assert body["error"]["type"] == "rate_limit_error"


# ---------------------------------------------------------------------------
# Integration-level: /v1/chat/completions endpoint returns 429
# ---------------------------------------------------------------------------


class TestCompletionsEndpointReturns429:
    """Exercise the /v1/chat/completions handler with a rate-limit exception."""

    @pytest.mark.anyio
    async def test_non_streaming_returns_429(self) -> None:
        rate_limit_ex = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit exceeded', "
            "'type': 'rate_limit_error'}}"
        )
        mock_bridge = AsyncMock(side_effect=rate_limit_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/chat/completions"]
        request: dict[str, object] = {
            "json": {"model": "gpt-4", "messages": [], "stream": False},
        }
        resp = await handler(request)
        assert resp["status"] == 429
        body = resp["body"]
        assert body["error"]["type"] == "rate_limit_error"


# ---------------------------------------------------------------------------
# Integration-level: Google endpoint returns 429
# ---------------------------------------------------------------------------


class TestGoogleEndpointReturns429:
    """Exercise the Google API handler with a rate-limit exception."""

    @pytest.mark.anyio
    async def test_non_streaming_returns_429(self) -> None:
        rate_limit_ex = Exception(
            "Error code: 429 - {'error': {'message': 'Resource exhausted', "
            "'type': 'resource_exhausted'}}"
        )
        mock_bridge = AsyncMock(side_effect=rate_limit_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        # Google routes use wildcard — find the handler
        handler = server._find_handler("POST", "/v1beta/models/gemini-pro:generateContent")
        assert handler is not None
        request: dict[str, object] = {
            "path": "/v1beta/models/gemini-pro:generateContent",
            "json": {"contents": []},
        }
        resp = await handler(request)
        assert resp["status"] == 429


# ---------------------------------------------------------------------------
# Non-rate-limit errors should still return 500
# ---------------------------------------------------------------------------


class TestNonRateLimitErrorsStill500:
    """Ensure non-rate-limit errors are not upgraded to 429."""

    @pytest.mark.anyio
    async def test_generic_error_returns_500(self) -> None:
        generic_ex = Exception("Something went wrong internally")
        mock_bridge = AsyncMock(side_effect=generic_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/messages"]
        request: dict[str, object] = {
            "json": {"model": "claude-3", "messages": [], "stream": False},
        }
        resp = await handler(request)
        assert resp["status"] == 500
        assert resp["body"]["error"]["type"] == "proxy_error"

    @pytest.mark.anyio
    async def test_timeout_error_returns_500(self) -> None:
        timeout_ex = TimeoutError("Connection timed out")
        mock_bridge = AsyncMock(side_effect=timeout_ex)
        server = await model_proxy_server(
            port=0, call_bridge_model_service_async=mock_bridge
        )

        handler = server.routes["POST"]["/v1/messages"]
        request: dict[str, object] = {
            "json": {"model": "claude-3", "messages": [], "stream": False},
        }
        resp = await handler(request)
        assert resp["status"] == 500


# ---------------------------------------------------------------------------
# GenerateConfig max_retries in bridge config builders
# ---------------------------------------------------------------------------


class TestBridgeGenerateConfigMaxRetries:
    """Config builders should set max_retries to limit tenacity retries."""

    def test_anthropic_config_sets_max_retries(self) -> None:
        from inspect_ai.agent._bridge.anthropic_api_impl import (
            generate_config_from_anthropic,
        )

        config = generate_config_from_anthropic({"max_tokens": 1024})
        assert config.max_retries is not None
        assert config.max_retries <= 5  # reasonable upper bound
        assert config.max_retries >= 1  # at least one retry

    def test_openai_completions_config_sets_max_retries(self) -> None:
        from inspect_ai.agent._bridge.completions import (
            generate_config_from_openai_completions,
        )

        config = generate_config_from_openai_completions({"model": "gpt-4"})
        assert config.max_retries is not None
        assert config.max_retries <= 5
        assert config.max_retries >= 1

    def test_openai_responses_config_sets_max_retries(self) -> None:
        from inspect_ai.agent._bridge.responses_impl import (
            generate_config_from_openai_responses,
        )

        config = generate_config_from_openai_responses({})
        assert config.max_retries is not None
        assert config.max_retries <= 5
        assert config.max_retries >= 1
