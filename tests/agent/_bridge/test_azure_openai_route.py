"""Tests for Azure OpenAI API route handling in the bridge proxy."""

import re

import pytest


# The extraction regex used inside model_proxy_server() — tested standalone.
_AZURE_DEPLOYMENT_PATTERN = re.compile(r"deployments/([^/:]+)")


def _extract_model_from_azure_deployment_path(path: str) -> str:
    """Mirror of the function defined inside model_proxy_server()."""
    match = _AZURE_DEPLOYMENT_PATTERN.search(path)
    return match.group(1) if match else "inspect"


class TestExtractModelFromAzureDeploymentPath:
    """Test deployment name extraction from Azure OpenAI URL paths."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/v1/openai/deployments/gpt-4o/chat/completions", "gpt-4o"),
            ("/v1/openai/deployments/1p-planner/chat/completions", "1p-planner"),
            (
                "/v1/openai/deployments/my-deployment/chat/completions?api-version=2024-08-01-preview",
                "my-deployment",
            ),
            ("/v1/openai/deployments/model_v2/chat/completions", "model_v2"),
            (
                "/v1/openai/deployments/gpt-4o-2024-08-06/chat/completions",
                "gpt-4o-2024-08-06",
            ),
            ("/v1/openai/deployments/o3-mini/chat/completions", "o3-mini"),
        ],
    )
    def test_extracts_deployment_name(self, path: str, expected: str) -> None:
        assert _extract_model_from_azure_deployment_path(path) == expected

    def test_fallback_when_no_match(self) -> None:
        assert _extract_model_from_azure_deployment_path("/v1/chat/completions") == "inspect"

    def test_fallback_on_empty_path(self) -> None:
        assert _extract_model_from_azure_deployment_path("") == "inspect"

    def test_does_not_capture_port_after_colon(self) -> None:
        """Ensure the regex stops at colons (e.g., host:port fragments)."""
        match = _AZURE_DEPLOYMENT_PATTERN.search("deployments/gpt-4o:8080/chat")
        assert match is not None
        assert match.group(1) == "gpt-4o"


class TestAzureRouteMatching:
    """Test that AsyncHTTPServer._find_handler matches Azure-style paths."""

    def test_find_handler_matches_azure_deployment_path(self) -> None:
        from inspect_ai.agent._bridge.sandbox.proxy import AsyncHTTPServer

        server = AsyncHTTPServer()

        async def dummy_handler(request: dict) -> dict:  # type: ignore[type-arg]
            return {"status": 200}

        server.routes["POST"]["/v1/openai/deployments/*"] = dummy_handler

        # Various Azure paths should all match the wildcard route
        for path in [
            "/v1/openai/deployments/gpt-4o/chat/completions",
            "/v1/openai/deployments/my-model/chat/completions?api-version=2024-08-01",
            "/v1/openai/deployments/1p-planner/chat/completions",
        ]:
            handler = server._find_handler("POST", path)
            assert handler is dummy_handler, f"No handler matched for {path}"

    def test_find_handler_no_match_for_non_azure_path(self) -> None:
        from inspect_ai.agent._bridge.sandbox.proxy import AsyncHTTPServer

        server = AsyncHTTPServer()

        async def dummy_handler(request: dict) -> dict:  # type: ignore[type-arg]
            return {"status": 200}

        server.routes["POST"]["/v1/openai/deployments/*"] = dummy_handler

        # Standard OpenAI path should NOT match the Azure route
        assert server._find_handler("POST", "/v1/chat/completions") is None
