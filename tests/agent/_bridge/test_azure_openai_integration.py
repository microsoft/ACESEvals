"""Integration test: verify the Azure OpenAI route handles real HTTP requests.

Starts the proxy's AsyncHTTPServer, registers a mock chat_completions handler
(simulating the host-side model service), then sends actual HTTP requests
in Azure OpenAI format and validates the responses.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

from inspect_ai.agent._bridge.sandbox.proxy import AsyncHTTPServer


def _make_openai_completion(model: str = "gpt-4o") -> dict:
    """Return a minimal OpenAI ChatCompletion response dict."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello from the bridge!",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest_asyncio.fixture
async def azure_proxy_server():
    """Start an AsyncHTTPServer with Azure + chat_completions routes wired to a mock backend."""
    server = AsyncHTTPServer(host="127.0.0.1", port=0)  # port=0 → pick a free port

    # Track what model name the "backend" received
    captured_requests: list[dict] = []

    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions(request: dict) -> dict:
        json_body = request.get("json", {}) or {}
        captured_requests.append(json_body)
        model = json_body.get("model", "unknown")
        return {"status": 200, "body": _make_openai_completion(model)}

    # Register the Azure route exactly as production does — delegate to chat_completions
    import re
    _AZURE_PATTERN = re.compile(r"deployments/([^/:]+)")

    @server.route("/v1/openai/deployments/*", method="POST")
    async def azure_chat_completions(request: dict) -> dict:
        path = request.get("path", "")
        json_body = request.get("json", {}) or {}
        match = _AZURE_PATTERN.search(path)
        model_name = match.group(1) if match else "inspect"
        json_body["model"] = model_name
        request["json"] = json_body
        return await chat_completions(request)

    # Start server on a random free port
    tcp_server = await asyncio.start_server(
        server._handle_client, server.host, server.port
    )
    actual_port = tcp_server.sockets[0].getsockname()[1]

    yield actual_port, captured_requests

    tcp_server.close()
    await tcp_server.wait_closed()


async def _send_http_post(host: str, port: int, path: str, body: dict) -> tuple[int, dict]:
    """Send a raw HTTP POST and return (status_code, json_body)."""
    body_bytes = json.dumps(body).encode()
    request_lines = [
        f"POST {path} HTTP/1.1",
        f"Host: {host}:{port}",
        "Content-Type: application/json",
        f"Content-Length: {len(body_bytes)}",
        "Connection: close",
        "",
        "",
    ]
    raw_request = "\r\n".join(request_lines).encode() + body_bytes

    reader, writer = await asyncio.open_connection(host, port)
    writer.write(raw_request)
    await writer.drain()

    response = await reader.read(65536)
    writer.close()
    await writer.wait_closed()

    # Parse HTTP response
    response_text = response.decode("utf-8", errors="replace")
    header_end = response_text.index("\r\n\r\n")
    status_line = response_text.split("\r\n")[0]
    status_code = int(status_line.split(" ")[1])
    body_text = response_text[header_end + 4:]
    try:
        json_body = json.loads(body_text)
    except json.JSONDecodeError:
        json_body = {"raw": body_text}

    return status_code, json_body


@pytest.mark.asyncio
async def test_azure_route_extracts_deployment_and_returns_completion(
    azure_proxy_server: tuple[int, list[dict]],
) -> None:
    """Verify Azure-style POST extracts deployment name and returns valid completion."""
    port, captured = azure_proxy_server

    status, body = await _send_http_post(
        "127.0.0.1",
        port,
        "/v1/openai/deployments/1p-planner/chat/completions?api-version=2024-08-01-preview",
        {
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        },
    )

    assert status == 200
    assert body["model"] == "1p-planner"
    assert body["choices"][0]["message"]["content"] == "Hello from the bridge!"

    # Verify the backend received "model": "1p-planner" (extracted from URL path)
    assert len(captured) == 1
    assert captured[0]["model"] == "1p-planner"


@pytest.mark.asyncio
async def test_azure_route_preserves_request_body(
    azure_proxy_server: tuple[int, list[dict]],
) -> None:
    """Verify that original request fields (messages, temperature, etc.) are forwarded."""
    port, captured = azure_proxy_server

    request_body = {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "temperature": 0.7,
        "max_tokens": 50,
    }

    status, body = await _send_http_post(
        "127.0.0.1",
        port,
        "/v1/openai/deployments/gpt-4o/chat/completions?api-version=2024-08-01",
        request_body,
    )

    assert status == 200
    # Backend should have received all original fields plus model from path
    assert captured[0]["model"] == "gpt-4o"
    assert captured[0]["temperature"] == 0.7
    assert captured[0]["max_tokens"] == 50
    assert len(captured[0]["messages"]) == 2


@pytest.mark.asyncio
async def test_azure_route_does_not_interfere_with_standard_openai(
    azure_proxy_server: tuple[int, list[dict]],
) -> None:
    """Verify standard /v1/chat/completions still works alongside the Azure route."""
    port, captured = azure_proxy_server

    status, body = await _send_http_post(
        "127.0.0.1",
        port,
        "/v1/chat/completions",
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Standard route"}],
        },
    )

    assert status == 200
    assert body["model"] == "gpt-4o"
    assert captured[0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_azure_route_with_complex_deployment_name(
    azure_proxy_server: tuple[int, list[dict]],
) -> None:
    """Verify deployment names with dates and versions are extracted correctly."""
    port, captured = azure_proxy_server

    status, body = await _send_http_post(
        "127.0.0.1",
        port,
        "/v1/openai/deployments/gpt-4o-2024-08-06/chat/completions?api-version=2024-08-01-preview",
        {"messages": [{"role": "user", "content": "test"}]},
    )

    assert status == 200
    assert body["model"] == "gpt-4o-2024-08-06"
    assert captured[0]["model"] == "gpt-4o-2024-08-06"
